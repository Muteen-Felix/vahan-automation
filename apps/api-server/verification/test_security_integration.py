"""MFA, replay, cookies, rate limits and local audit on a disposable database."""
import asyncio
import base64
from dataclasses import replace
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4
from unittest.mock import patch

from sqlalchemy.engine import make_url
name=make_url(os.environ.get('DATABASE_URL','postgresql://localhost/')).database or ''
if not name.endswith('_security_test'):
    raise RuntimeError('Use a dedicated disposable *_security_test database.')
os.environ['VAHAN_REQUIRE_ADMIN_MFA']='true'
os.environ['VAHAN_MFA_ENCRYPTION_KEY']=base64.urlsafe_b64encode(os.urandom(32)).decode()
os.environ['VAHAN_TENANT_ID']='security-integration'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import pyotp
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func, update
from app.db import engine, schema as db
from app.main import fastapi_app
from app.config import settings
from app.services import services
from app import mfa
from app.api import auth as auth_api
from app.security_limits import consume, refund
from app.security import issue_access_token


class SecurityTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_valid_password_mfa_setup_does_not_exhaust_account_limit(self):
        for _ in range(8):
            response=await self.client.post('/api/auth/login',json={'username':'admin','password':'Isolated test password'})
            self.assertEqual(response.status_code,200)
            self.assertIn('mfaSetupToken',response.json())

    async def test_successful_password_logins_do_not_exhaust_account_limit(self):
        await services.users.create('member','Isolated member password',role='user')
        for _ in range(8):
            response=await self.client.post('/api/auth/login',json={'username':'member','password':'Isolated member password'})
            self.assertEqual(response.status_code,200)
            self.assertEqual((await self.client.get('/api/auth/me')).status_code,200)

    async def test_password_only_admin_login_when_mfa_is_disabled(self):
        with patch.object(auth_api,'settings',replace(settings,require_admin_mfa=False)):
            response=await self.client.post('/api/auth/login',json={'username':'admin','password':'Isolated test password','browserSession':True})
        self.assertEqual(response.status_code,200)
        self.assertNotIn('mfaSetupToken',response.json())
        self.assertEqual(response.json()['tokenType'],'Cookie')
        self.assertEqual((await self.client.get('/api/auth/me')).status_code,200)

    async def test_existing_mfa_does_not_block_password_login_when_disabled(self):
        await self.enroll()
        self.client.cookies.clear()
        with patch.object(auth_api,'settings',replace(settings,require_admin_mfa=False)):
            response=await self.client.post('/api/auth/login',json={'username':'admin','password':'Isolated test password','browserSession':True})
        self.assertEqual(response.status_code,200)
        self.assertNotIn('mfaSetupToken',response.json())
        self.assertEqual((await self.client.get('/api/auth/me')).status_code,200)

    async def test_incorrect_passwords_still_lock_the_account(self):
        for _ in range(5):
            response=await self.client.post('/api/auth/login',json={'username':'admin','password':'Wrong password'})
            self.assertEqual(response.status_code,401)
        response=await self.client.post('/api/auth/login',json={'username':'admin','password':'Isolated test password'})
        self.assertEqual(response.status_code,429)
        self.assertGreater(int(response.headers['Retry-After']),0)

    async def test_missing_mfa_code_is_a_step_but_wrong_codes_are_limited(self):
        await self.enroll()
        for _ in range(6):
            response=await self.client.post('/api/auth/login',json={'username':'admin','password':'Isolated test password'})
            self.assertEqual(response.status_code,401)
            self.assertIn('verification code',response.json()['detail'])
        for _ in range(5):
            response=await self.client.post('/api/auth/login',json={'username':'admin','password':'Isolated test password','otp':'bad-code'})
            self.assertEqual(response.status_code,401)
        response=await self.client.post('/api/auth/login',json={'username':'admin','password':'Isolated test password','otp':'bad-code'})
        self.assertEqual(response.status_code,429)

    async def test_old_reservation_refund_does_not_change_new_window(self):
        from datetime import timedelta
        from app import security_limits
        started=security_limits.now()
        with patch.object(security_limits,'now',return_value=started):
            old=await consume('new-window',3,60)
        with patch.object(security_limits,'now',return_value=started+timedelta(seconds=61)):
            current=await consume('new-window',3,60)
        await refund(old)
        async with engine.connect() as connection:
            self.assertEqual(await connection.scalar(select(db.security_rate_limits.c.hits).where(db.security_rate_limits.c.key==current.key)),1)

    async def test_concurrent_refunds_do_not_leave_negative_counts(self):
        reservations=await asyncio.gather(*[consume('refund-race',12,60) for _ in range(12)])
        await asyncio.gather(*[refund(reservation) for reservation in reservations])
        async with engine.connect() as connection:
            self.assertEqual(await connection.scalar(select(func.count()).select_from(db.security_rate_limits)
                .where(db.security_rate_limits.c.key==reservations[0].key)),0)

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

    async def test_local_audit_events_are_redacted_and_persisted(self):
        from app.repositories.postgres import audit
        await audit('admin','security.fixture',{'password':'never-persist-this','csrfToken':'never-persist-this'})
        async with engine.connect() as connection:
            row=(await connection.execute(select(db.audit_events.c.payload).where(
                db.audit_events.c.event=='security.fixture'))).scalar_one()
            self.assertEqual(row['tenantId'],'security-integration')
            self.assertNotIn('never-persist-this',str(row))

    async def test_oversized_json_is_rejected_before_endpoint_processing(self):
        response=await self.client.post('/api/auth/login',content=b'{' + b'x'*(8*1024*1024),
                                       headers={'Content-Type':'application/json'})
        self.assertEqual(response.status_code,413)
