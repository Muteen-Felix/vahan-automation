"""Worker limits and historical workbooks in a guarded disposable database."""
import asyncio
import io
import unittest
from datetime import datetime, timezone
from uuid import uuid4

import test_report_results as fixture  # Guards the database and migrates before app imports.
from openpyxl import Workbook
from sqlalchemy import select, update
from starlette.requests import Request
from app.api.batch_queue import QueueTaskInput
from app.api.annual_reports import annual_reports
from app.api.report_coverage import CoverageQuery, report_coverage
from app.db import engine, schema as db
from app.models.job import Job, JobStatus
from app.repositories.batch_queue import BatchQueueRepository
from app.repositories.file_store import PostgresFileStore
from app.repositories.postgres import job_document, release_runner
from app.repositories.annual_reports import month_column
from app.services import services

class RunControlsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        self.owner = 'controls-' + str(uuid4())
        await services.users.bootstrap(self.owner, 'fixture-only-password')
        self.runners = [self.owner + '-' + str(index) for index in range(10)]
        for runner in self.runners:
            await services.runners.register(runner_id=runner, name=runner, socket_id=runner)
        self.queue = BatchQueueRepository()
        self.tasks = [QueueTaskInput(name=f'Office {index} (2024)', filters={
            'states': ['Fixture State'], 'rtos': [f'Office {index} - TS{index}'],
            'fromYear': '2024', 'toYear': '2024', 'yAxis': 'Maker', 'xAxis': 'Month Wise',
        }) for index in range(12)]

    async def asyncTearDown(self):
        await engine.dispose()

    async def finish(self, job_id, status=JobStatus.COMPLETED):
        async with engine.begin() as connection:
            payload = await connection.scalar(select(db.jobs.c.payload).where(db.jobs.c.id == job_id))
            job = Job.model_validate(payload); job.status = status; job.touch()
            await connection.execute(update(db.jobs).where(db.jobs.c.id == job_id).values(
                status=status.value, payload=job_document(job), updated_at=job.updated_at))
            await release_runner(connection, job.runner_id, job.id)

    async def test_five_worker_limit_is_enforced_across_ten_claimants(self):
        session = uuid4()
        await self.queue.start(session, self.owner, self.tasks, 5)
        claims = await asyncio.gather(*(self.queue.claim(session, self.owner, runner) for runner in self.runners))
        self.assertEqual(sum(item['type'] == 'assigned' for item in claims), 5)
        self.assertEqual(sum(item['type'] == 'waiting' for item in claims), 5)
        snapshot = await self.queue.snapshot(session, self.owner)
        self.assertEqual(snapshot['maxWorkers'], 5)
        self.assertEqual(sum(task['status'] == 'PROCESSING' for task in snapshot['tasks']), 5)
        with self.assertRaises(ValueError):
            await self.queue.start(session, self.owner, self.tasks, 10)

    async def test_pause_and_reduce_workers_preserves_completed_cases(self):
        session = uuid4()
        await self.queue.start(session, self.owner, self.tasks, 5)
        claims = [await self.queue.claim(session, self.owner, runner) for runner in self.runners[:5]]
        await self.queue.set_status(session, self.owner, 'PAUSED')
        with self.assertRaises(ValueError):
            await self.queue.set_status(session, self.owner, 'RUNNING', 1)
        for claim in claims:
            await self.finish(claim['jobId'])
        await self.queue.set_status(session, self.owner, 'RUNNING', 1)
        snapshot = await self.queue.snapshot(session, self.owner)
        self.assertEqual(snapshot['maxWorkers'], 1)
        self.assertEqual(sum(task['status'] == 'COMPLETED' for task in snapshot['tasks']), 5)
        following = await self.queue.claim(session, self.owner, self.runners[0])
        self.assertEqual(following['task']['position'], 5)
        self.assertEqual((await self.queue.claim(session, self.owner, self.runners[1]))['type'], 'waiting')

    async def test_one_worker_can_retry_its_own_failed_case(self):
        session = uuid4()
        await self.queue.start(session, self.owner, self.tasks, 1)
        first = await self.queue.claim(session, self.owner, self.runners[0])
        await self.finish(first['jobId'], JobStatus.FAILED)
        await self.queue.settle(session, self.owner, 0)

        # The retry waits for the current 10-case checkpoint to finish before
        # the queue advances to that group's retry phase.
        for position in range(1, 10):
            item = await self.queue.claim(session, self.owner, self.runners[0])
            self.assertEqual(item['task']['position'], position)
            await self.finish(item['jobId'])
            await self.queue.settle(session, self.owner, position)

        retry = await self.queue.claim(session, self.owner, self.runners[0])
        self.assertEqual(retry['type'], 'assigned')
        self.assertEqual(retry['task']['position'], 0)
        self.assertEqual(retry['task']['attempts'], 2)
        await self.finish(retry['jobId'], JobStatus.NO_DATA)
        await self.queue.settle(session, self.owner, 0)
        self.assertEqual((await self.queue.claim(session, self.owner, self.runners[0]))['task']['position'], 10)

    async def test_historical_workbook_is_saved_and_read_in_its_own_year(self):
        job = await services.jobs.create(Job(runnerId=self.runners[0], ownerUsername=self.owner,
            status=JobStatus.WAITING_RESULT, filters=self.tasks[0].filters))
        workbook = Workbook(); workbook.active.append(['Maker', "JAN'24"]); workbook.active.append(['Historical maker', 17])
        content = io.BytesIO(); workbook.save(content); workbook.close()
        await PostgresFileStore().commit_excel(job.id, 'historic.xlsx', content.getvalue(),
            observed_at=datetime.now(timezone.utc), runner_id=job.runner_id)
        request = Request({'type': 'http', 'headers': []}); request.state.authenticated_user = self.owner
        request.state.authenticated_role = 'admin'
        result = await annual_reports(request, year=2024, dataset='', state='Fixture State', rto='TS0', offset=0, limit=100)
        self.assertEqual(result['rows'][0]['months'][0], 17)
        self.assertEqual(result['rows'][0]['year'], 2024)
        coverage = await report_coverage(CoverageQuery(year=2024, scenarios=[{
            'name': task.name, 'filters': task.filters.model_dump(mode='json', by_alias=True)
        } for task in self.tasks]), request)
        self.assertEqual(coverage['covered'], 1)
        self.assertTrue(coverage['canContinue'], 'historical years can continue missing offices')
        self.assertEqual(month_column("JAN'99", 1999), (1999, 1))

    async def test_wrong_year_workbook_does_not_commit(self):
        job = await services.jobs.create(Job(runnerId=self.runners[0], ownerUsername=self.owner,
            status=JobStatus.WAITING_RESULT, filters=self.tasks[1].filters))
        workbook = Workbook(); workbook.active.append(['Maker', '2026-Jan']); workbook.active.append(['Maker', 8])
        content = io.BytesIO(); workbook.save(content); workbook.close()
        with self.assertRaisesRegex(ValueError, 'MAIN_REPORT_YEAR_MISMATCH'):
            await PostgresFileStore().commit_excel(job.id, 'wrong.xlsx', content.getvalue(), runner_id=job.runner_id)
        async with engine.connect() as connection:
            self.assertIsNone(await connection.scalar(select(db.report_update_history.c.source_key)
                .where(db.report_update_history.c.job_id == str(job.id))))

if __name__ == '__main__':
    unittest.main(verbosity=2)
