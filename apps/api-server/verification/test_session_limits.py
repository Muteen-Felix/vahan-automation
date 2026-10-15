"""Session expiry and job independence on an explicitly disposable PostgreSQL DB."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy.engine import make_url

name = os.environ.get('VAHAN_SESSION_TEST_DATABASE', '')
if not name.startswith('vahan_session_') or not name.endswith('_test'):
    raise RuntimeError('Use a disposable vahan_session_*_test database.')
os.environ['DATABASE_URL'] = make_url(os.environ['DATABASE_URL']).set(database=name).render_as_string(hide_password=False)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
subprocess.run([sys.executable, '-m', 'app.migrate'], check=True)

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from app.config import settings
from app.db import engine, schema as db
from app.main import fastapi_app
from app.models.job import Job, JobStatus
from app.repositories.postgres import session_hash
from app.services import services
from app.security import ABSOLUTE_TTL_SECONDS, IDLE_TIMEOUT_SECONDS, issue_access_token, verify_access_token
from app.realtime import ui_events


class SessionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        async with engine.begin() as connection:
            await connection.run_sync(db.metadata.drop_all)
            await connection.run_sync(db.metadata.create_all)
        await services.users.create('session-test', 'Session test password', role='admin')
        self.started = datetime.now(timezone.utc)
        with patch('app.repositories.postgres.now', return_value=self.started):
            self.session = await services.users.create_session('session-test')
        self.token = issue_access_token('session-test', self.session)
        self.headers = {'Authorization': f'Bearer {self.token}'}
        self.client = AsyncClient(transport=ASGITransport(app=fastapi_app), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()
        await engine.dispose()

    async def test_login_deadlines_and_retired_renew_endpoint(self):
        response = await self.client.post('/api/auth/login', json={'username': 'session-test', 'password': 'Session test password'})
        self.assertEqual(response.status_code, 200)
        value = response.json()
        self.assertEqual(value['expiresIn'], 43200)
        self.assertEqual(value['idleTimeoutSeconds'], 3600)
        payload = json.loads(base64.urlsafe_b64decode(value['accessToken'].split('.')[0] + '=='))
        self.assertLessEqual(payload['exp'] - payload['iat'], 43200)
        self.assertEqual((await self.client.post('/api/auth/renew', headers=self.headers)).status_code, 404)

    async def test_idle_boundary_background_reads_do_not_keep_session_alive(self):
        for seconds in (30, 1800, IDLE_TIMEOUT_SECONDS - 1):
            with patch('app.repositories.postgres.now', return_value=self.started + timedelta(seconds=seconds)):
                self.assertEqual((await self.client.get('/api/auth/me', headers=self.headers)).status_code, 200)
                self.assertEqual((await self.client.put('/api/user-state/background', headers=self.headers, json={'value': {}})).status_code, 200)
        async with engine.connect() as connection:
            last = await connection.scalar(select(db.auth_sessions.c.last_activity_at).where(db.auth_sessions.c.id == session_hash(self.session)))
        self.assertEqual(last, self.started)
        with patch('app.repositories.postgres.now', return_value=self.started + timedelta(seconds=IDLE_TIMEOUT_SECONDS)):
            self.assertEqual((await self.client.get('/api/auth/me', headers=self.headers)).status_code, 401)
            self.assertEqual((await self.client.post('/api/auth/activity', headers=self.headers)).status_code, 401)

    async def test_activity_extends_idle_but_cannot_extend_absolute_deadline(self):
        activity_at = self.started + timedelta(minutes=50)
        with patch('app.repositories.postgres.now', return_value=activity_at):
            response = await self.client.post('/api/auth/activity', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['expiresAt'], int((self.started + timedelta(hours=12)).timestamp()))
        with patch('app.repositories.postgres.now', return_value=self.started + timedelta(minutes=100)):
            self.assertEqual((await self.client.get('/api/auth/me', headers=self.headers)).status_code, 200)
        deadline = self.started + timedelta(seconds=ABSOLUTE_TTL_SECONDS)
        async with engine.begin() as connection:
            await connection.execute(update(db.auth_sessions).values(last_activity_at=deadline - timedelta(seconds=30)))
        with patch('app.repositories.postgres.now', return_value=deadline):
            self.assertEqual((await self.client.post('/api/auth/activity', headers=self.headers)).status_code, 401)

    async def test_legacy_token_without_expiry_is_rejected(self):
        payload = {'sub': 'session-test', 'sid': self.session, 'aud': 'vahan-rpa-ui', 'typ': 'access', 'iat': int(self.started.timestamp())}
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b'=')
        signature = base64.urlsafe_b64encode(hmac.new(settings.ui_auth_token_secret.encode(), encoded, hashlib.sha256).digest()).rstrip(b'=')
        legacy = f'{encoded.decode()}.{signature.decode()}'
        self.assertIsNone(verify_access_token(legacy))
        self.assertEqual((await self.client.get('/api/auth/me', headers={'Authorization': f'Bearer {legacy}'})).status_code, 401)

    async def test_member_can_record_activity_and_expiry_still_applies(self):
        async with engine.begin() as connection:
            await connection.execute(update(db.users).where(db.users.c.username == 'session-test').values(role='user'))
        self.assertEqual((await self.client.post('/api/auth/activity', headers=self.headers)).status_code, 200)
        with patch('app.repositories.postgres.now', return_value=self.started + timedelta(hours=2)):
            self.assertEqual((await self.client.get('/api/auth/me', headers=self.headers)).status_code, 401)

    async def test_logout_and_idle_expiry_leave_running_job_and_runner_auth_intact(self):
        await services.runners.register(runner_id='playwright-1', name='Fixture', socket_id='runner-fixture')
        job = await services.jobs.assign(Job(runnerId='playwright-1', sessionId=uuid4(), ownerUsername='session-test',
            status=JobStatus.ASSIGNED, filters={'states': ['State'], 'rtos': ['Office']}))
        with patch('app.repositories.postgres.now', return_value=self.started + timedelta(hours=1)):
            self.assertEqual((await self.client.get('/api/auth/me', headers=self.headers)).status_code, 401)
        with patch('app.realtime.ui_events.invalidate_session', AsyncMock()) as invalidated:
            self.assertEqual((await self.client.post('/api/auth/logout', headers=self.headers)).status_code, 200)
            invalidated.assert_awaited_once_with(self.session)
        self.assertEqual((await services.jobs.get(job.id)).status, JobStatus.ASSIGNED)
        self.assertEqual((await services.runners.get('playwright-1')).current_job_id, str(job.id))
        headers = {'X-Vahan-Runner-Token': settings.runner_token, 'X-Vahan-Runner-Id': 'playwright-1'}
        self.assertEqual((await self.client.get('/api/ui-health/contract', headers=headers)).status_code, 200)
        self.assertEqual((await self.client.get('/api/auth/me', headers=self.headers)).status_code, 401)

    async def test_socket_watchdog_checks_sql_idle_deadline_and_disconnects_ui_only(self):
        stored = AsyncMock(return_value={'token': self.token})
        disconnected = AsyncMock()
        with patch('app.repositories.postgres.now', return_value=self.started + timedelta(hours=1)), \
             patch.object(ui_events.sio, 'get_session', stored), patch.object(ui_events.sio, 'disconnect', disconnected):
            await asyncio.wait_for(ui_events._disconnect_after_expiry('ui-fixture', int(self.started.timestamp()) + 43200), 2)
        disconnected.assert_awaited_once_with('ui-fixture', namespace='/ui')

    async def test_upgrade_revokes_old_sessions_and_preserves_jobs(self):
        await services.runners.register(runner_id='playwright-1', name='Fixture', socket_id='runner-fixture')
        job = await services.jobs.assign(Job(runnerId='playwright-1', sessionId=uuid4(), ownerUsername='session-test',
            status=JobStatus.ASSIGNED, filters={'states': ['State'], 'rtos': ['Office']}))
        for command in ([sys.executable, '-m', 'alembic', 'downgrade', '0011_ui_contract'],
                        [sys.executable, '-m', 'app.migrate']):
            result = await asyncio.to_thread(subprocess.run, command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(await services.users.session_user('session-test', self.session))
        self.assertEqual((await services.jobs.get(job.id)).status, JobStatus.ASSIGNED)
        self.assertEqual((await self.client.post('/api/auth/login', json={'username': 'session-test', 'password': 'Session test password'})).status_code, 200)


if __name__ == '__main__':
    unittest.main(verbosity=2)
