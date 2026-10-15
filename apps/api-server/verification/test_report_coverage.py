"""Run only in an explicitly named disposable vahan_coverage_*_test database.

`/annual-reports/coverage` reports progress of the latest queue run for one report scope and year.
Saved month cells are never used as progress; they are verified separately by the annual-report tests.
"""
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import make_url

database = os.environ.get('VAHAN_COVERAGE_TEST_DATABASE', '')
if not database.startswith('vahan_coverage_') or not database.endswith('_test') or not database.replace('_', '').isalnum():
    raise RuntimeError('A disposable vahan_coverage_*_test database is required.')
os.environ['DATABASE_URL'] = make_url(os.environ['DATABASE_URL']).set(database=database).render_as_string(hide_password=False)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
subprocess.run([sys.executable, '-m', 'app.migrate'], check=True)

from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import delete, update
from app.api.batch_queue import QueueTaskInput
from app.api.report_coverage import CoverageQuery, report_coverage
from app.db import engine, schema as db
from app.models.job import Job, JobStatus
from app.repositories.annual_reports import import_rows
from app.repositories.batch_queue import BatchQueueRepository
from app.services import services

YEAR = datetime.now().year
PROGRESS_KEYS = ('total', 'processed', 'withData', 'noData', 'failed', 'pending', 'running')


def filters(index, year=YEAR, fuel='PURE EV'):
    return {'states': ['ASSAM'], 'rtos': [f'OFFICE {index} - AS{index:02d}'],
            'period': 'CALENDAR YEAR', 'fromYear': str(year), 'toYear': str(year),
            'fuels': [fuel], 'yAxis': 'Maker', 'xAxis': 'Month Wise', 'autoApply': True, 'autoExport': True}


def task(index, year=YEAR, fuel='PURE EV'):
    return QueueTaskInput(name=f'Office {index}', filters=filters(index, year, fuel))


def plan(tasks):
    return [{'name': item.name, 'filters': item.filters.model_dump(mode='json', by_alias=True)} for item in tasks]


class CoverageTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        async with engine.begin() as connection:
            for table in (db.main_reports, db.report_update_history, db.batch_queue_tasks, db.batch_queue_sessions,
                          db.jobs, db.report_sessions, db.app_settings):
                await connection.execute(delete(table))
        self.owner = 'coverage-' + str(uuid4())
        await services.users.bootstrap(self.owner, 'fixture-password-only')
        self.request = Request({'type': 'http', 'headers': []})
        self.request.state.authenticated_user = self.owner
        self.request.state.authenticated_role = 'user'
        self.queue = BatchQueueRepository()
        self.tasks = [task(index) for index in range(5)]

    async def asyncTearDown(self):
        await engine.dispose()

    async def start(self, tasks=None, workers=2):
        session = uuid4()
        await self.queue.start(session, self.owner, tasks or self.tasks, workers)
        return session

    async def mark(self, session, **positions):
        """positions: status name -> list of queue positions."""
        async with engine.begin() as connection:
            for status, items in positions.items():
                for position in items:
                    await connection.execute(update(db.batch_queue_tasks).where(
                        db.batch_queue_tasks.c.session_id == str(session),
                        db.batch_queue_tasks.c.position == position).values(status=status))

    async def read(self, tasks=None, year=YEAR, **changes):
        tasks = self.tasks if tasks is None else tasks
        return await report_coverage(CoverageQuery(year=year, scenarios=plan(tasks), **changes), self.request)

    async def save_workbook(self, index, value=0):
        job = await services.jobs.create(Job(runnerId='coverage-fixture', ownerUsername=self.owner,
            status=JobStatus.COMPLETED, filters=filters(index), scenarioName=f'Office {index}'))
        async with engine.begin() as connection:
            await import_rows(connection, source_key='fixture:' + str(uuid4()), name='Fixture',
                rows=[{'sheet': 'Report', 'row_number': 1, 'cells': ['Maker', f'{YEAR}-Jan']},
                      {'sheet': 'Report', 'row_number': 2, 'cells': ['Fixture maker', value]}],
                filters=job.filters.model_dump(mode='json', by_alias=True), owner=job.owner_username,
                observed_at=datetime.now(timezone.utc), job_id=str(job.id))

    async def test_no_run_reports_empty_progress_and_the_loaded_matrix(self):
        result = await self.read()
        self.assertEqual((result['hasRun'], result['status'], result['matrixLoaded']), (False, 'NO_RUN', True))
        self.assertEqual([result[key] for key in PROGRESS_KEYS], [0] * 7)
        self.assertIsNone(result['startedAt'])
        self.assertIsNone(result['lastActivityAt'])
        self.assertFalse((await self.read(tasks=[]))['matrixLoaded'])

    async def test_progress_counts_queue_cases_by_status(self):
        session = await self.start()
        await self.mark(session, COMPLETED=[0], NO_DATA=[1], FAILED=[2], PROCESSING=[3])
        result = await self.read()
        self.assertTrue(result['hasRun'])
        self.assertEqual({key: result[key] for key in PROGRESS_KEYS},
            {'total': 5, 'processed': 3, 'withData': 1, 'noData': 1, 'failed': 1, 'pending': 1, 'running': 1})
        self.assertEqual(result['status'], 'RUNNING', 'a run with unfinished cases is not complete')
        self.assertTrue(result['startedAt'] and result['lastActivityAt'])

    async def test_saved_month_cells_do_not_change_progress(self):
        await self.save_workbook(0, value=12)
        self.assertEqual((await self.read())['status'], 'NO_RUN', 'saved data alone is not a run')
        session = await self.start()
        await self.save_workbook(4, value=7)
        result = await self.read()
        self.assertEqual({key: result[key] for key in PROGRESS_KEYS},
            {'total': 5, 'processed': 0, 'withData': 0, 'noData': 0, 'failed': 0, 'pending': 5, 'running': 0})
        await self.mark(session, COMPLETED=[0, 1, 2, 3, 4])
        self.assertEqual((await self.read())['withData'], 5)

    async def test_finished_runs_report_completion_with_or_without_failures(self):
        clean = await self.start()
        await self.mark(clean, COMPLETED=[0, 1, 2], NO_DATA=[3, 4])
        result = await self.read()
        self.assertEqual((result['status'], result['processed'], result['total']), ('COMPLETED', 5, 5))
        await self.mark(clean, FAILED=[4])
        waiting = await self.read()
        self.assertEqual((waiting['status'], waiting['failed']), ('RUNNING', 1),
                         'a failed case is still retried until the retry phase is done')
        async with engine.begin() as connection:
            key = {'session_id': str(clean)}
            policy = await self.queue._policy(connection, key)
            await self.queue._save_policy(connection, key, {**policy, 'phase': 'DONE'})
        finished = await self.read()
        self.assertEqual((finished['status'], finished['failed'], finished['processed']),
                         ('COMPLETED_WITH_ERRORS', 1, 5))

    async def test_year_and_report_scope_are_isolated(self):
        previous = [task(index, year=YEAR - 1) for index in range(3)]
        mixed = [task(0), task(1), task(2, fuel='PETROL')]
        await self.start(previous)
        self.assertEqual((await self.read())['status'], 'NO_RUN', 'another year is not this year\'s run')
        self.assertEqual((await self.read(tasks=previous, year=YEAR - 1))['total'], 3)
        session = await self.start(mixed)
        await self.mark(session, COMPLETED=[0, 1, 2])
        electric = await self.read(tasks=mixed[:2])
        petrol = await self.read(tasks=mixed[2:])
        self.assertEqual((electric['total'], electric['withData']), (2, 2))
        self.assertEqual((petrol['total'], petrol['withData']), (1, 1))
        self.assertNotEqual(electric['datasetId'], petrol['datasetId'])

    async def test_running_session_wins_over_an_older_paused_one(self):
        older = await self.start(self.tasks[:3])
        await self.queue.set_status(older, self.owner, 'PAUSED')
        newer = await self.start(self.tasks)
        self.assertNotEqual(older, newer)
        self.assertEqual((await self.read())['total'], 5)
        await self.queue.set_status(newer, self.owner, 'PAUSED')
        await self.mark(older, COMPLETED=[0])
        result = await self.read()
        self.assertEqual(result['total'], 5, 'the most recently updated paused run is used when none is running')

    async def test_invalid_requests_are_rejected(self):
        with self.assertRaises(HTTPException) as unknown:
            await self.read(dataset='not-owned')
        self.assertEqual(unknown.exception.status_code, 404)
        two_offices = filters(0)
        two_offices['rtos'] = ['OFFICE 0 - AS00', 'OFFICE 1 - AS01']
        with self.assertRaises(HTTPException) as invalid:
            await report_coverage(CoverageQuery(year=YEAR, scenarios=[{'name': 'Two', 'filters': two_offices}]),
                                  self.request)
        self.assertEqual(invalid.exception.status_code, 400)
        with self.assertRaises(HTTPException) as wrong_year:
            await report_coverage(CoverageQuery(year=YEAR - 1, scenarios=plan(self.tasks)), self.request)
        self.assertEqual(wrong_year.exception.status_code, 400)


if __name__ == '__main__':
    unittest.main()
