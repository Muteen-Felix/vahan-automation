"""Run only in an explicitly named disposable vahan_coverage_*_test database."""
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
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
from app.api.report_coverage import CoverageQuery, report_coverage
from app.db import engine, schema as db
from sqlalchemy import delete, update
from app.models.job import Job, JobStatus
from app.repositories.annual_reports import dataset, import_rows
from app.services import services

YEAR = datetime.now().year


def filters(index, year=YEAR, fuel='PURE EV'):
    return {'states': ['ASSAM'], 'rtos': [f'OFFICE {index} - AS{index:02d}'],
            'period': 'CALENDAR YEAR', 'fromYear': str(year), 'toYear': str(year),
            'fuels': [fuel], 'yAxis': 'Maker', 'xAxis': 'Month Wise', 'autoApply': True, 'autoExport': True}


class CoverageTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        async with engine.begin() as connection:
            await connection.execute(delete(db.main_reports))
            await connection.execute(delete(db.report_update_history))
        self.owner = 'coverage-' + str(uuid4())
        self.other = 'other-' + str(uuid4())
        for owner in (self.owner, self.other):
            await services.users.bootstrap(owner, 'fixture-password-only')
        self.request = Request({'type': 'http', 'headers': []})
        self.request.state.authenticated_user = self.owner
        self.request.state.authenticated_role = 'user'
        self.plan = [{'name': f'Office {i}', 'filters': filters(i)} for i in range(5)]

    async def asyncTearDown(self):
        await engine.dispose()

    async def job(self, index, status=JobStatus.COMPLETED, owner=None, changed=None):
        return await services.jobs.create(Job(runnerId='coverage-fixture', ownerUsername=owner or self.owner,
            status=status, filters=changed or filters(index), scenarioName=f'Office {index}'))

    async def save(self, job, no_data=False, warning=None, value=0):
        async with engine.begin() as connection:
            return await import_rows(connection, source_key='fixture:' + str(uuid4()), name='Fixture',
                rows=[{'sheet': 'Report', 'row_number': 1, 'cells': ['Maker', f'{YEAR}-Jan']},
                      {'sheet': 'Report', 'row_number': 2, 'cells': ['Fixture maker', value]}],
                filters=job.filters.model_dump(mode='json', by_alias=True), owner=job.owner_username,
                observed_at=datetime.now(timezone.utc), job_id=str(job.id), no_data=no_data, warning=warning)

    async def read(self, **changes):
        return await report_coverage(CoverageQuery(year=YEAR, scenarios=self.plan, **changes), self.request)

    async def test_data_and_confirmed_empty_cover_only_saved_reports(self):
        await self.save(await self.job(0), value=0)
        await self.save(await self.job(1, JobStatus.NO_DATA), no_data=True)
        await self.job(2, JobStatus.FAILED)
        await self.job(3, JobStatus.CANCELLED)
        result = await self.read()
        self.assertEqual((result['covered'], result['withData'], result['noData'], result['total']), (2, 1, 1, 5))
        self.assertEqual(result['missingIndices'], [2, 3, 4])
        self.assertEqual(result['firstMissing']['index'], 2)
        self.assertEqual(result['coveredThrough'], 2)

    async def test_repeated_imports_later_failure_and_filter_order_do_not_reset_coverage(self):
        original = await self.job(0, changed=dict(reversed(list(filters(0).items()))))
        await self.save(original)
        await self.save(original)
        await self.job(0, JobStatus.FAILED)
        await self.save(await self.job(0, JobStatus.NO_DATA), no_data=True)
        result = await self.read()
        self.assertEqual((result['covered'], result['withData'], result['noData']), (1, 1, 0))
        self.assertEqual(result['missingIndices'], [1, 2, 3, 4])

    async def test_shared_coverage_keeps_filter_year_and_partial_report_isolation(self):
        await self.save(await self.job(0, owner=self.other))
        await self.save(await self.job(1, changed=filters(1, fuel='PETROL')))
        await self.save(await self.job(2, changed=filters(2, year=YEAR - 1)))
        await self.save(await self.job(3, changed={**filters(3), 'makers': ['Fixture maker']}))
        self.assertEqual((await self.read())['covered'], 1)
        foreign = dataset(self.other, filters(0))['id']
        shared = await self.read(dataset=foreign)
        self.assertEqual(shared['covered'], 1)
        self.assertTrue(shared['canContinue'])

    async def test_search_preserves_matrix_indices_and_fills_earlier_gaps(self):
        await self.save(await self.job(3))
        result = await self.read()
        self.assertEqual(result['missingIndices'], [0, 1, 2, 4])
        self.assertEqual(result['lastSaved']['index'], 3)
        self.assertEqual(result['coveredThrough'], 0)
        scoped = await self.read(state='ass', rto='AS04')
        self.assertEqual(scoped['missingIndices'], [4])
        self.assertEqual(scoped['total'], 1)

    async def test_review_or_dom_without_workbook_does_not_cover_data(self):
        await self.save(await self.job(0), warning='Complete workbook required')
        await self.save(await self.job(1), value='invalid')
        await self.job(2, JobStatus.COMPLETED)
        self.assertEqual((await self.read())['covered'], 0)

    async def test_active_job_blocks_continuation_for_own_account(self):
        await self.job(0, JobStatus.WAITING_RESULT, owner=self.other)
        self.assertTrue((await self.read())['canContinue'])
        await self.job(1, JobStatus.WAITING_CAPTCHA)
        result = await self.read()
        self.assertFalse(result['canContinue'])
        self.assertIn('already running', result['blockedReason'])

    async def test_newer_full_crawl_counts_as_covered_after_replacing_all_values(self):
        first = await self.job(0)
        await self.save(first, value=7)
        newer = await self.job(0)
        async with engine.begin() as connection:
            await connection.execute(update(db.report_update_history).where(
                db.report_update_history.c.job_id == str(first.id)).values(status='review'))
            await import_rows(connection, source_key='newer:' + str(uuid4()), name='Newer crawl',
                rows=[{'sheet': 'Report', 'row_number': 1, 'cells': ['Maker', f'{YEAR}-Jan']},
                      {'sheet': 'Report', 'row_number': 2, 'cells': ['Fixture maker', 11]}],
                filters=newer.filters.model_dump(mode='json', by_alias=True), owner=newer.owner_username,
                observed_at=datetime.now(timezone.utc) + timedelta(seconds=1),
                job_id=str(newer.id), update_newer=True)
        result = await self.read()
        self.assertEqual((result['covered'], result['withData']), (1, 1))

    async def test_unknown_scope_duplicate_offices_and_empty_plan(self):
        with self.assertRaises(HTTPException):
            await self.read(dataset='not-owned')
        self.plan.append(self.plan[0])
        with self.assertRaises(HTTPException) as invalid:
            await self.read()
        self.assertEqual(invalid.exception.status_code, 400)
        self.plan = []
        self.assertFalse((await self.read())['matrixLoaded'])


if __name__ == '__main__':
    unittest.main()
