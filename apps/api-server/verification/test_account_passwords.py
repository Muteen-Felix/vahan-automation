"""Password changes on a guarded disposable database, never real user accounts."""
import os,sys,asyncio,unittest
from pathlib import Path
from sqlalchemy.engine import make_url
name=os.environ.get('VAHAN_ACCOUNT_TEST_DATABASE','')
if not name.startswith('vahan_account_') or not name.endswith('_test'):
    raise RuntimeError('Use a disposable vahan_account_*_test database.')
os.environ['DATABASE_URL']=make_url(os.environ['DATABASE_URL']).set(database=name).render_as_string(hide_password=False)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from unittest.mock import AsyncMock,patch
from starlette.requests import Request
from fastapi import HTTPException
from pydantic import ValidationError
from app.db import engine,schema as db
from app.services import services
from app.api.auth import ChangePasswordRequest,change_password
from app.api.data import ResetPasswordRequest,reset_password

class PasswordTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        async with engine.begin() as c:
            await c.run_sync(db.metadata.drop_all);await c.run_sync(db.metadata.create_all)
        await services.users.create('admin','Initial admin password','admin')
        await services.users.create('member','Initial member password')
        self.current=await services.users.create_session('member')
        self.other=await services.users.create_session('member')
        self.admin_session=await services.users.create_session('admin')
        self.invalidate=patch('app.realtime.ui_events.invalidate_user',AsyncMock());self.invalidated=self.invalidate.start()
    async def asyncTearDown(self):
        self.invalidate.stop();await engine.dispose()
    def request(self,user='member',role='user'):
        r=Request({'type':'http'});r.state.authenticated_user=user;r.state.authenticated_role=role
        r.state.token_session=self.current if user=='member' else self.admin_session;return r
    async def test_own_change_replaces_hash_keeps_current_session_and_revokes_others(self):
        result=await change_password(ChangePasswordRequest(currentPassword='Initial member password',newPassword='Replacement member password'),self.request())
        self.assertTrue(result['ok']);self.assertFalse(await services.users.authenticate('member','Initial member password'))
        self.assertTrue(await services.users.authenticate('member','Replacement member password'))
        self.assertIsNotNone(await services.users.session_user('member',self.current))
        self.assertIsNone(await services.users.session_user('member',self.other))
        self.invalidated.assert_awaited_once_with('member',except_session=self.current)
    async def test_login_verified_before_reset_cannot_create_a_session_after_reset(self):
        user=await services.users.authenticate('member','Initial member password')
        await services.users.change_password('member','Admin reset replacement')
        with self.assertRaises(ValueError):
            await services.users.create_session('member',expected_password_hash=user['password_hash'])
        user=await services.users.authenticate('member','Admin reset replacement')
        session=await services.users.create_session('member',expected_password_hash=user['password_hash'])
        self.assertIsNotNone(await services.users.session_user('member',session))
    async def test_wrong_current_password_cannot_change_or_revoke(self):
        with self.assertRaises(HTTPException) as ctx:
            await change_password(ChangePasswordRequest(currentPassword='wrong',newPassword='Replacement member password'),self.request())
        self.assertEqual(ctx.exception.status_code,409)
        self.assertTrue(await services.users.authenticate('member','Initial member password'))
        self.assertIsNotNone(await services.users.session_user('member',self.other))
    async def test_admin_reset_revokes_target_sessions_but_keeps_admin(self):
        await reset_password('member',ResetPasswordRequest(password='Admin reset replacement'),self.request('admin','admin'))
        self.assertTrue(await services.users.authenticate('member','Admin reset replacement'))
        self.assertIsNone(await services.users.session_user('member',self.current))
        self.assertIsNone(await services.users.session_user('member',self.other))
        self.assertIsNotNone(await services.users.session_user('admin',self.admin_session))
    async def test_member_cannot_reset_another_user(self):
        with self.assertRaises(HTTPException) as ctx:
            await reset_password('admin',ResetPasswordRequest(password='Unauthorized replacement'),self.request())
        self.assertEqual(ctx.exception.status_code,403)
        self.assertTrue(await services.users.authenticate('admin','Initial admin password'))
    async def test_admin_own_reset_requires_current_password_flow(self):
        with self.assertRaises(HTTPException) as ctx:
            await reset_password('admin',ResetPasswordRequest(password='Replacement admin password'),self.request('admin','admin'))
        self.assertEqual(ctx.exception.status_code,409)
    async def test_unknown_user_and_password_validation(self):
        with self.assertRaises(HTTPException) as ctx:
            await reset_password('missing',ResetPasswordRequest(password='Replacement long password'),self.request('admin','admin'))
        self.assertEqual(ctx.exception.status_code,404)
        with self.assertRaises(ValidationError):ResetPasswordRequest(password='short')
        with self.assertRaises(HTTPException):
            await change_password(ChangePasswordRequest(currentPassword='Initial member password',newPassword='Initial member password'),self.request())

if __name__=='__main__':unittest.main(verbosity=2)
