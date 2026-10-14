#!/usr/bin/env python3
"""T19i (S12, D-32): provision_database is idempotent, rotates the runtime password atomically, refuses unsafe
roles without logging the password, and a production API refuses a privileged database role.

Cases (a) fresh DB and (b) upgraded DB are covered by test_runtime_role_lifecycle.py; this file adds (c)-(f).
Needs DATABASE_URL pointing at a disposable PostgreSQL whose account can CREATE DATABASE and CREATE ROLE.
"""
from __future__ import annotations

import asyncio
import base64
import os
import secrets
import subprocess
import sys
import unittest
from pathlib import Path
from uuid import uuid4

import asyncpg
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
API = Path(os.environ.get("API_SERVER_ROOT", str(ROOT / "apps" / "api-server")))
PRODUCTION_START = """import asyncio
from app.main import fastapi_app, lifespan
async def main():
    async with lifespan(fastapi_app):
        pass
asyncio.run(main())
"""


def asyncpg_dsn(url, **changes) -> str:
    return url.set(drivername="postgresql", **changes).render_as_string(hide_password=False)


class ProvisionDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get("DATABASE_URL"):
            raise RuntimeError("Set DATABASE_URL to a disposable PostgreSQL database owned by a migration account.")
        cls.base = make_url(os.environ["DATABASE_URL"])

    def setUp(self):
        token = uuid4().hex[:12]
        self.database, self.role = f"vahan_prov_{token}", f"rtprov_{token}"
        self.password = secrets.token_urlsafe(36)
        self.admin_url = self.base.set(database="vahan")
        self.owner_url = self.base.set(database=self.database)
        asyncio.run(self.admin(f'CREATE DATABASE "{self.database}"'))
        self.addCleanup(self.drop)

    def drop(self):
        async def work():
            connection = await asyncpg.connect(asyncpg_dsn(self.admin_url))
            try:
                await connection.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=$1", self.database)
                await connection.execute(f'DROP DATABASE IF EXISTS "{self.database}"')
                await connection.execute(f'DROP ROLE IF EXISTS "{self.role}"')
            finally:
                await connection.close()
        asyncio.run(work())

    # ------------------------------------------------------------------ helpers
    async def admin(self, sql: str, *args):
        connection = await asyncpg.connect(asyncpg_dsn(self.admin_url))
        try:
            return await connection.execute(sql, *args)
        finally:
            await connection.close()

    def owner_sql(self, sql: str):
        async def work():
            connection = await asyncpg.connect(asyncpg_dsn(self.owner_url))
            try:
                return await connection.fetch(sql)
            finally:
                await connection.close()
        return asyncio.run(work())

    def provision(self, password: str | None = None, role: str | None = None) -> subprocess.CompletedProcess:
        env = {**os.environ, "DATABASE_URL": self.owner_url.render_as_string(hide_password=False),
               "DB_APP_USERNAME": role or self.role, "DB_APP_PASSWORD": self.password if password is None else password}
        return subprocess.run([sys.executable, "-m", "app.provision_database"], cwd=API, env=env, text=True,
                              encoding="utf-8", errors="replace", capture_output=True, timeout=240)

    def assertQuiet(self, result: subprocess.CompletedProcess, *secrets_: str):
        output = (result.stdout or "") + (result.stderr or "")
        for secret in secrets_:
            self.assertNotIn(secret, output, "a password reached stdout/stderr")

    def runtime_can_write(self, password: str) -> bool:
        async def work():
            try:
                connection = await asyncpg.connect(asyncpg_dsn(self.owner_url, username=self.role, password=password))
            except asyncpg.InvalidPasswordError:
                return False
            try:
                key = f"provision-test:{uuid4().hex}"
                await connection.execute("INSERT INTO app_settings(key,value) VALUES($1,'{}'::jsonb)", key)
                await connection.execute("DELETE FROM app_settings WHERE key=$1", key)
                return True
            finally:
                await connection.close()
        return asyncio.run(work())

    def role_exists(self) -> bool:
        return bool(asyncio.run(self._role_rows()))

    async def _role_rows(self):
        connection = await asyncpg.connect(asyncpg_dsn(self.admin_url))
        try:
            return await connection.fetch("SELECT 1 FROM pg_roles WHERE rolname=$1", self.role)
        finally:
            await connection.close()

    def start_production_api(self, url, role_password: str | None = None) -> subprocess.CompletedProcess:
        env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False), "VAHAN_ENVIRONMENT": "production",
               "DB_APP_USERNAME": self.role, "DB_APP_PASSWORD": role_password or self.password,
               "VAHAN_UI_AUTH_USERNAME": "provision-test-admin", "VAHAN_UI_AUTH_PASSWORD": secrets.token_urlsafe(32),
               "VAHAN_UI_AUTH_TOKEN_SECRET": secrets.token_urlsafe(48), "VAHAN_API_RUNNER_TOKEN": secrets.token_urlsafe(36),
               "VAHAN_BROWSER_STATE_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
               "VAHAN_API_CORS_ORIGINS": "https://dashboard.example",
               "VAHAN_API_SOCKETIO_CORS_ORIGINS": "https://dashboard.example"}
        return subprocess.run([sys.executable, "-c", PRODUCTION_START], cwd=API, env=env, text=True, encoding="utf-8",
                              errors="replace", capture_output=True, timeout=240)

    # ------------------------------------------------------------------ (c) idempotent + password rotation
    def test_c_second_run_is_idempotent_and_a_new_password_replaces_the_old_one(self):
        first = self.provision()
        self.assertEqual(first.returncode, 0, (first.stdout or "") + (first.stderr or ""))
        self.assertTrue(self.runtime_can_write(self.password))
        again = self.provision()
        self.assertEqual(again.returncode, 0, (again.stdout or "") + (again.stderr or ""))
        self.assertTrue(self.runtime_can_write(self.password))
        rotated = secrets.token_urlsafe(36)
        third = self.provision(password=rotated)
        self.assertEqual(third.returncode, 0, (third.stdout or "") + (third.stderr or ""))
        self.assertTrue(self.runtime_can_write(rotated), "new password must work")
        self.assertFalse(self.runtime_can_write(self.password), "old password must stop working")
        for result in (first, again, third):
            self.assertQuiet(result, self.password, rotated)

    # ------------------------------------------------------------------ (d) runtime role must not own objects
    def test_d_a_runtime_role_that_owns_schema_objects_is_refused_and_nothing_changes(self):
        self.assertEqual(self.provision().returncode, 0)
        self.owner_sql("CREATE TABLE public.owned_by_runtime_role (id integer)")
        self.owner_sql(f'ALTER TABLE public.owned_by_runtime_role OWNER TO "{self.role}"')
        attempted = secrets.token_urlsafe(36)
        refused = self.provision(password=attempted)
        self.assertNotEqual(refused.returncode, 0)
        self.assertQuiet(refused, self.password, attempted)
        self.assertIn("Database provisioning failed", (refused.stdout or "") + (refused.stderr or ""))
        # The failed run rolled back: the old password still works and the attempted one was never applied.
        self.assertTrue(self.runtime_can_write(self.password))
        self.assertFalse(self.runtime_can_write(attempted))

    # ------------------------------------------------------------------ (e) weak password / invalid role
    def test_e_short_or_missing_password_is_refused_before_any_role_is_created(self):
        for weak in ("x" * 23, ""):
            with self.subTest(length=len(weak)):
                refused = self.provision(password=weak)
                self.assertNotEqual(refused.returncode, 0)
                if weak:
                    self.assertQuiet(refused, weak)
                self.assertFalse(self.role_exists(), "no role may be created for a rejected password")
        accepted = self.provision(password="y" * 24)
        self.assertEqual(accepted.returncode, 0, (accepted.stdout or "") + (accepted.stderr or ""))

    def test_e_role_equal_to_the_migration_account_or_reserved_is_refused(self):
        owner = make_url(os.environ["DATABASE_URL"]).username
        for bad in (owner, "pg_monitor", "bad role;drop"):
            with self.subTest(role=bad):
                refused = self.provision(role=bad)
                self.assertNotEqual(refused.returncode, 0)
                self.assertQuiet(refused, self.password)

    # ------------------------------------------------------------------ (f) production API refuses a privileged role
    def test_f_production_api_starts_with_the_runtime_role_and_refuses_the_owner(self):
        self.assertEqual(self.provision().returncode, 0)
        runtime_url = self.owner_url.set(username=self.role, password=self.password)
        accepted = self.start_production_api(runtime_url)
        self.assertEqual(accepted.returncode, 0, "control: restricted role must start\n" + (accepted.stderr or "")[-1500:])
        refused = self.start_production_api(self.owner_url)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("restricted runtime database role", (refused.stdout or "") + (refused.stderr or ""))

    def test_f_production_api_refuses_a_runtime_role_that_gained_create_on_the_schema(self):
        self.assertEqual(self.provision().returncode, 0)
        self.owner_sql(f'GRANT CREATE ON SCHEMA public TO "{self.role}"')
        refused = self.start_production_api(self.owner_url.set(username=self.role, password=self.password))
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("restricted runtime database role", (refused.stdout or "") + (refused.stderr or ""))


if __name__ == "__main__":
    unittest.main()
