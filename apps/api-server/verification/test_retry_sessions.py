"""Run with VAHAN_RETRY_TEST_DATABASE=vahan_retry_<name>_test in the API image.

Only a dedicated disposable database is migrated or cleared, never the live DB.
"""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import unittest
from io import BytesIO
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy.engine import make_url

database = os.environ.get('VAHAN_RETRY_TEST_DATABASE', '')
if not database.startswith('vahan_retry_') or not database.endswith('_test') or not database.replace('_', '').isalnum():
    raise RuntimeError('Set VAHAN_RETRY_TEST_DATABASE to a disposable vahan_retry_*_test database.')
os.environ['DATABASE_URL'] = make_url(os.environ['DATABASE_URL']).set(database=database).render_as_string(hide_password=False)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
subprocess.run([sys.executable, '-m', 'app.migrate'], check=True)

from fastapi import HTTPException
from openpyxl import Workbook
from sqlalchemy import delete, func, select, update
from starlette.requests import Request
from app.api.jobs import create_job
from app.api.excel import (list_exported_report_sessions, read_exported_report_session, download_job_file,
    delete_report_session, restore_report_session)
from app.db import engine, schema as db
from app.models.job import Job, JobStatus, CreateJobRequest
from app.models.report_result import ReportResultRequest
from app.repositories.report_results import commit_report_result
from app.services import services


class RetrySessionsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Connections cannot be shared across IsolatedAsyncioTestCase loops.
        await engine.dispose()
        self.user = 'retry-fixture'
        await services.users.bootstrap(self.user, 'fixture-password-only')
        self.session_id = uuid4()
        self.runner_id = 'retry-' + str(uuid4())
        await services.runners.register(runner_id=self.runner_id, name='Fixture', socket_id=str(uuid4()))
        self.request = Request({'type': 'http', 'headers': []})
        self.request.state.authenticated_user = self.user
        self.request.state.authenticated_role = 'user'
        self.emit = patch('app.api.jobs.sio.emit', new=AsyncMock())
        self.emit.start()
        # These tests insert the original job directly; gate lifecycle is
        # exercised separately by the UI contract verification suite.
        self.gate = patch('app.repositories.ui_contract.require_gate', new=AsyncMock(return_value={'fixture': True}))
        self.bind = patch('app.repositories.ui_contract.bind_gate', new=AsyncMock())
        self.gate.start(); self.bind.start()

    async def asyncTearDown(self):
        self.emit.stop()
        self.gate.stop(); self.bind.stop()
        await engine.dispose()

    async def original(self, status=JobStatus.FAILED, office='PUNE-MH12', legacy=False):
        job = await services.jobs.create(Job(runnerId=self.runner_id, ownerUsername=self.user,
            sessionId=self.session_id, status=status, scenarioName='Report ' + office,
            filters={'states': ['MAHARASHTRA'], 'rtos': [office], 'fuels': ['PURE EV'],
                'reportYear': '2026', 'reportMonth': 'OCTOBER'}, error='Fixture failure' if status == JobStatus.FAILED else None))
        if legacy:
            async with engine.begin() as connection:
                payload = await connection.scalar(select(db.jobs.c.payload).where(db.jobs.c.id == str(job.id)))
                payload.pop('case_id', None)
                payload.pop('retry_of_job_id', None)
                await connection.execute(update(db.jobs).where(db.jobs.c.id == str(job.id)).values(payload=payload, case_id=None, retry_of_job_id=None))
            job = await services.jobs.get(job.id)
        return job

    async def retry(self, previous, **changes):
        data = dict(runnerId=self.runner_id, filters=previous.filters, retryOfJobId=previous.id,
            scenarioName=previous.scenario_name, sessionId=self.session_id)
        return await create_job(CreateJobRequest.model_validate({**data, **changes}), self.request)

    async def summary(self):
        return await read_exported_report_session(self.session_id, self.request)

    async def finish(self, job, data=True, workbook=True):
        for status in [JobStatus.OPENING_VAHAN, JobStatus.FILLING_FILTERS, JobStatus.SUBMITTING, JobStatus.WAITING_RESULT]:
            self.assertIsNotNone(await services.jobs.update_status(job.id, status))
        if data and workbook:
            await self.commit_workbook(job)
        command = ReportResultRequest.model_validate(dict(result='DATA' if data else 'NO_RECORD',
            message='Data found' if data else 'No record found', observedAt='2026-10-02T17:00:00+07:00',
            pageUrl='http://fixture.test/report', tables=[{'rows': [{'section': 'body', 'cells': ['Fixture maker', '1']}]}] if data else []))
        return await commit_report_result(job.id, self.runner_id, command)

    async def commit_workbook(self, job):
        document = Workbook()
        document.active.append(['Maker', 'JAN', 'Total'])
        document.active.append(['Fixture maker', 1, 1])
        buffer = BytesIO()
        document.save(buffer)
        return await services.files.commit_excel(job.id, 'fixture.xlsx', buffer.getvalue(),
            observed_at=datetime(2026, 10, 2, 10, tzinfo=timezone.utc), runner_id=self.runner_id)

    async def test_retry_replaces_failure_counts_and_download_without_new_case(self):
        failed = await self.original(legacy=True)
        await self.original(JobStatus.COMPLETED, 'OTHER-MH13')
        before = await self.summary()
        self.assertEqual((before['jobCount'], before['failedCount'], before['completedCount']), (2, 1, 1))
        retry = await self.retry(failed)
        self.assertEqual(retry.case_id, failed.id)
        active = await self.summary()
        self.assertEqual((active['jobCount'], active['failedCount'], active['activeCount']), (2, 0, 1))
        await self.finish(retry)
        after = await self.summary()
        self.assertEqual((after['jobCount'], after['failedCount'], after['completedCount'], after['fileCount']), (2, 0, 2, 0))
        self.assertEqual(after['startedAt'], before['startedAt'])
        self.assertGreater(after['updatedAt'], before['updatedAt'])
        self.assertEqual(after['jobs'][0]['jobId'], str(retry.id))
        self.assertEqual(after['jobs'][0]['createdAt'], failed.created_at.isoformat())
        self.assertIsNone(after['jobs'][0]['error'])
        self.assertIsNone(after['jobs'][0]['downloadUrl'])
        self.assertIsNone(await services.files.for_job(retry.id, 'excel'))
        with self.assertRaises(HTTPException) as raised:
            await download_job_file(retry.id, 'excel', self.request)
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual((await services.jobs.get(failed.id)).status, JobStatus.FAILED, 'retain the original attempt for audit')

    async def test_no_data_retry_updates_no_data_and_txt(self):
        retry = await self.retry(await self.original())
        await self.finish(retry, data=False)
        summary = await self.summary()
        self.assertEqual((summary['jobCount'], summary['failedCount'], summary['noDataCount'], summary['fileCount']), (1, 0, 1, 0))
        self.assertIsNone(summary['jobs'][0]['fileType'])
        with self.assertRaises(HTTPException) as raised:
            await download_job_file(retry.id, 'no-data', self.request)
        self.assertEqual(raised.exception.status_code, 404)

    async def test_failed_retry_chain_keeps_one_failure_until_recovered(self):
        failed = await self.original()
        retry = await self.retry(failed)
        retry = await services.jobs.update_status(retry.id, JobStatus.FAILED, error='Retry failure')
        summary = await self.summary()
        self.assertEqual((summary['jobCount'], summary['failedCount']), (1, 1))
        second_retry = await self.retry(retry)
        with self.assertRaisesRegex(ValueError, 'Full workbook must be saved'):
            await self.finish(second_retry, workbook=False)
        self.assertEqual((await services.jobs.get(second_retry.id)).status, JobStatus.WAITING_RESULT)
        await self.commit_workbook(second_retry)
        summary = await self.summary()
        self.assertEqual((summary['jobCount'], summary['failedCount'], summary['completedCount']), (1, 0, 1))
        self.assertEqual(second_retry.case_id, failed.id)
        async with engine.connect() as connection:
            attempts = await connection.scalar(select(func.count()).select_from(db.jobs).where(db.jobs.c.session_id == str(self.session_id)))
        self.assertEqual(attempts, 3)

    async def test_distinct_new_cases_with_identical_filters_are_not_merged(self):
        first = await self.original()
        await self.original()
        retry = await self.retry(first)
        await self.finish(retry, data=False)
        summary = await self.summary()
        self.assertEqual((summary['jobCount'], summary['failedCount'], summary['noDataCount']), (2, 1, 1))

    async def test_legacy_retries_are_collapsed_and_can_be_retried_again(self):
        first = await self.original(legacy=True)
        latest = await self.original(legacy=True)
        summary = await self.summary()
        self.assertEqual((summary['jobCount'], summary['failedCount']), (1, 1))
        retry = await self.retry(latest)
        await self.finish(retry)
        summary = await self.summary()
        self.assertEqual((summary['jobCount'], summary['failedCount'], summary['completedCount']), (1, 0, 1))
        self.assertEqual(summary['jobs'][0]['createdAt'], first.created_at.isoformat())

    async def test_reject_changed_filters_session_owner_and_completed_retry(self):
        failed = await self.original()
        for changes in [{'sessionId': uuid4()}, {'filters': {**failed.filters.model_dump(by_alias=True), 'rtos': ['WRONG-MH99']}}]:
            with self.assertRaises(HTTPException) as raised:
                await self.retry(failed, **changes)
            self.assertEqual(raised.exception.status_code, 409)
        self.request.state.authenticated_user = 'someone-else'
        with self.assertRaises(HTTPException) as raised:
            await self.retry(failed)
        self.assertEqual(raised.exception.status_code, 404)
        self.request.state.authenticated_user = self.user
        completed = await self.original(JobStatus.COMPLETED, 'DONE-MH14')
        with self.assertRaises(HTTPException) as raised:
            await self.retry(completed)
        self.assertEqual(raised.exception.status_code, 409)

    async def test_concurrent_retries_create_only_one_child(self):
        failed = await self.original()
        other_runner = self.runner_id + '-other'
        await services.runners.register(runner_id=other_runner, name='Fixture 2', socket_id=str(uuid4()))
        results = await asyncio.gather(self.retry(failed), self.retry(failed, runnerId=other_runner), return_exceptions=True)
        self.assertEqual(sum(isinstance(result, Job) for result in results), 1)
        errors = [result for result in results if isinstance(result, HTTPException)]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].status_code, 409)
        self.assertEqual((await self.summary())['jobCount'], 1)

    async def test_stopped_retry_continues_same_case(self):
        failed = await self.original()
        stopped = await self.retry(failed)
        stopped = await services.jobs.update_status(stopped.id, JobStatus.CANCELLED)
        continued = await self.retry(stopped)
        await self.finish(continued)
        summary = await self.summary()
        self.assertEqual((summary['jobCount'], summary['completedCount'], summary['cancelledCount']), (1, 1, 0))

    async def test_delete_and_restore_keep_cases_files_and_monthly_data(self):
        retry = await self.retry(await self.original())
        await self.finish(retry)
        before = await self.summary()
        original_file = await services.files.for_job(retry.id, 'excel')
        self.assertIsNone(original_file)
        async with engine.connect() as connection:
            reports_before = await connection.scalar(select(func.count()).select_from(db.main_reports))
            history_before = await connection.scalar(select(func.count()).select_from(db.report_update_history))
        await delete_report_session(self.session_id, self.request)
        await delete_report_session(self.session_id, self.request)  # Safe duplicate request.
        visible = await list_exported_report_sessions(self.request)
        self.assertNotIn(str(self.session_id), [session['sessionId'] for session in visible])
        deleted = await list_exported_report_sessions(self.request, deleted=True)
        archived = next(session for session in deleted if session['sessionId'] == str(self.session_id))
        self.assertIsNotNone(archived['deletedAt'])
        self.assertEqual(archived['jobCount'], before['jobCount'])
        self.assertIsNone(await services.files.for_job(retry.id, 'excel'))
        with self.assertRaises(HTTPException) as raised:
            await download_job_file(retry.id, 'excel', self.request)
        self.assertEqual(raised.exception.status_code, 404)
        async with engine.connect() as connection:
            self.assertEqual(await connection.scalar(select(func.count()).select_from(db.main_reports)), reports_before)
            self.assertEqual(await connection.scalar(select(func.count()).select_from(db.report_update_history)), history_before)
        await restore_report_session(self.session_id, self.request)
        after = await self.summary()
        self.assertEqual(after, before)
        self.assertNotIn(str(self.session_id), [session['sessionId'] for session in await list_exported_report_sessions(self.request, deleted=True)])

    async def test_delete_is_blocked_for_active_job_and_between_batch_cases(self):
        failed = await self.original()
        retry = await self.retry(failed)
        with self.assertRaises(HTTPException) as raised:
            await delete_report_session(self.session_id, self.request)
        self.assertEqual(raised.exception.status_code, 409)
        await services.jobs.update_status(retry.id, JobStatus.FAILED)
        await services.users.put_state(self.user, 'vahanStateRtoBatchRecoveryV1',
            {'sessionId': str(self.session_id), 'status': 'running'})
        with self.assertRaises(HTTPException) as raised:
            await delete_report_session(self.session_id, self.request)
        self.assertEqual(raised.exception.status_code, 409)
        await services.users.put_state(self.user, 'vahanStateRtoBatchRecoveryV1',
            {'sessionId': str(self.session_id), 'status': 'stopped'})
        await delete_report_session(self.session_id, self.request)

    async def test_delete_restore_and_trash_enforce_ownership(self):
        await self.original()
        self.request.state.authenticated_user = 'someone-else'
        for action in [delete_report_session, restore_report_session]:
            with self.assertRaises(HTTPException) as raised:
                await action(self.session_id, self.request)
            self.assertEqual(raised.exception.status_code, 404)
        self.request.state.authenticated_user = self.user
        await delete_report_session(self.session_id, self.request)
        self.request.state.authenticated_user = 'someone-else'
        self.assertEqual(await list_exported_report_sessions(self.request, deleted=True), [])
        self.request.state.authenticated_role = 'admin'
        self.assertIn(str(self.session_id), [session['sessionId'] for session in await list_exported_report_sessions(self.request, deleted=True)])
        await restore_report_session(self.session_id, self.request)

    async def test_deleted_session_cannot_accept_retry_until_restored(self):
        failed = await self.original()
        await delete_report_session(self.session_id, self.request)
        with self.assertRaises(HTTPException) as raised:
            await self.retry(failed)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn('Restore', raised.exception.detail)
        self.assertIsNone((await services.runners.get(self.runner_id)).current_job_id)
        await restore_report_session(self.session_id, self.request)
        retry = await self.retry(failed)
        self.assertEqual(retry.case_id, failed.id)


if __name__ == '__main__':
    unittest.main(verbosity=2)
