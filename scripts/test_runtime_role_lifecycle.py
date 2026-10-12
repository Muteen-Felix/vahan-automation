#!/usr/bin/env python3
"""Prove a production API starts as a DML-only role on fresh and upgraded DBs."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
API = Path(os.environ.get("API_SERVER_ROOT", str(ROOT / "apps" / "api-server")))
HEAD = "head"
OLD_REVISION = "0012"


def run(args: list[str], *, cwd: Path, env: dict[str, str], secrets_to_redact: list[str], label: str) -> None:
    result = subprocess.run(args, cwd=cwd, env=env, text=True, encoding="utf-8",
        errors="replace", capture_output=True, timeout=180)
    if result.returncode:
        output = (result.stdout or "") + (result.stderr or "")
        for secret in secrets_to_redact:
            if secret:
                output = output.replace(secret, "[redacted]")
        raise RuntimeError(f"{label} failed:\n{output[-5000:]}")


def runtime_probe(mode: str, role: str, sentinel: str) -> str:
    return f'''import asyncio
from app.db import engine
from app.main import fastapi_app, lifespan
from sqlalchemy import text
async def main():
    async with lifespan(fastapi_app):
        async with engine.connect() as connection:
            row = (await connection.execute(text("""SELECT current_user, r.rolsuper, r.rolcreatedb,
              r.rolcreaterole, r.rolreplication, r.rolbypassrls,
              has_schema_privilege(current_user,'public','CREATE') AS schema_create,
              has_table_privilege(current_user,'app_settings','UPDATE') AS settings_update,
              EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relowner=r.oid) AS owns_objects
              FROM pg_roles r WHERE r.rolname=current_user"""))).mappings().one()
            assert row['current_user'] == {role!r}
            assert not any(row[key] for key in ('rolsuper','rolcreatedb','rolcreaterole','rolreplication',
                'rolbypassrls','schema_create','owns_objects'))
            assert row['settings_update']
            if {mode!r} == 'upgrade':
                value = await connection.scalar(text("SELECT value FROM app_settings WHERE key=:key"),
                    {{'key':{sentinel!r}}})
                assert value == {{'preserved':'before-upgrade'}}
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text('CREATE TABLE public.__runtime_role_must_not_create (id integer)'))
            except Exception:
                await transaction.rollback()
            else:
                await transaction.rollback()
                raise AssertionError('restricted API role unexpectedly created a table')
    await engine.dispose()
asyncio.run(main())'''


async def main() -> None:
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("Set DATABASE_URL to a disposable PostgreSQL database owned by a migration account.")
    base_url = make_url(os.environ["DATABASE_URL"])
    owner_url = base_url.set(database="vahan").render_as_string(hide_password=False)
    admin_dsn = make_url(owner_url).set(drivername="postgresql").render_as_string(hide_password=False)
    connection = await asyncpg.connect(admin_dsn)
    token = uuid4().hex[:12]
    cases = [(f"vahan_sec_fresh_{token}", f"rtfresh_{token}", "fresh"),
        (f"vahan_sec_upgrade_{token}", f"rtupgrade_{token}", "upgrade")]
    created_databases: list[str] = []
    created_roles: list[str] = []
    try:
        for database, role, mode in cases:
            password = secrets.token_urlsafe(36)
            runtime_url = base_url.set(database=database, username=role, password=password).render_as_string(hide_password=False)
            await connection.execute(f'CREATE DATABASE "{database}"')
            created_databases.append(database)
            if mode == "upgrade":
                migration_env = {**os.environ, "DATABASE_URL": base_url.set(database=database).render_as_string(hide_password=False)}
                run([sys.executable, "-c",
                    "from alembic import command; from alembic.config import Config; command.upgrade(Config('alembic.ini'), '0012')"],
                    cwd=API, env=migration_env, secrets_to_redact=[owner_url], label="Upgrade fixture to revision 0012")
                old_connection = await asyncpg.connect(make_url(migration_env["DATABASE_URL"])
                    .set(drivername="postgresql").render_as_string(hide_password=False))
                try:
                    await old_connection.execute("INSERT INTO app_settings(key,value) VALUES($1,$2::jsonb)",
                        f"security-upgrade-sentinel:{token}", json.dumps({"preserved":"before-upgrade"}))
                finally:
                    await old_connection.close()

            owner_env = {**os.environ,
                "DATABASE_URL": base_url.set(database=database).render_as_string(hide_password=False),
                "DB_APP_USERNAME": role, "DB_APP_PASSWORD": password}
            created_roles.append(role)
            run([sys.executable, "-m", "app.provision_database"], cwd=API, env=owner_env,
                secrets_to_redact=[password, owner_url], label=f"Provision {mode} schema and runtime role")

            key = f"security-upgrade-sentinel:{token}"
            runtime_env = {**os.environ, "DATABASE_URL": runtime_url,
                "DB_APP_USERNAME": role, "DB_APP_PASSWORD": password,
                "VAHAN_ENVIRONMENT": "production",
                "VAHAN_UI_AUTH_USERNAME": "security-test-admin",
                "VAHAN_UI_AUTH_PASSWORD": secrets.token_urlsafe(32),
                "VAHAN_UI_AUTH_TOKEN_SECRET": secrets.token_urlsafe(48),
                "VAHAN_API_RUNNER_TOKEN": secrets.token_urlsafe(36),
                "VAHAN_BROWSER_STATE_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
                "VAHAN_API_CORS_ORIGINS": "https://dashboard.example",
                "VAHAN_API_SOCKETIO_CORS_ORIGINS": "https://dashboard.example"}
            probe = runtime_probe(mode, role, key)
            run([sys.executable, "-c", probe], cwd=API, env=runtime_env,
                secrets_to_redact=[password, owner_url, runtime_url], label=f"Start production API on {mode} DB")
            print(f"Restricted-role API startup passed on {mode} database.")
    finally:
        for database in created_databases:
            await connection.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=$1", database)
            await connection.execute(f'DROP DATABASE IF EXISTS "{database}"')
        for role in created_roles:
            await connection.execute(f'DROP ROLE IF EXISTS "{role}"')
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
