"""Progress contract for annual report updates on a guarded disposable database."""
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
from sqlalchemy import delete, insert, update
from starlette.requests import Request

from app.api.batch_queue import QueueTaskInput
from app.api.report_coverage import CoverageQuery, report_coverage
from app.db import engine, schema as db
from app.repositories.annual_reports import dataset
from app.repositories.batch_queue import BatchQueueRepository, RETRY_KEY
from app.repositories.postgres import now
from app.services import services

YEAR = datetime.now().year


def filters(index, year=YEAR, fuel='PURE EV'):
    return {
        'states': ['ASSAM'],
        'rtos': [f'OFFICE {index} - AS{index:02d}'],
        'period': 'CALENDAR YEAR',
        'fromYear': str(year),
        'toYear': str(year),
        'fuels': [fuel],
        'yAxis': 'Maker',
        'xAxis': 'Month Wise',
    }


class ReportCoverageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        async with engine.begin() as connection:
            await connection.execute(delete(db.batch_queue_sessions))
            await connection.execute(delete(db.report_update_history))
            await connection.execute(delete(db.main_reports))
        self.owner = 'coverage-' + str(uuid4())
        self.other_owner = 'other-' + str(uuid4())
        for owner in (self.owner, self.other_owner):
            await services.users.bootstrap(owner, 'fixture-password-only')
        self.request = Request({'type': 'http', 'headers': []})
        self.request.state.authenticated_user = self.owner
        self.request.state.authenticated_role = 'user'
        self.plan = [{'name': f'Office {index}', 'filters': filters(index)} for index in range(5)]

    async def asyncTearDown(self):
        await engine.dispose()

    async def read(self, **changes):
        query = {'year': YEAR, 'scenarios': self.plan}
        query.update(changes)
        return await report_coverage(CoverageQuery(**query), self.request)

    async def start(self, owner, scenarios):
        session_id = uuid4()
        tasks = [QueueTaskInput(name=item['name'], filters=item['filters']) for item in scenarios]
        await BatchQueueRepository().start(session_id, owner, tasks, max_workers=3)
        return session_id

    async def set_statuses(self, session_id, statuses):
        async with engine.begin() as connection:
            for position, status in statuses.items():
                await connection.execute(update(db.batch_queue_tasks).where(
                    db.batch_queue_tasks.c.session_id == str(session_id),
                    db.batch_queue_tasks.c.position == position,
                ).values(status=status, updated_at=now()))

    async def save_scope(self, report_filters):
        scope = dataset(self.owner, report_filters)
        observed = datetime.now(timezone.utc)
        async with engine.begin() as connection:
            await connection.execute(insert(db.report_update_history).values(
                source_key='coverage-fixture:' + str(uuid4()),
                owner_key=self.owner,
                scope_key=scope['id'],
                scope_label=scope['label'],
                filters=scope['filters'],
                job_id=None,
                name='Coverage fixture',
                status='saved',
                years=[YEAR],
                states=['ASSAM'],
                rtos=['OFFICE 0 - AS00'],
                details={},
                observed_at=observed,
                imported_at=observed,
            ))
        return scope['id']

    async def test_no_run_returns_empty_progress_and_empty_plan_is_marked(self):
        result = await self.read(scenarios=[])

        self.assertEqual(result, {
            'year': YEAR,
            'datasetId': '',
            'hasRun': False,
            'matrixLoaded': False,
            'total': 0,
            'processed': 0,
            'withData': 0,
            'noData': 0,
            'failed': 0,
            'pending': 0,
            'running': 0,
            'status': 'NO_RUN',
            'startedAt': None,
            'lastActivityAt': None,
        })

    async def test_latest_matching_run_counts_queue_statuses_and_ignores_other_scope_and_year(self):
        scope_id = await self.save_scope(self.plan[0]['filters'])
        target_session = await self.start(self.owner, self.plan)
        await self.set_statuses(target_session, {
            0: 'COMPLETED', 1: 'NO_DATA', 2: 'FAILED', 3: 'PENDING', 4: 'PROCESSING',
        })
        # A newer run in another report scope must be skipped while looking for this scope.
        await self.start(self.other_owner, [
            {'name': 'Other fuel', 'filters': filters(8, fuel='PETROL')},
        ])
        # A matching run for a different year must not affect the requested year.
        await self.start(self.other_owner, [
            {'name': 'Previous year', 'filters': filters(9, year=YEAR - 1)},
        ])

        result = await self.read(dataset=scope_id)

        self.assertTrue(result['hasRun'])
        self.assertTrue(result['matrixLoaded'])
        self.assertEqual(result['datasetId'], scope_id)
        self.assertEqual((result['total'], result['processed']), (5, 3))
        self.assertEqual((result['withData'], result['noData'], result['failed']), (1, 1, 1))
        self.assertEqual((result['pending'], result['running'], result['status']), (1, 1, 'RUNNING'))
        self.assertIsNotNone(result['startedAt'])
        self.assertIsNotNone(result['lastActivityAt'])

    async def test_complete_run_with_failures_is_reported_as_completed_with_errors(self):
        scope_id = await self.save_scope(self.plan[0]['filters'])
        session_id = await self.start(self.owner, self.plan[:2])
        await self.set_statuses(session_id, {0: 'COMPLETED', 1: 'FAILED'})
        async with engine.begin() as connection:
            await connection.execute(update(db.app_settings).where(
                db.app_settings.c.key == RETRY_KEY + str(session_id),
            ).values(value={'phase': 'DONE'}))

        result = await self.read(dataset=scope_id)

        self.assertEqual((result['total'], result['processed']), (2, 2))
        self.assertEqual((result['withData'], result['failed']), (1, 1))
        self.assertEqual(result['status'], 'COMPLETED_WITH_ERRORS')

    async def test_unknown_dataset_and_invalid_scenarios_are_rejected(self):
        with self.assertRaises(HTTPException) as unknown:
            await self.read(dataset='not-a-saved-report')
        self.assertEqual(unknown.exception.status_code, 404)

        invalid_scenarios = [
            [{'name': 'Multiple states', 'filters': {
                **filters(0), 'states': ['ASSAM', 'BIHAR'],
            }}],
            [{'name': 'Different year', 'filters': filters(0, year=YEAR - 1)}],
        ]
        for scenarios in invalid_scenarios:
            with self.assertRaises(HTTPException) as invalid:
                await self.read(scenarios=scenarios)
            self.assertEqual(invalid.exception.status_code, 400)


if __name__ == '__main__':
    unittest.main()
