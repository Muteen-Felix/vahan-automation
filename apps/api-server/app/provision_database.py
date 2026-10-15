"""Migrate with the owner account, then grant a separate DML-only runtime role."""
import asyncio
import os
import re
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import command
from alembic.config import Config
from pathlib import Path
from app.config import settings


async def grant_runtime_role():
    role = os.environ.get('DB_APP_USERNAME', 'vahan_app')
    password = os.environ.get('DB_APP_PASSWORD', '')
    if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]{0,62}', role) or role.startswith('pg_') or role == make_url(settings.database_url).username:
        raise RuntimeError('Use a distinct, valid PostgreSQL application role.')
    if len(password) < 24:
        raise RuntimeError('DB_APP_PASSWORD must contain at least 24 characters.')
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    try:
        async with engine.begin() as connection:
            exists = await connection.scalar(text('SELECT 1 FROM pg_roles WHERE rolname=:role'), {'role':role})
            verb = 'ALTER' if exists else 'CREATE'
            statement = await connection.scalar(text(
                f"SELECT format('{verb} ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L', CAST(:role AS text), CAST(:password AS text))"),
                {'role':role,'password':password})
            await connection.exec_driver_sql(statement)
            memberships = (await connection.execute(text('SELECT parent.rolname FROM pg_auth_members m JOIN pg_roles parent ON parent.oid=m.roleid JOIN pg_roles child ON child.oid=m.member WHERE child.rolname=:role'), {'role':role})).scalars().all()
            for parent in memberships:
                statement = await connection.scalar(text('SELECT format(\'REVOKE %I FROM %I\', CAST(:parent AS text), CAST(:role AS text))'), {'parent':parent,'role':role})
                await connection.exec_driver_sql(statement)
            owned = await connection.scalar(text("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_roles r ON r.oid=c.relowner WHERE n.nspname='public' AND r.rolname=:role"), {'role':role})
            if owned:
                raise RuntimeError('Runtime role owns schema objects; move ownership to the migration account first.')
            database = await connection.scalar(text('SELECT current_database()'))
            for sql in [
                'GRANT CONNECT ON DATABASE %I TO %I',
                'GRANT USAGE ON SCHEMA public TO %I',
                'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I',
                'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO %I',
                'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
                'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO %I',
            ]:
                arguments = {'sql':sql,'role':role,'database':database}
                fmt = 'SELECT format(CAST(:sql AS text), CAST(:database AS text), CAST(:role AS text))' if 'DATABASE' in sql else 'SELECT format(CAST(:sql AS text), CAST(:role AS text))'
                await connection.execute(text(await connection.scalar(text(fmt), arguments)))
            # Schema changes and migration bookkeeping stay with the owner.
            await connection.execute(text('REVOKE CREATE ON SCHEMA public FROM PUBLIC'))
            await connection.execute(text(f'REVOKE CREATE ON SCHEMA public FROM "{role}"'))
            await connection.execute(text(f'REVOKE ALL ON TABLE alembic_version FROM "{role}"'))
            await connection.execute(text(f'GRANT SELECT ON TABLE alembic_version TO "{role}"'))
    finally:
        await engine.dispose()


if __name__ == '__main__':
    try:
        command.upgrade(Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini')), 'head')
        asyncio.run(grant_runtime_role())
    except Exception:
        # DDL exceptions can contain the generated password statement.
        raise SystemExit('Database provisioning failed. Verify migration and runtime-role configuration; credentials were not logged.') from None
    print('Schema migrated and runtime role granted DML access.')
