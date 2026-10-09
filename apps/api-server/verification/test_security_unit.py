"""Security boundaries without production credentials or live database access."""
from dataclasses import replace
import json
import time
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.config import Settings
from app import security, mfa, audit_log
from app.main import require_ui_authentication

BASE = Settings(ui_auth_token_secret='isolated-security-test-' + 'x'*48,
                tenant_id='tenant-a', runner_tokens=json.dumps({
                    'playwright-1': 'worker-one-' + 'a'*40,
                    'playwright-2': 'worker-two-' + 'b'*40}))


class TokenBoundaryTests(unittest.TestCase):
    def test_same_signing_key_still_rejects_another_tenant(self):
        with patch.object(security, 'settings', BASE):
            token = security.issue_access_token('admin', 'session')
            self.assertEqual(security.verify_access_token(token), 'admin')
        with patch.object(security, 'settings', replace(BASE, tenant_id='tenant-b')):
            self.assertIsNone(security.verify_access_token(token))

    def test_unique_worker_identity_and_retired_shared_secret(self):
        settings = replace(BASE, production=True, runner_token='old-shared-' + 'z'*40)
        with patch.object(security, 'settings', settings):
            self.assertTrue(security.runner_token_matches('worker-one-'+'a'*40, 'playwright-1'))
            self.assertFalse(security.runner_token_matches('worker-one-'+'a'*40, 'playwright-2'))
            self.assertFalse(security.runner_token_matches(settings.runner_token, 'playwright-1'))
            self.assertFalse(security.runner_token_matches('worker-one-'+'a'*40))

    def test_expired_or_tampered_token_is_rejected(self):
        with patch.object(security, 'settings', BASE):
            token = security.issue_access_token('admin', 'session', expires_at=int(time.time())-1)
            self.assertIsNone(security.verify_access_token(token))
            token = security.issue_access_token('admin', 'session')
            self.assertIsNone(security.verify_access_token(token+'tampered'))

    def test_sensitive_fields_and_bearer_are_redacted(self):
        value = audit_log.redact({'password':'private','csrfToken':'private','mfaSetupToken':'private',
                            'nested':{'recoveryCodes':['private']},'message':'Bearer private-token'})
        self.assertNotIn('private', json.dumps(value))


class HttpBoundaryTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.middleware('http')(require_ui_authentication)
        for path in ['/api/test', '/api/runner-state/playwright-2', f'/api/jobs/{uuid4()}/main-report']:
            app.add_api_route(path, lambda: {'ok':True}, methods=['GET','POST','PUT'])
        self.app = app

    def test_cookie_mutations_require_csrf_and_trusted_origin(self):
        from app.config import settings
        user={'username':'admin','role':'admin','session_id':'fixture-session'}
        with patch('app.main.authenticate_access_token', AsyncMock(return_value=user)):
            client=TestClient(self.app)
            client.cookies.set(settings.session_cookie_name, 'cookie-fixture')
            self.assertEqual(client.post('/api/test').status_code,403)
            headers={'X-CSRF-Token':security.csrf_token('fixture-session')}
            self.assertEqual(client.post('/api/test',headers=headers).status_code,200)
            self.assertEqual(client.post('/api/test',headers={**headers,'Origin':'https://evil.invalid'}).status_code,403)

    def test_worker_cannot_claim_another_identity_or_state_path(self):
        with patch('app.main.settings',BASE), patch.object(security,'settings',BASE):
            client=TestClient(self.app)
            headers={'X-VAHAN-RUNNER-TOKEN':'worker-one-'+'a'*40,'X-VAHAN-RUNNER-ID':'playwright-2'}
            self.assertEqual(client.get('/api/runner-state/playwright-2',headers=headers).status_code,401)
            headers['X-VAHAN-RUNNER-ID']='playwright-1'
            self.assertEqual(client.get('/api/runner-state/playwright-2',headers=headers).status_code,403)

    def test_explicit_bad_bearer_cannot_fall_back_to_valid_cookie(self):
        from app.config import settings
        authentication=AsyncMock(return_value=None)
        with patch('app.main.authenticate_access_token',authentication):
            client=TestClient(self.app);client.cookies.set(settings.session_cookie_name,'valid-cookie')
            self.assertEqual(client.get('/api/test',headers={'Authorization':'Bearer invalid'}).status_code,401)
            authentication.assert_awaited_with('invalid')


class EnrollmentBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_challenge_cannot_be_replayed_in_another_tenant(self):
        user={'username':'admin','role':'admin','active':True,'password_hash':'fixture-hash'}
        with patch.object(mfa,'settings',BASE):token=mfa.setup_challenge(user)
        with patch.object(mfa,'settings',replace(BASE,tenant_id='tenant-b')):
            with self.assertRaises(HTTPException) as error:await mfa.setup_user(token)
            self.assertEqual(error.exception.status_code,401)

    async def test_password_change_invalidates_pending_enrollment(self):
        user={'username':'admin','role':'admin','active':True,'password_hash':'old-hash'}
        with patch.object(mfa,'settings',BASE):
            token=mfa.setup_challenge(user)
            with patch('app.services.services.users.get',AsyncMock(return_value={**user,'password_hash':'new-hash'})):
                with self.assertRaises(HTTPException):await mfa.setup_user(token)
