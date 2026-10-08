"""Authorization regression checks using mocked storage; no live database required."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.main import fastapi_app, require_ui_authentication
from app.api import data, run_schedules
from app.realtime import ui_events


def request(role='admin', username='admin'):
    value = Request({'type': 'http', 'method': 'PATCH', 'path': '/', 'headers': []})
    value.state.authenticated_role = role
    value.state.authenticated_user = username
    return value


class PermissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_member_http_denied_before_any_repository_access(self):
        user = {'username': 'member', 'role': 'user', 'session_id': 'fixture'}
        with patch('app.main.authenticate_access_token', AsyncMock(return_value=user)), patch('app.main.audit', AsyncMock()):
            client = TestClient(fastapi_app)
            for method, path in [('GET', '/api/filter-profiles'), ('POST', '/api/filter-profiles'),
                                 ('GET', '/api/run-schedules'), ('POST', '/api/run-schedules'),
                                 ('POST', f'/api/run-schedules/{uuid4()}/stop'),
                                 ('PATCH', f'/api/run-schedules/{uuid4()}'),
                                 ('POST', f'/api/run-schedules/{uuid4()}/pause'),
                                 ('POST', f'/api/run-schedules/{uuid4()}/resume'),
                                 ('DELETE', f'/api/run-schedules/{uuid4()}'),
                                 ('PATCH', '/api/users/admin'), ('GET', '/api/users'),
                                 ('PUT', '/api/ui-health/schedule'), ('POST', '/api/jobs'),
                                 ('GET', '/api/runners'), ('PUT', '/api/user-state/filter-cache')]:
                response = client.request(method, path, headers={'Authorization': 'Bearer fixture'})
                self.assertEqual(response.status_code, 403, (method, path, response.text))
            self.assertEqual(client.get('/api/user-state', headers={'Authorization':'Bearer fixture'}).json(), {})

    async def test_member_report_read_and_export_pass_middleware(self):
        app = FastAPI()
        app.middleware('http')(require_ui_authentication)
        async def sentinel():
            return {'ok': True}
        for path in ['/api/annual-reports', '/api/annual-reports/history', '/api/annual-reports/export', '/api/annual-reports/update-status']:
            app.add_api_route(path, sentinel, methods=['GET'])
        app.add_api_route('/api/annual-reports/coverage', sentinel, methods=['POST'])
        with patch('app.main.authenticate_access_token', AsyncMock(return_value={'username':'member','role':'user','session_id':'fixture'})):
            client = TestClient(app, headers={'Authorization':'Bearer fixture'})
            for path in ['/api/annual-reports', '/api/annual-reports/history', '/api/annual-reports/export', '/api/annual-reports/update-status']:
                self.assertEqual(client.get(path).json(), {'ok':True})
                self.assertEqual(client.delete(path).status_code, 403)
            self.assertEqual(client.post('/api/annual-reports/coverage').status_code, 200)
            self.assertEqual(client.get('/api/annual-reports/private').status_code, 403)

    async def test_admin_can_manage_another_admin_schedule(self):
        value = {'owner': 'first-admin'}
        with patch.object(run_schedules.repository, 'get', AsyncMock(return_value=value)) as get:
            owner = await run_schedules.schedule_owner(uuid4(), request(username='delegated-admin'))
            self.assertEqual(owner, 'first-admin')
            self.assertIsNone(get.await_args.args[1])
        with self.assertRaises(HTTPException) as denied:
            await run_schedules.schedule_owner(uuid4(), request(role='user'))
        self.assertEqual(denied.exception.status_code, 403)

    async def test_member_cannot_send_socket_commands_or_connect(self):
        with patch.object(ui_events, 'authenticate_access_token', AsyncMock(return_value={'role':'user'})):
            self.assertFalse(await ui_events.connect('socket', {}, {'token':'fixture'}))
        with patch.object(ui_events.sio, 'get_session', AsyncMock(return_value={'token':'fixture'})), patch.object(ui_events, 'authenticate_access_token', AsyncMock(return_value={'role':'user'})):
            for handler in [ui_events.subscribe_job, ui_events.runner_options, ui_events.submit_captcha, ui_events.refresh_captcha]:
                self.assertFalse((await handler('socket', {}))['ok'])

    async def test_role_changes_preserve_last_admin_and_revoke_sessions(self):
        rows = [{'username':'admin','role':'admin','active':True}, {'username':'member','role':'user','active':True}]
        connection = SimpleNamespace(execute=AsyncMock())
        result = MagicMock()
        result.mappings.return_value.all.return_value = rows
        connection.execute.return_value = result
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=connection)
        context.__aexit__ = AsyncMock(return_value=False)
        with patch.object(data, 'engine', SimpleNamespace(begin=lambda: context)), patch.object(ui_events, 'invalidate_user', AsyncMock()) as invalidate:
            with self.assertRaises(HTTPException) as last:
                await data.update_user('admin', data.UserUpdate(role='user'), request())
            self.assertEqual(last.exception.status_code, 409)
            self.assertEqual(connection.execute.await_count, 1)
            connection.execute.reset_mock()
            await data.update_user('member', data.UserUpdate(role='admin'), request())
            self.assertEqual(connection.execute.await_count, 3)  # lock users, change role, revoke sessions
            invalidate.assert_awaited_once_with('member')
            rows.append({'username':'another-admin','role':'admin','active':True})
            await data.update_user('admin', data.UserUpdate(role='user'), request(username='another-admin'))
            invalidate.assert_any_await('admin')


if __name__ == '__main__':
    unittest.main()
