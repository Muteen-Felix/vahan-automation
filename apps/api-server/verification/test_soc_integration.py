"""MFA, replay, cookies, rate limits and outbox on a disposable SOC database."""
import asyncio
import base64
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4
from unittest.mock import patch

from sqlalchemy.engine import make_url
name=make_url(os.environ.get('DATABASE_URL','postgresql://localhost/')).database or ''
if not name.endswith('_soc_test'):
    raise RuntimeError('Use a dedicated disposable *_soc_test database.')
os.environ['VAHAN_REQUIRE_ADMIN_MFA']='true'
os.environ['VAHAN_MFA_ENCRYPTION_KEY']=base64.urlsafe_b64encode(os.urandom(32)).decode()
os.environ['VAHAN_TENANT_ID']='soc-integration'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import pyotp
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func, update
from app.db import engine, schema as db
from app.main import fastapi_app
from app.config import settings
from app.services import services
from app import mfa
from app.security_limits import consume
from app.security import issue_access_token


class SocTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        async with engine.begin() as connection:
            await connection.run_sync(db.metadata.drop_all)
            await connection.run_sync(db.metadata.create_all)
        await services.users.create('admin','Isolated test password',role='admin')
        self.client=AsyncClient(transport=ASGITransport(app=fastapi_app),base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose();await engine.dispose()

    async def enroll(self):
        login=await self.client.post('/api/auth/login',json={'username':'admin','password':'Isolated test password','browserSession':True})
        self.assertEqual(login.status_code,200)
        self.assertIsNone(login.json()['accessToken'])
        challenge=login.json()['mfaSetupToken']
        setup=await self.client.post('/api/auth/mfa/enroll',json={'challenge':challenge})
        self.assertEqual(setup.status_code,200)
        secret=setup.json()['secret']
        response=await self.client.post('/api/auth/mfa/confirm',json={'challenge':challenge,'code':pyotp.TOTP(secret).now()})
        self.assertEqual(response.status_code,200)
        return response,secret

    async def test_password_only_cannot_open_an_admin_session(self):
        response=await self.client.post('/api/auth/login',json={'username':'admin','password':'Isolated test password','browserSession':True})
        self.assertIn('mfaSetupToken',response.json())
        self.assertEqual((await self.client.get('/api/users')).status_code,401)
        async with engine.connect() as connection:
            self.assertEqual(await connection.scalar(select(func.count()).select_from(db.auth_sessions)),0)

    async def test_enrollment_cookie_csrf_and_logout(self):
        response,_=await self.enroll()
        cookie=response.headers['set-cookie'].lower()
        self.assertIn('httponly',cookie);self.assertIn('samesite=strict',cookie)
        self.assertNotIn('accessToken',str(self.client.cookies))
        self.assertEqual((await self.client.get('/api/auth/me')).status_code,200)
        self.assertEqual((await self.client.post('/api/auth/activity')).status_code,403)
        csrf=response.json()['csrfToken']
        self.assertEqual((await self.client.post('/api/auth/activity',headers={'X-CSRF-Token':csrf})).status_code,200)
        self.assertEqual((await self.client.post('/api/auth/logout',headers={'X-CSRF-Token':csrf})).status_code,200)
        self.assertEqual((await self.client.get('/api/auth/me')).status_code,401)

    async def test_totp_replay_and_recovery_reuse_are_rejected(self):
        response,secret=await self.enroll()
        self.assertFalse(await mfa.verify('admin',pyotp.TOTP(secret).now()))
        recovery=response.json()['recoveryCodes'][0]
        self.assertTrue(await mfa.verify('admin',recovery))
        self.assertFalse(await mfa.verify('admin',recovery))
        async with engine.connect() as connection:
            encrypted=await connection.scalar(select(db.user_mfa.c.secret))
            self.assertNotIn(secret.encode(),encrypted)

    async def test_concurrent_rate_limit_is_atomic(self):
        async def request():
            try:await consume('race',3,60);return 200
            except Exception as error:return getattr(error,'status_code',500)
        results=await asyncio.gather(*[request() for _ in range(12)])
        self.assertEqual(results.count(200),3)
        self.assertEqual(results.count(429),9)
        self.assertEqual(await request(),429)

    async def test_role_change_cannot_complete_a_password_only_login(self):
        user=await services.users.get('admin')
        async with engine.begin() as connection:
            await connection.execute(update(db.users).where(db.users.c.username=='admin').values(role='user'))
        with self.assertRaises(ValueError):
            await services.users.create_session('admin',expected_password_hash=user['password_hash'],expected_role='admin')

    async def test_password_reset_blocks_activation_of_old_enrollment(self):
        user=await services.users.get('admin')
        setup=await mfa.enroll(user)
        await services.users.change_password('admin','A different isolated password')
        with self.assertRaises(Exception) as error:
            await mfa.confirm(user,pyotp.TOTP(setup['secret']).now())
        self.assertEqual(getattr(error.exception,'status_code',None),401)
        async with engine.connect() as connection:
            self.assertIsNone(await connection.scalar(select(db.user_mfa.c.secret)))

    async def test_security_events_are_redacted_and_queued(self):
        from app.repositories.postgres import audit
        await audit('admin','security.fixture',{'password':'never-persist-this','csrfToken':'never-persist-this'})
        async with engine.connect() as connection:
            row=(await connection.execute(select(db.soc_outbox.c.payload).where(
                db.soc_outbox.c.payload['event'].as_string()=='security.fixture'))).scalar_one()
            self.assertEqual(row['tenantId'],'soc-integration')
            self.assertNotIn('never-persist-this',str(row))

    async def test_oversized_json_is_rejected_before_endpoint_processing(self):
        response=await self.client.post('/api/auth/login',content=b'{' + b'x'*(8*1024*1024),
                                       headers={'Content-Type':'application/json'})
        self.assertEqual(response.status_code,413)
