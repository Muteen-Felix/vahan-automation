"""Run only against an explicitly named disposable PostgreSQL *_test database.

VAHAN_RESULT_TEST_DATABASE=vahan_results_test python verification/test_report_results.py
The compose API environment supplies credentials; this script never prints them.
"""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy.engine import make_url

test_database = os.environ.get('VAHAN_RESULT_TEST_DATABASE', '')
if not test_database.endswith('_test') or not test_database.startswith('vahan_results_'):
    raise RuntimeError('Set VAHAN_RESULT_TEST_DATABASE to a disposable vahan_results_*_test database.')
url = make_url(os.environ['DATABASE_URL']).set(database=test_database)
os.environ['DATABASE_URL'] = url.render_as_string(hide_password=False)
subprocess.run([sys.executable, '-m', 'app.migrate'], check=True)

from sqlalchemy import delete, func, select
from pydantic import ValidationError
from starlette.requests import Request
from fastapi import HTTPException
from app.db import engine, schema as db
from app.models.job import Job, JobStatus
from app.models.report_result import ReportResultRequest
from app.repositories.postgres import PostgresJobRepository, PostgresRunnerRegistry
from app.repositories.report_results import commit_report_result, get_report_result
from app.api.jobs import save_report_result, read_report_result


async def asgi_request(method, path, body=None, headers=None, binary=False):
    from app.main import fastapi_app
    messages, delivered = [], False
    data = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else b''
    request_headers = {'content-type': 'application/json', **(headers or {})}
    path, _, query = path.partition('?')
    scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.3'},
        'http_version': '1.1', 'method': method, 'scheme': 'http', 'path': path,
        'raw_path': path.encode(), 'query_string': query.encode(), 'root_path': '',
        'server': ('test', 80), 'client': ('127.0.0.1', 1234),
        'headers': [(k.encode(), v.encode()) for k, v in request_headers.items()]}

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {'type': 'http.request', 'body': data, 'more_body': False}
        await asyncio.Event().wait()

    async def send(message):
        messages.append(message)

    await asyncio.wait_for(fastapi_app(scope, receive, send), timeout=5)
    status = next(message['status'] for message in messages if message['type'] == 'http.response.start')
    response = b''.join(message.get('body', b'') for message in messages if message['type'] == 'http.response.body')
    return status, response if binary else json.loads(response)


class ReportResultsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as connection:
            await connection.execute(delete(db.main_reports))
            await connection.execute(delete(db.report_update_history))
        self.jobs, self.runners = PostgresJobRepository(), PostgresRunnerRegistry()
        self.runner_id = 'test-' + str(uuid4())
        initial = JobStatus.FILLING_FILTERS if self._testMethodName in {
            'test_filter_proofs_accept_sequential_fill_and_legacy_before_apply',
            'test_incomplete_or_different_case_proof_is_rejected_before_sql_write',
            'test_verification_rejects_wrong_phase_runner_and_cancelled_job',
        } else JobStatus.WAITING_RESULT
        self.job = Job(runnerId=self.runner_id, status=initial,
            filters={'states': ['MAHARASHTRA'], 'rtos': ['PUNE-MH12'],
                     'reportYear': '2026', 'reportMonth': 'OCTOBER'}, scenarioName='Result test')
        await self.jobs.create(self.job)
        self.socket_id = str(uuid4())
        await self.runners.register(runner_id=self.runner_id, name='Fixture', socket_id=self.socket_id)
        await self.runners.set_job(self.runner_id, str(self.job.id))
        self.command = ReportResultRequest.model_validate(dict(result='NO_RECORD',
            message='No record found', observedAt='2026-10-02T14:35:42+07:00',
            pageUrl='http://fixture.test/report', tables=[]))

    async def asyncTearDown(self):
        async with engine.begin() as c:
            await c.execute(delete(db.main_reports))
            await c.execute(delete(db.report_update_history))
            await c.execute(delete(db.runners).where(db.runners.c.id == self.runner_id))
            await c.execute(delete(db.stored_files).where(db.stored_files.c.job_id == str(self.job.id)))
            await c.execute(delete(db.jobs).where(db.jobs.c.id == str(self.job.id)))
            await c.execute(delete(db.report_sessions).where(db.report_sessions.c.id == str(self.job.session_id)))
        # unittest creates a separate event loop per test.
        await engine.dispose()

    async def test_no_record_stores_context_timestamp_and_releases_worker_without_file(self):
        job = await commit_report_result(self.job.id, self.runner_id, self.command)
        self.assertEqual(job.status, JobStatus.NO_DATA)
        self.assertEqual(job.result_message, 'No record found')
        result = await get_report_result(self.job.id)
        self.assertEqual(result['states'], ['MAHARASHTRA'])
        self.assertEqual(result['rtos'], ['PUNE-MH12'])
        self.assertEqual(result['observed_at'].isoformat(), '2026-10-02T14:35:42+07:00')
        self.assertIsNotNone(result['saved_at'].tzinfo)
        self.assertEqual(result['rows'], [])
        self.assertIsNone((await self.runners.get(self.runner_id)).current_job_id)
        async with engine.connect() as c:
            history = (await c.execute(select(db.report_update_history))).mappings().one()
            self.assertEqual(history['status'], 'no-data')
            self.assertEqual(history['observed_at'].isoformat(), '2026-10-02T07:35:42+00:00')
            self.assertEqual(await c.scalar(select(func.count()).select_from(db.main_reports)), 0)
            self.assertEqual(await c.scalar(select(func.count()).select_from(db.stored_files)), 0)

    async def test_populated_dom_cannot_complete_without_full_workbook(self):
        command = ReportResultRequest.model_validate({**self.command.model_dump(by_alias=True),
            'result':'DATA', 'message':'Data found', 'tables':[{'rows':[{'section':'body','cells':['Fixture maker','123']}]}]})
        with self.assertRaisesRegex(ValueError, 'Full workbook'):
            await commit_report_result(self.job.id, self.runner_id, command)
        self.assertEqual((await self.jobs.get(self.job.id)).status, JobStatus.WAITING_RESULT)
        self.assertIsNone(await get_report_result(self.job.id))

    async def test_concurrent_duplicate_save_is_idempotent(self):
        await asyncio.gather(*(commit_report_result(self.job.id, self.runner_id, self.command) for _ in range(2)))
        async with engine.connect() as c:
            self.assertEqual(await c.scalar(select(func.count()).select_from(db.report_update_history)), 1)
            self.assertEqual(await c.scalar(select(func.count()).select_from(db.stored_files)), 0)
        with self.assertRaises(ValueError):
            await commit_report_result(self.job.id, self.runner_id,
                self.command.model_copy(update={'page_url': 'http://different.test/'}))

    async def test_cancelled_job_cannot_save_result(self):
        await self.jobs.transition_status(self.job.id, JobStatus.CANCELLED)
        with self.assertRaises(ValueError):
            await commit_report_result(self.job.id, self.runner_id, self.command)
        self.assertIsNone(await get_report_result(self.job.id))

    async def test_unconfirmed_no_data_status_is_rejected(self):
        self.assertIsNone(await self.jobs.transition_status(self.job.id, JobStatus.NO_DATA))
        self.assertEqual((await self.jobs.get(self.job.id)).status, JobStatus.WAITING_RESULT)
        self.assertIsNone(await get_report_result(self.job.id))

    async def test_wrong_runner_cannot_save_result(self):
        with self.assertRaises(PermissionError):
            await commit_report_result(self.job.id, 'other-runner', self.command)
        self.assertIsNone(await get_report_result(self.job.id))

    async def test_transaction_rolls_back_result_file_and_status_together(self):
        with patch('app.repositories.report_results.save_job', new=AsyncMock(side_effect=RuntimeError('forced failure'))):
            with self.assertRaises(RuntimeError):
                await commit_report_result(self.job.id, self.runner_id, self.command)
        self.assertIsNone(await get_report_result(self.job.id))
        self.assertEqual((await self.jobs.get(self.job.id)).status, JobStatus.WAITING_RESULT)
        self.assertEqual((await self.runners.get(self.runner_id)).current_job_id, str(self.job.id))
        async with engine.connect() as c:
            self.assertEqual(await c.scalar(select(func.count()).select_from(db.stored_files)), 0)

    async def test_saved_main_report_cannot_be_changed_to_no_record(self):
        from app.repositories.file_store import PostgresFileStore
        await PostgresFileStore().commit_excel(self.job.id, 'report.xlsx', self.workbook_bytes())
        with self.assertRaises(ValueError):
            await commit_report_result(self.job.id, self.runner_id, self.command)
        self.assertEqual((await get_report_result(self.job.id))['result'], 'DATA')

    async def test_api_assigned_runner_can_save_and_owner_can_read(self):
        request = Request({'type': 'http', 'method': 'POST', 'path': '/', 'headers': [],
            'state': {'authenticated_runner': True}})
        with patch('app.api.jobs.sio.emit', new=AsyncMock()) as emit:
            result = await save_report_result(self.job.id, self.command, request, self.runner_id)
            self.assertEqual(result['status'], 'NO_DATA')
            self.assertEqual(emit.await_count,2)
            self.assertEqual(emit.await_args_list[0].kwargs,{'room':f'job:{self.job.id}','namespace':'/ui'})
            self.assertEqual(emit.await_args_list[1].args[0],'reports:updated')
            self.assertEqual(emit.await_args_list[1].kwargs,{'room':'reports:shared','namespace':'/ui'})
        owner_request = Request({'type': 'http', 'method': 'GET', 'path': '/', 'headers': [],
            'state': {'authenticated_role': 'admin', 'authenticated_user': 'admin'}})
        self.assertEqual((await read_report_result(self.job.id, owner_request, 0, 100))['message'], 'No record found')
        denied = Request({'type': 'http', 'method': 'POST', 'path': '/', 'headers': [], 'state': {}})
        with self.assertRaises(HTTPException) as error:
            await save_report_result(self.job.id, self.command, denied, self.runner_id)
        self.assertEqual(error.exception.status_code, 403)
        denied.state.authenticated_role, denied.state.authenticated_user = 'user', 'stranger'
        with self.assertRaises(HTTPException) as error:
            await read_report_result(self.job.id, denied, 0, 100)
        self.assertEqual(error.exception.status_code, 404)

    async def test_schema_matches_migration(self):
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        async with engine.connect() as c:
            diffs = await c.run_sync(lambda sync: compare_metadata(MigrationContext.configure(sync), db.metadata))
        self.assertEqual(diffs, [])

    async def test_http_auth_validation_serialization_and_save(self):
        from app.config import settings
        path = f'/api/jobs/{self.job.id}/report-result'
        body = self.command.model_dump(mode='json', by_alias=True)
        self.assertEqual((await asgi_request('POST', path, body))[0], 401)
        headers = {'x-vahan-runner-token': settings.runner_token, 'x-vahan-runner-id': 'wrong-runner'}
        self.assertEqual((await asgi_request('POST', path, body, headers))[0], 403)
        headers['x-vahan-runner-id'] = self.runner_id
        self.assertEqual((await asgi_request('POST', path, {**body, 'result': 'TIMEOUT'}, headers))[0], 422)
        code, response = await asgi_request('POST', path, body, headers)
        self.assertEqual(code, 200)
        self.assertEqual(response['status'], 'NO_DATA')
        with patch('app.main.authenticate_access_token', new=AsyncMock(return_value={
            'username': 'admin', 'role': 'admin', 'session_id': 'test-session'})):
            code, response = await asgi_request('GET', path, headers={'authorization': 'Bearer fixture-token'})
        self.assertEqual(code, 200)
        self.assertEqual(response['observed_at'], '2026-10-02T14:35:42+07:00')

    async def test_invalid_payloads_cannot_claim_no_data(self):
        payload = self.command.model_dump(by_alias=True)
        for changes in ({'result': 'TIMEOUT'}, {'message': 'NO_DATA'}, {'observedAt': '2026-10-02'},
                        {'result': 'DATA', 'message': 'Data found'},
                        {'tables': [{'rows': [{'section': 'body', 'cells': ['data']}]}]}):
            with self.assertRaises(ValidationError):
                ReportResultRequest.model_validate({**payload, **changes})

    async def test_apply_wrong_state_reports_conflict_not_missing_job(self):
        from app.realtime.runner_events import job_apply_clicked
        await self.jobs.update_status(self.job.id, JobStatus.WAITING_CAPTCHA)
        result = await job_apply_clicked(self.socket_id, {'jobId': str(self.job.id), 'clickId': 'fixture-click'})
        self.assertFalse(result['ok'])
        self.assertEqual(result['code'], 'JOB_APPLY_STATE_CONFLICT')
        self.assertNotIn('Job not found', result['error'])
        self.assertIsNotNone(await self.jobs.get(self.job.id))

    async def test_apply_lifecycle_saves_main_table_and_completes(self):
        from app.realtime.runner_events import job_status, job_apply_clicked
        from app.repositories.file_store import PostgresFileStore
        await self.jobs.update_status(self.job.id, JobStatus.WAITING_CAPTCHA)
        with patch('app.realtime.runner_events.sio.emit', new=AsyncMock()):
            self.assertTrue((await job_status(self.socket_id, {'jobId':str(self.job.id),'status':'SUBMITTING'}))['ok'])
            for _ in range(2):
                clicked = await job_apply_clicked(self.socket_id, {'jobId':str(self.job.id),'clickId':'fixture-click'})
                self.assertEqual(clicked['successfulApplyCount'], 1)
            self.assertTrue((await job_status(self.socket_id, {'jobId':str(self.job.id),'status':'WAITING_RESULT'}))['ok'])
        content = self.workbook_bytes()
        store = PostgresFileStore()
        response = await store.commit_excel(self.job.id, 'fixture.xlsx', content, observed_at=self.command.observed_at)
        self.assertEqual(response['status'], 'COMPLETED')
        self.assertEqual((await store.commit_excel(self.job.id, 'fixture.xlsx', content))['summary'], response['summary'])
        saved = await self.jobs.get(self.job.id)
        self.assertIsNone(saved.excel_file_name)
        self.assertEqual(saved.successful_apply_count, 1)
        self.assertIsNotNone(saved.main_report_saved_at.tzinfo)
        self.assertIsNone((await self.runners.get(self.runner_id)).current_job_id)
        async with engine.connect() as connection:
            self.assertEqual(await connection.scalar(select(func.count()).select_from(db.report_update_history)), 1)
            self.assertEqual(await connection.scalar(select(func.count()).select_from(db.stored_files)), 0)
            record = (await connection.execute(select(db.main_reports))).mappings().one()
            self.assertEqual([record[m] for m in db.MONTH_COLUMNS], [1,2]+[None]*10)
            self.assertEqual((record['state'],record['rto_code'],record['maker']), ('MAHARASHTRA','MH12','Fixture maker'))
        self.assertEqual((await get_report_result(self.job.id))['rows'], [])

    def workbook_bytes(self, maker='Fixture maker', count=1):
        from openpyxl import Workbook
        from io import BytesIO
        workbook, output = Workbook(), BytesIO()
        workbook.active.append(['Maker','JAN','FEB','Total'])
        workbook.active.append([maker,count,2,3])
        workbook.save(output); workbook.close()
        return output.getvalue()

    async def test_others_is_saved_to_sql_as_a_manufacturer_group(self):
        from app.repositories.file_store import PostgresFileStore
        response = await PostgresFileStore().commit_excel(
            self.job.id, 'fixture.xlsx', self.workbook_bytes(maker='Others', count=7),
            observed_at=self.command.observed_at)
        self.assertEqual(response['status'], 'COMPLETED')
        self.assertEqual((await self.jobs.get(self.job.id)).status, JobStatus.COMPLETED)
        self.assertIsNone((await self.runners.get(self.runner_id)).current_job_id)
        async with engine.connect() as connection:
            record = (await connection.execute(select(db.main_reports))).mappings().one()
            self.assertEqual(record['maker'], 'OTHERS')
            self.assertEqual([record[m] for m in db.MONTH_COLUMNS], [7,2]+[None]*10)
            history = (await connection.execute(select(db.report_update_history))).mappings().one()
            self.assertEqual(history['details']['unresolvedMakers'], 0)

    async def test_full_data_transaction_rollback_cannot_complete_or_release_worker(self):
        from app.repositories.file_store import PostgresFileStore
        with patch('app.repositories.file_store.save_job', new=AsyncMock(side_effect=RuntimeError('forced failure'))):
            with self.assertRaises(RuntimeError):
                await PostgresFileStore().commit_excel(self.job.id, 'fixture.xlsx', self.workbook_bytes())
        self.assertEqual((await self.jobs.get(self.job.id)).status, JobStatus.WAITING_RESULT)
        self.assertEqual((await self.runners.get(self.runner_id)).current_job_id, str(self.job.id))
        async with engine.connect() as c:
            for table in (db.main_reports,db.report_update_history):
                self.assertEqual(await c.scalar(select(func.count()).select_from(table)), 0)

    async def test_invalid_manufacturer_or_count_rejects_whole_filter(self):
        from app.repositories.file_store import PostgresFileStore
        for content in (self.workbook_bytes(maker='Other'), self.workbook_bytes(maker='Unknown'),
                        self.workbook_bytes(count='invalid')):
            with self.assertRaisesRegex(ValueError,'MAIN_REPORT_PARSE_FAILED'):
                await PostgresFileStore().commit_excel(self.job.id, 'fixture.xlsx', content)
        self.assertEqual((await self.jobs.get(self.job.id)).status, JobStatus.WAITING_RESULT)
        async with engine.connect() as c:
            self.assertEqual(await c.scalar(select(func.count()).select_from(db.main_reports)), 0)

    async def test_main_report_http_commit_immediately_reads_back_and_notifies(self):
        from app.config import settings
        content = self.workbook_bytes()
        boundary='fixture-main-report'
        body=(f'--{boundary}\r\nContent-Disposition: form-data; name="observedAt"\r\n\r\n'
            '2026-10-02T14:35:42+07:00\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="fixture.xlsx"\r\n'
            'Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n').encode()+content+f'\r\n--{boundary}--\r\n'.encode()
        headers={'content-type':f'multipart/form-data; boundary={boundary}',
            'x-vahan-runner-token':settings.runner_token,'x-vahan-runner-id':self.runner_id}
        path=f'/api/jobs/{self.job.id}/main-report'
        self.assertEqual((await asgi_request('POST',path,body))[0],401)
        with patch('app.realtime.server.sio.emit',new=AsyncMock()) as emit:
            code, response=await asgi_request('POST',path,body,headers)
            self.assertEqual(code,200)
            self.assertEqual(response['status'],'COMPLETED')
            self.assertEqual(response['summary']['parsedRows'],1)
            self.assertEqual(emit.await_count,2)
            self.assertEqual(emit.await_args_list[0].kwargs,{'room':f'job:{self.job.id}','namespace':'/ui'})
            notification=emit.await_args_list[1]
            self.assertEqual(notification.args[0],'reports:updated')
            self.assertEqual(notification.kwargs,{'room':'reports:shared','namespace':'/ui'})
            self.assertEqual(notification.args[1]['newRows'],1)
            self.assertEqual(notification.args[1]['newMonthValues'],2)
            self.assertNotIn('jobId',notification.args[1])
            # At notification time, committed rows are already visible to other connections.
            from app.api.annual_reports import annual_reports
            reader=Request({'type':'http','headers':[]})
            reader.state.authenticated_user='another-account';reader.state.authenticated_role='user'
            view=await annual_reports(reader,year=2026,dataset='',state='',rto='',offset=0,limit=100)
            self.assertEqual(view['rows'][0]['months'][:2],[1,2])
            self.assertEqual(view['lastSaved'],notification.args[1])
        async with engine.connect() as c:
            self.assertEqual(await c.scalar(select(db.main_reports.c.jan)),1)
            self.assertEqual(await c.scalar(select(func.count()).select_from(db.report_update_history)),1)
        self.assertEqual((await self.jobs.get(self.job.id)).status,JobStatus.COMPLETED)

    async def test_realtime_failure_does_not_fail_an_already_committed_filter(self):
        from app.api.excel import upload_excel
        from fastapi import UploadFile
        from io import BytesIO
        request=Request({'type':'http','headers':[]})
        request.state.authenticated_runner=True
        with patch('app.realtime.server.sio.emit',new=AsyncMock(side_effect=RuntimeError('Fixture transport failure'))), \
             patch('app.realtime.report_notifications.logger.exception'):
            result=await upload_excel(self.job.id,UploadFile(file=BytesIO(self.workbook_bytes()),filename='fixture.xlsx'),
                request,runner_id=self.runner_id,observed_at=self.command.observed_at,page_url='')
        self.assertEqual(result['status'],'COMPLETED')
        self.assertEqual((await self.jobs.get(self.job.id)).status,JobStatus.COMPLETED)
        async with engine.connect() as connection:
            self.assertEqual(await connection.scalar(select(func.count()).select_from(db.main_reports)),1)

    def execution_proof(self):
        from app.models.filter_execution import CONTROL_SELECTORS
        checks = []
        for field, value in self.job.filters.runner_payload().items():
            if field in {'autoApply', 'autoExport'}:
                continue
            expected = value if isinstance(value, list) else [value]
            checks.append(dict(field=field, selector=CONTROL_SELECTORS[field], expected=expected,
                actual=expected, match=True, mode='requested'))
        return dict(version='parallel-fill-v1', fieldCount=len(checks), checks=checks,
            validatedAt='2026-10-02T16:02:03+07:00', verificationMs=80,
            durationMs=420, groups=[dict(name='geography', startedMs=1, durationMs=280, attempts=1)], repairPasses=0)

    async def test_filter_proofs_accept_sequential_fill_and_legacy_before_apply(self):
        from app.realtime.runner_events import job_filters_verified
        await self.jobs.update_status(self.job.id, JobStatus.FILLING_FILTERS)
        proof = self.execution_proof()
        proof['version'] = 'sequential-mutation-v2'
        payload = dict(jobId=str(self.job.id), phase='filled', execution=proof)
        self.assertTrue((await job_filters_verified(self.socket_id, payload))['ok'])
        await self.jobs.update_status(self.job.id, JobStatus.SUBMITTING)
        payload['phase'] = 'before-apply'
        payload['execution'] = self.execution_proof()
        self.assertTrue((await job_filters_verified(self.socket_id, payload))['ok'])
        saved = await PostgresJobRepository().get(self.job.id)
        self.assertEqual(set(saved.filter_execution), {'filled', 'before-apply'})
        self.assertEqual(saved.filter_execution['filled']['version'], 'sequential-mutation-v2')
        self.assertEqual(saved.filter_execution['before-apply']['version'], 'parallel-fill-v1')
        self.assertEqual(saved.filter_execution['filled']['durationMs'], 420)
        self.assertEqual(saved.filter_execution['before-apply']['validatedAt'], '2026-10-02T16:02:03+07:00')

    async def test_incomplete_or_different_case_proof_is_rejected_before_sql_write(self):
        from app.realtime.runner_events import job_filters_verified
        await self.jobs.update_status(self.job.id, JobStatus.FILLING_FILTERS)
        original = self.execution_proof()
        for change in ['omitted', 'wrong-case', 'wrong-value', 'wrong-selector', 'duplicate', 'false-match', 'unsupported-version']:
            proof = json.loads(json.dumps(original))
            if change == 'omitted':
                proof['checks'].pop(); proof['fieldCount'] -= 1
            elif change == 'wrong-case': proof['checks'][0]['expected'] = ['Other state']
            elif change == 'wrong-value': proof['checks'][0]['actual'] = ['Other state']
            elif change == 'wrong-selector': proof['checks'][0]['selector'] = '#not-the-control'
            elif change == 'duplicate': proof['checks'].append(proof['checks'][0]); proof['fieldCount'] += 1
            elif change == 'unsupported-version': proof['version'] = 'unknown-fill-v3'
            else: proof['checks'][0]['match'] = False
            result = await job_filters_verified(self.socket_id, dict(jobId=str(self.job.id), phase='filled', execution=proof))
            self.assertFalse(result['ok'], change)
            self.assertIn('Filter verification rejected', result['error'], change)
            self.assertEqual((await self.jobs.get(self.job.id)).filter_execution, {})

    async def test_verification_rejects_wrong_phase_runner_and_cancelled_job(self):
        from app.models.filter_execution import FilterExecution
        from app.realtime.runner_events import job_filters_verified
        proof = self.execution_proof()
        payload = dict(jobId=str(self.job.id), phase='before-apply', execution=proof)
        self.assertFalse((await job_filters_verified(self.socket_id, payload))['ok'])
        payload['phase'] = 'unknown'
        self.assertFalse((await job_filters_verified(self.socket_id, payload))['ok'])
        await self.jobs.update_status(self.job.id, JobStatus.FILLING_FILTERS)
        self.assertIsNone(await self.jobs.record_filter_execution(self.job.id, 'other-runner', 'filled', FilterExecution.model_validate(proof)))
        await self.jobs.update_status(self.job.id, JobStatus.CANCELLED)
        payload['phase'] = 'filled'
        self.assertFalse((await job_filters_verified(self.socket_id, payload))['ok'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
