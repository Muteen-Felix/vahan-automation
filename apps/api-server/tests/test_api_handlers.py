"""Focused handler tests for API status, authorization, and route error mapping."""
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Response
from starlette.datastructures import UploadFile
from starlette.requests import Request

from app.api import auth, batch_queue, data, health, jobs, ocr, worker_pool
from app.models.job import Job, JobStatus, ReportSource
from app.models.report_result import ReportResultRequest
from app.models.runner import RunnerStatus
from app.services import services as app_services


def request(user='test-admin', role='admin', *, runner=False, runner_id=None):
    headers = [(b'x-vahan-runner-id', runner_id.encode())] if runner_id else []
    value = Request({'type': 'http', 'method': 'POST', 'headers': headers})
    value.state.authenticated_user = user
    value.state.authenticated_role = role
    value.state.token_session = f'session-{user}'
    value.state.authenticated_runner = runner
    return value


def live_runner(runner_id='runner-test'):
    return SimpleNamespace(
        id=runner_id,
        source=ReportSource.NEW,
        status=RunnerStatus.ONLINE,
        current_job_id=None,
    )


async def test_health_routes_cover_readiness_and_network_status(monkeypatch):
    assert await health.health() == {'status': 'ok'}
    monkeypatch.setattr(health, 'required_revision', lambda: 'not-the-current-revision')
    with pytest.raises(HTTPException) as mismatch:
        await health.ready()
    assert mismatch.value.status_code == 503

    class BrokenConnection:
        async def __aenter__(self):
            raise OSError('database offline')

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(health, 'engine', SimpleNamespace(connect=lambda: BrokenConnection()))
    with pytest.raises(HTTPException) as unavailable:
        await health.ready()
    assert unavailable.value.status_code == 503
    assert 'could not be verified' in unavailable.value.detail

    state = {'online': False, 'message': 'fixture outage'}
    monkeypatch.setattr('app.network_guard.status', AsyncMock(return_value=state))
    assert await health.network_status() == state


async def test_ocr_handler_checks_runner_job_and_current_captcha(monkeypatch):
    from app.api.ocr import OcrStartRequest, begin_ocr

    command = OcrStartRequest(jobId=uuid4(), captchaId='captcha-current')
    runner_id = 'runner-ocr'
    req = request(runner=True, runner_id=runner_id)
    with pytest.raises(HTTPException) as anonymous:
        await begin_ocr(command, request(), runner_id)
    assert anonymous.value.status_code == 403

    monkeypatch.setattr(ocr.services.runners, 'get', AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as missing_runner:
        await begin_ocr(command, req, runner_id)
    assert missing_runner.value.status_code == 403

    runner = SimpleNamespace(source=ReportSource.NEW, current_job_id=str(command.job_id))
    monkeypatch.setattr(ocr.services.runners, 'get', AsyncMock(return_value=runner))
    monkeypatch.setattr(ocr.services.jobs, 'get', AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as missing_job:
        await begin_ocr(command, req, runner_id)
    assert missing_job.value.status_code == 404

    job = SimpleNamespace(runner_id=runner_id, status=JobStatus.WAITING_CAPTCHA, captcha_id='old-captcha')
    monkeypatch.setattr(ocr.services.jobs, 'get', AsyncMock(return_value=job))
    with pytest.raises(HTTPException) as stale:
        await begin_ocr(command, req, runner_id)
    assert stale.value.status_code == 409
    job.captcha_id = command.captcha_id
    assert await begin_ocr(command, req, runner_id) == {'allowed': True}


async def test_worker_pool_routes_map_pool_errors(monkeypatch):
    monkeypatch.setattr(worker_pool, 'pool_status', AsyncMock(return_value={'desiredCount': 4}))
    assert await worker_pool.get_worker_pool() == {'desiredCount': 4}
    monkeypatch.setattr(worker_pool, 'pool_status', AsyncMock(side_effect=worker_pool.PoolError('busy')))
    with pytest.raises(HTTPException) as status_error:
        await worker_pool.get_worker_pool()
    assert status_error.value.status_code == 503

    monkeypatch.setattr(worker_pool, 'apply_pool', AsyncMock(return_value={'desiredCount': 2}))
    assert await worker_pool.set_worker_pool(worker_pool.WorkerCount(count=2)) == {'desiredCount': 2}
    monkeypatch.setattr(worker_pool, 'apply_pool', AsyncMock(side_effect=worker_pool.PoolError('busy')))
    with pytest.raises(HTTPException) as update_error:
        await worker_pool.set_worker_pool(worker_pool.WorkerCount(count=3))
    assert update_error.value.status_code == 409


async def test_auth_handlers_cover_configuration_and_expired_sessions(monkeypatch):
    monkeypatch.setattr(auth, 'settings', SimpleNamespace(ui_auth_configured=False))
    monkeypatch.setattr(auth.services.users, 'list', AsyncMock(return_value=[]))
    status = await auth.auth_status()
    assert status['configured'] is False
    with pytest.raises(HTTPException) as unconfigured:
        await auth.login(auth.LoginRequest(username='member', password='not-a-password'), Response())
    assert unconfigured.value.status_code == 503
    with pytest.raises(HTTPException) as expired:
        auth.session_deadlines(None)
    assert expired.value.status_code == 401

    req = request(user=None, role=None)
    with pytest.raises(HTTPException) as anonymous:
        await auth.current_user(req)
    assert anonymous.value.status_code == 401


async def test_auth_login_and_password_routes_cover_success_and_error_paths(monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setattr(auth, 'settings', SimpleNamespace(ui_auth_configured=True))
    monkeypatch.setattr(auth.services.users, 'authenticate', AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as bad_login:
        await auth.login(auth.LoginRequest(username='member', password='wrong-password'), Response())
    assert bad_login.value.status_code == 401

    session = 'session-login'
    user = {'session_expires_at': datetime.now(timezone.utc),
        'session_last_activity_at': datetime.now(timezone.utc)}
    monkeypatch.setattr(auth.services.users, 'authenticate', AsyncMock(return_value={'password_hash': 'hash'}))
    monkeypatch.setattr(auth.services.users, 'create_session', AsyncMock(return_value=session))
    monkeypatch.setattr(auth.services.users, 'session_user', AsyncMock(return_value=user))
    monkeypatch.setattr(auth, 'issue_access_token', lambda *_args, **_kwargs: 'fixture-token')
    response = Response()
    result = await auth.login(auth.LoginRequest(username='member', password='long-enough-password'), response)
    assert result['accessToken'] == 'fixture-token'
    assert response.headers['cache-control'] == 'no-store'

    monkeypatch.setattr(auth.services.users, 'change_password', AsyncMock())
    monkeypatch.setattr('app.realtime.ui_events.invalidate_user', AsyncMock())
    monkeypatch.setattr('app.repositories.postgres.audit', AsyncMock())
    req = request()
    assert await auth.change_password(auth.ChangePasswordRequest(
        currentPassword='current-password', newPassword='replacement-password'), req) == {'ok': True}
    with pytest.raises(HTTPException) as same_password:
        await auth.change_password(auth.ChangePasswordRequest(
            currentPassword='same-password-123', newPassword='same-password-123'), req)
    assert same_password.value.status_code == 409


async def test_data_user_and_password_routes_call_storage_and_map_conflicts(monkeypatch):
    users = [{'username': 'test-admin', 'role': 'admin'}]
    monkeypatch.setattr(data.services.users, 'list', AsyncMock(return_value=users))
    assert await data.users(request()) == users

    create = AsyncMock()
    monkeypatch.setattr(data.services.users, 'create', create)
    user = data.UserCreate(username='new-member', password='fixture-long-password', profile={'team': 'qa'})
    result = await data.create_user(user, request())
    assert result == {'username': 'new-member', 'role': 'user', 'profile': {'team': 'qa'}}
    create.assert_awaited_once()

    with pytest.raises(HTTPException) as own_reset:
        await data.reset_password('test-admin', data.ResetPasswordRequest(password='replacement-password'), request())
    assert own_reset.value.status_code == 409
    monkeypatch.setattr(data.services.users, 'change_password', AsyncMock())
    monkeypatch.setattr('app.realtime.ui_events.invalidate_user', AsyncMock())
    monkeypatch.setattr(data, 'audit', AsyncMock())
    assert await data.reset_password('other-member',
        data.ResetPasswordRequest(password='replacement-password'), request()) == {'ok': True}


async def test_job_result_and_create_handlers_cover_auth_and_storage_errors(monkeypatch):
    job_id = uuid4()
    command = ReportResultRequest(result='NO_RECORD', message='No record found',
        observedAt='2026-10-01T00:00:00Z', pageUrl='https://fixture.test/report')
    with pytest.raises(HTTPException) as unauthenticated:
        await jobs.save_report_result(job_id, command, request(), 'runner')
    assert unauthenticated.value.status_code == 403

    runner_request = request(runner=True, runner_id='runner')
    monkeypatch.setattr(jobs, 'commit_report_result', AsyncMock(side_effect=PermissionError('wrong runner')))
    with pytest.raises(HTTPException) as denied:
        await jobs.save_report_result(job_id, command, runner_request, 'runner')
    assert denied.value.status_code == 403

    monkeypatch.setattr(jobs, 'commit_report_result', AsyncMock(side_effect=ValueError('Job not found.')))
    with pytest.raises(HTTPException) as missing:
        await jobs.save_report_result(job_id, command, runner_request, 'runner')
    assert missing.value.status_code == 404

    job = Job(id=job_id, runnerId='runner', ownerUsername='test-admin', filters={}, status=JobStatus.NO_DATA)
    monkeypatch.setattr(jobs, 'commit_report_result', AsyncMock(return_value=job))
    monkeypatch.setattr('app.realtime.report_notifications.notify_report_saved', AsyncMock())
    assert (await jobs.save_report_result(job_id, command, runner_request, 'runner'))['ok'] is True

    async def offline():
        raise ValueError('NETWORK_PAUSED: fixture outage')

    monkeypatch.setattr('app.network_guard.require_connection', offline)
    create = jobs.CreateJobRequest(runnerId='runner', filters={})
    with pytest.raises(HTTPException) as network_error:
        await jobs.create_job(create, request())
    assert network_error.value.status_code == 503

    async def online():
        return None

    monkeypatch.setattr('app.network_guard.require_connection', online)
    monkeypatch.setattr(jobs.services.runners, 'get', AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as missing_runner:
        await jobs.create_job(create, request())
    assert missing_runner.value.status_code == 404


async def test_job_result_reader_checks_owner_and_result(monkeypatch):
    job_id = uuid4()
    monkeypatch.setattr(jobs.services.jobs, 'get', AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as missing_job:
        await jobs.read_report_result(job_id, request())
    assert missing_job.value.status_code == 404

    job = SimpleNamespace(owner_username='another-user')
    monkeypatch.setattr(jobs.services.jobs, 'get', AsyncMock(return_value=job))
    with pytest.raises(HTTPException) as wrong_owner:
        await jobs.read_report_result(job_id, request('member', 'member'))
    assert wrong_owner.value.status_code == 404
    assert wrong_owner.value.detail == 'Resource not found.'

    job.owner_username = 'test-admin'
    monkeypatch.setattr(jobs, 'get_report_result', AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as no_result:
        await jobs.read_report_result(job_id, request())
    assert no_result.value.status_code == 404


async def test_job_create_completes_preflight_assignment_and_notification(monkeypatch):
    from contextlib import asynccontextmanager

    runner_id = 'runner-create'
    session_id = uuid4()
    runner = live_runner(runner_id)
    job = Job(runnerId=runner_id, ownerUsername='test-admin', sessionId=session_id,
        scenarioName='Fixture', filters={}, status=JobStatus.ASSIGNED)
    monkeypatch.setattr('app.network_guard.require_connection', AsyncMock())
    monkeypatch.setattr(jobs.services.runners, 'get', AsyncMock(return_value=runner))

    class Connection:
        async def scalar(self, _query):
            return None

    @asynccontextmanager
    async def connect():
        yield Connection()

    monkeypatch.setattr(jobs, 'engine', SimpleNamespace(connect=connect))
    monkeypatch.setattr('app.repositories.ui_contract.require_gate', AsyncMock(return_value='gate'))
    monkeypatch.setattr('app.repositories.ui_contract.bind_gate', AsyncMock())
    monkeypatch.setattr(jobs.services.jobs, 'assign', AsyncMock(return_value=job))
    emit = AsyncMock()
    monkeypatch.setattr(jobs.sio, 'emit', emit)
    command = jobs.CreateJobRequest(runnerId=runner_id, sessionId=session_id, scenarioName='Fixture', filters={})

    result = await jobs.create_job(command, request())

    assert result.id == job.id
    emit.assert_awaited_once()


async def test_job_report_result_maps_other_storage_errors_to_conflicts(monkeypatch):
    command = ReportResultRequest(result='NO_RECORD', message='No record found',
        observedAt='2026-10-01T00:00:00Z', pageUrl='https://fixture.test/report')
    monkeypatch.setattr(jobs, 'commit_report_result', AsyncMock(side_effect=ValueError('stale report')))

    with pytest.raises(HTTPException) as conflict:
        await jobs.save_report_result(uuid4(), command, request(runner=True), 'runner')

    assert conflict.value.status_code == 409
    assert conflict.value.detail == 'stale report'


async def test_job_create_rejects_legacy_sources_and_unsupported_runner_states(monkeypatch):
    monkeypatch.setattr('app.network_guard.require_connection', AsyncMock())
    command = jobs.CreateJobRequest(runnerId='runner', filters={})

    with pytest.raises(HTTPException) as retired_source:
        await jobs.create_job(command.model_copy(update={'source': ReportSource.OLD}), request())
    assert retired_source.value.status_code == 410

    unsupported = live_runner('runner')
    unsupported.source = ReportSource.OLD
    reconnecting = live_runner('runner')
    reconnecting.status = RunnerStatus.RECONNECTING
    busy = live_runner('runner')
    busy.current_job_id = str(uuid4())

    for runner, expected_status in ((unsupported, 409), (reconnecting, 409), (busy, 409)):
        monkeypatch.setattr(jobs.services.runners, 'get', AsyncMock(return_value=runner))
        with pytest.raises(HTTPException) as rejected:
            await jobs.create_job(command, request())
        assert rejected.value.status_code == expected_status


@pytest.mark.parametrize(('update_kind', 'update_run_id', 'update_task_id'), [
    ('GLOBAL', None, None),
    ('NORMAL', uuid4(), None),
    ('NORMAL', None, 'retired-task'),
])
async def test_job_retry_rejects_missing_owner_and_retired_update_jobs(
    monkeypatch, update_kind, update_run_id, update_task_id,
):
    monkeypatch.setattr('app.network_guard.require_connection', AsyncMock())
    monkeypatch.setattr(jobs.services.runners, 'get', AsyncMock(return_value=live_runner('runner')))
    retry_id = uuid4()
    command = jobs.CreateJobRequest(runnerId='runner', retryOfJobId=retry_id, filters={})
    get_job = AsyncMock(return_value=None)
    monkeypatch.setattr(jobs.services.jobs, 'get', get_job)

    with pytest.raises(HTTPException) as missing:
        await jobs.create_job(command, request())
    assert missing.value.status_code == 404

    retry = SimpleNamespace(
        id=retry_id,
        case_id=None,
        owner_username='test-admin',
        session_id=uuid4(),
        status=JobStatus.FAILED,
        filters=command.filters,
        source=ReportSource.NEW,
        update_kind=update_kind,
        update_run_id=update_run_id,
        update_task_id=update_task_id,
    )
    get_job.return_value = retry
    with pytest.raises(HTTPException) as wrong_owner:
        await jobs.create_job(command, request(user='other-admin', role='admin'))
    assert wrong_owner.value.status_code == 409

    retry.owner_username = 'other-admin'
    with pytest.raises(HTTPException) as retired_update:
        await jobs.create_job(command, request(user='other-admin', role='admin'))
    assert retired_update.value.status_code == 409
    assert retired_update.value.detail == 'Maker Update has been removed.'


async def test_job_create_maps_gate_and_assignment_races(monkeypatch):
    from contextlib import asynccontextmanager

    runner_id = 'runner-race'
    session_id = uuid4()
    existing_job_id = str(uuid4())
    command = jobs.CreateJobRequest(runnerId=runner_id, sessionId=session_id, filters={})
    monkeypatch.setattr('app.network_guard.require_connection', AsyncMock())
    monkeypatch.setattr(jobs.services.runners, 'get', AsyncMock(return_value=live_runner(runner_id)))

    class Connection:
        async def scalar(self, _query):
            return existing_job_id

    @asynccontextmanager
    async def connect():
        yield Connection()

    monkeypatch.setattr(jobs, 'engine', SimpleNamespace(connect=connect))
    require_gate = AsyncMock(side_effect=ValueError('gate is blocked'))
    monkeypatch.setattr('app.repositories.ui_contract.require_gate', require_gate)

    with pytest.raises(HTTPException) as gate_error:
        await jobs.create_job(command, request())
    assert gate_error.value.status_code == 409

    require_gate.side_effect = None
    require_gate.return_value = 'gate'
    assign = AsyncMock(side_effect=ValueError('runner assignment changed'))
    monkeypatch.setattr(jobs.services.jobs, 'assign', assign)
    with pytest.raises(HTTPException) as assignment_error:
        await jobs.create_job(command, request())
    assert assignment_error.value.status_code == 409

    assign.side_effect = None
    assign.return_value = None
    with pytest.raises(HTTPException) as assignment_race:
        await jobs.create_job(command, request())
    assert assignment_race.value.status_code == 409

    job = Job(runnerId=runner_id, ownerUsername='test-admin', sessionId=session_id,
        filters={}, status=JobStatus.ASSIGNED)
    assign.return_value = job
    monkeypatch.setattr('app.repositories.ui_contract.bind_gate', AsyncMock())
    monkeypatch.setattr(jobs.sio, 'emit', AsyncMock())
    assert await jobs.create_job(command, request()) == job
    assert require_gate.await_args.kwargs['fresh'] is False


async def test_job_lookup_cancel_and_list_routes_cover_error_paths(monkeypatch):
    job_id = uuid4()
    get_job = AsyncMock(return_value=None)
    monkeypatch.setattr(jobs.services.jobs, 'get', get_job)

    with pytest.raises(HTTPException) as missing_get:
        await jobs.get_job(job_id, request())
    assert missing_get.value.status_code == 404

    job = Job(id=job_id, runnerId='runner', ownerUsername='member', filters={})
    get_job.return_value = job
    with pytest.raises(HTTPException) as denied_get:
        await jobs.get_job(job_id, request(user='another-member', role='member'))
    assert denied_get.value.status_code == 404
    assert await jobs.get_job(job_id, request(user='member', role='member')) == job

    get_job.return_value = None
    with pytest.raises(HTTPException) as missing_cancel:
        await jobs.cancel_job(job_id, request())
    assert missing_cancel.value.status_code == 404

    terminal = job.model_copy(update={'status': JobStatus.COMPLETED})
    get_job.return_value = terminal
    with pytest.raises(HTTPException) as terminal_cancel:
        await jobs.cancel_job(job_id, request(user='member', role='member'))
    assert terminal_cancel.value.status_code == 409

    get_job.return_value = job
    transition = AsyncMock(return_value=None)
    monkeypatch.setattr(jobs.services.jobs, 'transition_status', transition)
    with pytest.raises(HTTPException) as transition_race:
        await jobs.cancel_job(job_id, request(user='member', role='member'))
    assert transition_race.value.status_code == 409

    listed = [job]
    list_all = AsyncMock(return_value=listed)
    monkeypatch.setattr(jobs.services.jobs, 'list_all', list_all)
    monkeypatch.setattr(jobs, 'owner_filter', lambda _request: 'member')
    assert await jobs.list_jobs(request(user='member', role='member'), offset=4, limit=7) == listed
    list_all.assert_awaited_once_with('member', offset=4, limit=7)


async def test_data_handlers_cover_runner_logs_user_state_and_file_upload(monkeypatch):
    with pytest.raises(HTTPException) as unauthenticated:
        await data.runner_log(data.RunnerLog(message='fixture'), request(), 'runner-data')
    assert unauthenticated.value.status_code == 403

    monkeypatch.setattr(data.services.runners, 'get', AsyncMock(return_value=live_runner('runner-data')))
    audit = AsyncMock()
    monkeypatch.setattr(data, 'audit', audit)
    assert await data.runner_log(data.RunnerLog(level='warning', message='fixture'),
        request(runner=True, runner_id='runner-data'), 'runner-data') == {'ok': True}
    audit.assert_awaited_once()

    monkeypatch.setattr(data.services.users, 'state', AsyncMock(return_value={'theme': 'dark'}))
    assert await data.state(request(role='user')) == {}
    assert await data.state(request(role='admin')) == {'theme': 'dark'}
    with pytest.raises(HTTPException) as protected:
        await data.put_state('authToken', data.StateValue(value='secret'), request())
    assert protected.value.status_code == 400
    put_state = AsyncMock()
    monkeypatch.setattr(data.services.users, 'put_state', put_state)
    assert await data.put_state('displayMode', data.StateValue(value={'compact': True}), request()) == {'ok': True}
    put_state.assert_awaited_once()

    monkeypatch.setattr(data.services.files, 'list', AsyncMock(return_value=[]))
    assert await data.files(request()) == []
    monkeypatch.setattr(data, 'read_upload', AsyncMock(return_value=b'fixture'))
    uploaded = {'id': 'file-id'}
    monkeypatch.setattr(data.services.files, 'put', AsyncMock(return_value=uploaded))
    file = UploadFile(filename='C:\\temp\\report.csv', file=BytesIO(b'fixture'))
    assert await data.upload(file, request()) == uploaded


async def test_data_file_handlers_map_missing_files_and_runner_artifacts(monkeypatch):
    with pytest.raises(HTTPException) as missing:
        await data.accessible_file('missing', request())
    assert missing.value.status_code == 404

    monkeypatch.setattr(data.services.files, 'get', AsyncMock(return_value={
        'id': 'file-id', 'owner_username': 'test-admin', 'name': 'report.csv',
        'mime_type': 'text/csv', 'sha256': 'a' * 64, 'content': b'a,b\n1,2\n',
    }))
    downloaded = await data.download(uuid4(), request())
    assert downloaded.body == b'a,b\n1,2\n'
    with pytest.raises(HTTPException) as retired_rows:
        await data.rows(uuid4(), request())
    assert retired_rows.value.status_code == 410

    with pytest.raises(HTTPException) as wrong_runner:
        await data.runner_artifact(uuid4(), UploadFile(filename='shot.png', file=BytesIO(b'x')),
            request(runner=True, runner_id='other'), 'other')
    assert wrong_runner.value.status_code == 403

    job = SimpleNamespace(runner_id='runner-artifact')
    monkeypatch.setattr(data.services.jobs, 'get', AsyncMock(return_value=job))
    monkeypatch.setattr(data, 'read_upload', AsyncMock(return_value=b'image'))
    saved = AsyncMock(return_value={'id': 'artifact-id'})
    monkeypatch.setattr(data.services.files, 'put', saved)
    result = await data.runner_artifact(uuid4(), UploadFile(filename='shot.png', file=BytesIO(b'image')),
        request(runner=True, runner_id='runner-artifact'), 'runner-artifact')
    assert result == {'id': 'artifact-id'}
    assert saved.await_args.kwargs['kind'] == 'screenshot'


async def test_batch_queue_routes_map_errors_and_start_pause_resume(monkeypatch):
    session_id = uuid4()
    task = {'name': 'Office A', 'filters': {'states': ['State A'], 'rtos': ['Office A']}}
    command = batch_queue.StartQueueInput(sessionId=session_id, tasks=[task], maxWorkers=2)
    req = request()
    monkeypatch.setattr(app_services.runners, 'list', AsyncMock(return_value=[]))
    with pytest.raises(HTTPException) as no_workers:
        await batch_queue.start_queue(command, req)
    assert no_workers.value.status_code == 409

    monkeypatch.setattr(app_services.runners, 'list', AsyncMock(return_value=[live_runner()]))
    monkeypatch.setattr('app.repositories.ui_contract.require_gate', AsyncMock(return_value='gate-id'))
    bind = AsyncMock()
    monkeypatch.setattr('app.repositories.ui_contract.bind_gate', bind)
    monkeypatch.setattr('app.worker_pool.apply_pool', AsyncMock())
    queue_start = AsyncMock()
    snapshot = {'sessionId': str(session_id), 'status': 'RUNNING'}
    monkeypatch.setattr(batch_queue.queue, 'start', queue_start)
    monkeypatch.setattr(batch_queue.queue, 'snapshot', AsyncMock(return_value=snapshot))
    assert await batch_queue.start_queue(command, req) == snapshot
    queue_start.assert_awaited_once()
    bind.assert_awaited_once()

    monkeypatch.setattr(batch_queue.queue, 'set_status', AsyncMock())
    assert await batch_queue.pause_queue(session_id, req) == {'status': 'PAUSED'}
    monkeypatch.setattr(batch_queue.queue, 'snapshot', AsyncMock(return_value={'maxWorkers': 3}))
    monkeypatch.setattr(batch_queue.queue, 'set_status', AsyncMock())
    assert await batch_queue.resume_queue(session_id, req) == {'status': 'RUNNING'}


async def _raise_lookup():
    raise LookupError('missing queue')


async def test_batch_queue_runner_claim_auth_gate_and_assignment(monkeypatch):
    from app.api.batch_queue import claim_queue_task

    command_id = uuid4()
    unauthenticated = request()
    unauthenticated.scope['headers'] = [(b'x-vahan-runner-id', b'runner-claim')]
    with pytest.raises(HTTPException) as auth_error:
        await claim_queue_task(unauthenticated)
    assert auth_error.value.status_code == 401

    idle = request(runner=True, runner_id='runner-claim')
    monkeypatch.setattr(batch_queue.queue, 'candidate_sessions', AsyncMock(return_value=[]))
    assert await claim_queue_task(idle) == {'type': 'idle'}
    assert await claim_queue_task(idle, batch_queue.QueueClaimRequest(sessionId=command_id)) == {'type': 'done'}

    session_id = uuid4()
    monkeypatch.setattr(batch_queue.queue, 'candidate_sessions', AsyncMock(return_value=[(session_id, 'test-admin')]))
    monkeypatch.setattr(batch_queue.queue, 'needs_work', AsyncMock(return_value=True))
    monkeypatch.setattr('app.repositories.ui_contract.require_gate', AsyncMock(
        side_effect=ValueError('UI_PREFLIGHT_REQUIRED: check required')))
    assert await claim_queue_task(idle) == {'type': 'gate_required'}

    job = Job(runnerId='runner-claim', ownerUsername='test-admin', filters={}, status=JobStatus.ASSIGNED)
    monkeypatch.setattr('app.repositories.ui_contract.require_gate', AsyncMock())
    monkeypatch.setattr(batch_queue.queue, 'needs_work', AsyncMock(return_value=False))
    monkeypatch.setattr(batch_queue.queue, 'claim', AsyncMock(return_value={'type': 'assigned', 'job': job}))
    result = await claim_queue_task(idle)
    assert result['type'] == 'assigned'
    assert result['job']['jobId'] == str(job.id)


async def test_batch_queue_call_converts_storage_errors():
    with pytest.raises(HTTPException) as missing:
        await batch_queue.call(_raise_lookup())
    assert missing.value.status_code == 404

    async def conflict():
        raise ValueError('queue conflict')

    with pytest.raises(HTTPException) as invalid:
        await batch_queue.call(conflict())
    assert invalid.value.status_code == 409


async def test_filter_profile_routes_map_save_errors_and_delete(monkeypatch):
    from app.api import filter_profiles

    value = {'id': str(uuid4()), 'name': 'Fixture'}
    monkeypatch.setattr(filter_profiles.profiles, 'list', AsyncMock(return_value=[value]))
    assert await filter_profiles.list_profiles(request()) == [value]
    monkeypatch.setattr(filter_profiles.profiles, 'save', AsyncMock(return_value=value))
    assert await filter_profiles.create_profile(SimpleNamespace(), request()) == value
    assert await filter_profiles.update_profile(uuid4(), SimpleNamespace(), request()) == value

    monkeypatch.setattr(filter_profiles.profiles, 'save', AsyncMock(side_effect=LookupError('missing profile')))
    with pytest.raises(HTTPException) as missing:
        await filter_profiles.update_profile(uuid4(), SimpleNamespace(), request())
    assert missing.value.status_code == 404

    deleted = AsyncMock()
    monkeypatch.setattr(filter_profiles.profiles, 'delete', deleted)
    assert await filter_profiles.delete_profile(uuid4(), 3, request()) == {'ok': True}
    deleted.assert_awaited_once()
    monkeypatch.setattr(filter_profiles.profiles, 'delete', AsyncMock(side_effect=ValueError('stale revision')))
    with pytest.raises(HTTPException) as conflict:
        await filter_profiles.delete_profile(uuid4(), 1, request())
    assert conflict.value.status_code == 409


async def test_filter_profile_live_options_and_maker_routes(monkeypatch):
    from contextlib import asynccontextmanager
    from datetime import datetime
    from app.api import filter_profiles
    from app.models.filter_profile import FIELD_ORDER

    @asynccontextmanager
    async def reserve(_runner_id, _owner):
        yield 'socket-fixture', 'lease-fixture'

    monkeypatch.setattr('app.repositories.ui_contract.require_gate', AsyncMock())
    monkeypatch.setattr(filter_profiles, 'reserve_options_runner', reserve)
    renew = AsyncMock()
    monkeypatch.setattr(filter_profiles, 'renew_lease', renew)
    options = {field: ['Fixture value'] for field in FIELD_ORDER}

    async def reply(_event, payload, **_kwargs):
        if payload['type'] == 'GET_FILTER_CONTEXT':
            return {'ok': True, 'options': options}
        return {'ok': True, 'options': ['Office A', 'Office B']}

    monkeypatch.setattr(filter_profiles.sio, 'call', reply)
    command = filter_profiles.OptionsInput(runnerId='runner-options', year=datetime.now().year,
        context={'states': ['State A', 'State B']})
    result = await filter_profiles.load_options(command, request())
    assert result['rtos'] == ['Office A', 'Office B']
    assert renew.await_count == 2

    maker_command = filter_profiles.MakerSearchInput(runnerId='runner-options',
        year=datetime.now().year, search='Maker')
    assert await filter_profiles.search_makers(maker_command, request()) == ['Office A', 'Office B']

    monkeypatch.setattr(filter_profiles.sio, 'call', AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as invalid_ack:
        await filter_profiles.search_makers(maker_command, request())
    assert invalid_ack.value.status_code == 409


async def test_run_schedule_routes_forward_operations_and_errors(monkeypatch):
    from app.api import run_schedules

    schedule_id = uuid4()
    value = {'id': str(schedule_id), 'owner': 'test-admin', 'status': 'PAUSED'}
    monkeypatch.setattr(run_schedules, 'public_schedule', lambda item: item)
    monkeypatch.setattr('app.run_diagnostics.attach_diagnostics', AsyncMock(return_value=[value]))
    monkeypatch.setattr(run_schedules.repository, 'list', AsyncMock(return_value=[value]))
    assert await run_schedules.list_schedules(request()) == [value]

    from unittest.mock import Mock
    wake = Mock()
    monkeypatch.setattr(run_schedules, 'wake_scheduler', wake)
    monkeypatch.setattr(run_schedules.repository, 'create', AsyncMock(return_value=value))
    assert await run_schedules.create_schedule(SimpleNamespace(), request()) == value
    monkeypatch.setattr(run_schedules.repository, 'set_owner_time_zone', AsyncMock(return_value=[value]))
    assert await run_schedules.set_schedule_time_zone(SimpleNamespace(time_zone='Asia/Kolkata'), request()) == [value]

    monkeypatch.setattr(run_schedules.repository, 'get', AsyncMock(return_value=value))
    monkeypatch.setattr(run_schedules.repository, 'toggle', AsyncMock(return_value=value))
    assert await run_schedules.toggle_schedule(schedule_id, run_schedules.RunScheduleToggle(enabled=False), request()) == value
    monkeypatch.setattr(run_schedules.repository, 'pause', AsyncMock(return_value=value))
    assert await run_schedules.pause_schedule(schedule_id, request()) == value
    monkeypatch.setattr(run_schedules.repository, 'resume', AsyncMock(return_value=value))
    assert await run_schedules.resume_schedule(schedule_id, request()) == value

    monkeypatch.setattr('app.run_scheduler.stop_scheduled_run', AsyncMock())
    monkeypatch.setattr(run_schedules.repository, 'get', AsyncMock(side_effect=[value, value]))
    assert await run_schedules.stop_schedule(schedule_id, request()) == value
    monkeypatch.setattr(run_schedules.repository, 'get', AsyncMock(return_value=value))
    monkeypatch.setattr(run_schedules.repository, 'delete', AsyncMock())
    assert await run_schedules.delete_schedule(schedule_id, request()) == {'ok': True}
    assert wake.call_count >= 6

    with pytest.raises(HTTPException) as not_found:
        await run_schedules.call(_raise_lookup())
    assert not_found.value.status_code == 404


async def test_excel_verify_and_download_routes_cover_missing_and_duplicate_files(monkeypatch):
    from app.api import excel

    job_id, session_id = uuid4(), uuid4()
    job = Job(id=job_id, runnerId='runner', ownerUsername='test-admin', sessionId=session_id,
        filters={}, scenarioName='Fixture', status=JobStatus.COMPLETED)
    files = [{'id': 'file-id', 'job_id': str(job_id), 'name': 'fixture.xlsx', 'size': 512}]
    monkeypatch.setattr(excel.services.files, 'list', AsyncMock(return_value=files))
    monkeypatch.setattr(excel.services.jobs, 'list_all', AsyncMock(return_value=[job]))
    verify = excel.VerifyReportsRequest(fileNames=['fixture.xlsx', 'missing.xlsx'],
        sessionIds={'fixture.xlsx': session_id})
    assert await excel.verify_exported_reports(verify, request()) == {
        'files': {'fixture.xlsx': 512, 'missing.xlsx': 0}}

    monkeypatch.setattr(excel.services.files, 'list', AsyncMock(return_value=[]))
    with pytest.raises(HTTPException) as missing:
        await excel.download_stored_report('missing.xlsx', request())
    assert missing.value.status_code == 404

    monkeypatch.setattr(excel.services.files, 'list', AsyncMock(return_value=[files[0], files[0]]))
    with pytest.raises(HTTPException) as duplicate:
        await excel.download_stored_report('fixture.xlsx', request())
    assert duplicate.value.status_code == 409

    file = {'name': 'fixture.xlsx', 'mime_type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'sha256': 'a' * 64, 'content': b'workbook'}
    monkeypatch.setattr(excel.services.files, 'list', AsyncMock(return_value=[files[0]]))
    monkeypatch.setattr(excel.services.files, 'get', AsyncMock(return_value=file))
    download = await excel.download_stored_report('fixture.xlsx', request())
    assert download.body == b'workbook'


async def test_job_file_download_checks_job_owner_and_blob(monkeypatch):
    from app.api import excel

    job_id = uuid4()
    monkeypatch.setattr(excel.services.jobs, 'get', AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as missing_job:
        await excel.download_excel(job_id, request())
    assert missing_job.value.status_code == 404

    job = SimpleNamespace(owner_username='test-admin')
    monkeypatch.setattr(excel.services.jobs, 'get', AsyncMock(return_value=job))
    monkeypatch.setattr(excel.services.files, 'for_job', AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as missing_file:
        await excel.download_no_data_file(job_id, request())
    assert missing_file.value.status_code == 404

    blob = {'name': 'no-data.txt', 'mime_type': 'text/plain', 'sha256': 'b' * 64, 'content': b'No data'}
    monkeypatch.setattr(excel.services.files, 'for_job', AsyncMock(return_value=blob))
    result = await excel.download_no_data_file(job_id, request())
    assert result.body == b'No data'


async def test_ui_health_helpers_and_download_errors(monkeypatch):
    from app.api import ui_health

    assert ui_health._normalise_date(None) is None
    assert ui_health._normalise_date('2026-10-15') == '2026-10-15'
    with pytest.raises(HTTPException) as invalid_date:
        ui_health._normalise_date('15-10-2026')
    assert invalid_date.value.status_code == 400

    monkeypatch.setattr(ui_health.services.ui_health_logs, 'resolve_report', AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as missing:
        await ui_health.download_ui_health_report('missing.csv')
    assert missing.value.status_code == 404
    monkeypatch.setattr(ui_health.services.ui_health_logs, 'resolve_report', AsyncMock(return_value=b'csv-data'))
    response = await ui_health.download_ui_health_report('health.csv')
    assert response.body == b'csv-data'


async def test_ui_health_preflight_passes_matching_sql_evidence(monkeypatch):
    from contextlib import asynccontextmanager
    from app.api import ui_health

    @asynccontextmanager
    async def reserve(_runner_ids, _owner):
        yield {'runner-preflight': ('socket-preflight', 'lease')}

    evidence = {'healthCheck': {'contractValidation': {
        'allowed': True, 'runnerId': 'runner-preflight', 'versionId': 'contract-v1',
    }}}

    class Connection:
        async def scalar(self, _query):
            return evidence

        async def execute(self, _query):
            return None

    @asynccontextmanager
    async def connect():
        yield Connection()

    @asynccontextmanager
    async def begin():
        yield Connection()

    monkeypatch.setattr(ui_health, 'engine', SimpleNamespace(connect=connect, begin=begin))
    monkeypatch.setattr('app.worker_pool.pool_value', AsyncMock(return_value={'desiredCount': 2}))
    monkeypatch.setattr(ui_health, 'reserve_preflight_runners', reserve)
    monkeypatch.setattr('app.repositories.ui_contract.gate_generation', AsyncMock(return_value=1))
    monkeypatch.setattr('app.repositories.ui_contract.next_check_seq', AsyncMock(return_value=1))
    monkeypatch.setattr('app.repositories.ui_contract.current', AsyncMock(return_value={
        'blocked': False, 'blockedRunnerIds': [], 'versionId': 'contract-v1', 'revision': 1,
    }))
    monkeypatch.setattr(ui_health.sio, 'call', AsyncMock(return_value={'ok': True}))
    monkeypatch.setattr(ui_health.sio, 'emit', AsyncMock())

    result = await ui_health.preflight(ui_health.PreflightInput(runnerIds=['runner-preflight']), request())

    assert result['allowed'] is True
    assert result['reports'][0]['runnerId'] == 'runner-preflight'


async def test_ui_health_gate_admin_routes_publish_state_and_map_conflicts(monkeypatch):
    from app.api import ui_health
    from app.repositories.ui_contract import GateOpError

    monkeypatch.setattr(ui_health, '_publish_gate_state', AsyncMock(return_value={
        'blocked': False, 'blockedRunnerIds': [],
    }))
    monkeypatch.setattr('app.repositories.ui_contract.retire_runner_error', AsyncMock(return_value={'retired': True}))
    result = await ui_health.admin_retire_runner_error('gone-runner', ui_health.GateReason(reason='worker removed'), request())
    assert result['retired'] is True
    assert result['blocked'] is False

    monkeypatch.setattr('app.repositories.ui_contract.invalidate_gates', AsyncMock(
        side_effect=GateOpError(409, 'GATE_ACTIVE', 'A report is running.')))
    with pytest.raises(HTTPException) as active:
        await ui_health.admin_invalidate_gates(ui_health.GateReason(reason='rollback'), request())
    assert active.value.status_code == 409


async def test_runner_list_route_returns_registered_runners(monkeypatch):
    from app.api import runners

    expected = [live_runner()]
    monkeypatch.setattr(runners.services.runners, 'list', AsyncMock(return_value=expected))
    assert await runners.list_runners() == expected
