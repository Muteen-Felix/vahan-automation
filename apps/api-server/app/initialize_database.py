"""One-shot administrative setup; runtime never receives administrative keys."""
import asyncio
import os
import subprocess
import sys
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from app.config import settings

ROLES = {'vahan_app': 'VAHAN_DB_RUNTIME_PASSWORD',
         'vahan_migrator': 'VAHAN_DB_MIGRATION_PASSWORD',
         'vahan_backup': 'VAHAN_DB_BACKUP_PASSWORD'}


async def configure(before):
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    try:
        async with engine.begin() as connection:
            if before:
                identity_exists = await connection.scalar(text("SELECT to_regclass('public.deployment_identity')"))
                if identity_exists:
                    existing_tenant = await connection.scalar(text('SELECT tenant_id FROM deployment_identity WHERE id=1'))
                    if existing_tenant and existing_tenant != settings.tenant_id:
                        raise RuntimeError('Database tenant mismatch; no administrative changes allowed.')
                for role, key in ROLES.items():
                    password = os.environ.get(key, '')
                    if len(password) < 32:
                        raise RuntimeError('Configure independent database role passwords.')
                    exists = await connection.scalar(text('SELECT 1 FROM pg_roles WHERE rolname=:name'), {'name':role})
                    query = await connection.scalar(text('SELECT format(CAST(:template AS text), CAST(:password AS text))'),
                        {'template':f"{'ALTER' if exists else 'CREATE'} ROLE {role} "
                         'LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT NOBYPASSRLS PASSWORD %L', 'password':password})
                    await connection.execute(text(query))
                    parents=await connection.scalars(text('SELECT parent.rolname FROM pg_auth_members m '
                        'JOIN pg_roles parent ON parent.oid=m.roleid JOIN pg_roles child ON child.oid=m.member '
                        'WHERE child.rolname=:name'),{'name':role})
                    for parent in parents:
                        quoted='"'+parent.replace('"','""')+'"'
                        await connection.execute(text(f'REVOKE {quoted} FROM {role}'))
                await connection.execute(text('ALTER DATABASE vahan OWNER TO vahan_migrator'))
                await connection.execute(text('ALTER SCHEMA public OWNER TO vahan_migrator'))
                rows = (await connection.execute(text("SELECT relname, relkind FROM pg_class c JOIN pg_namespace n "
                    "ON n.oid=c.relnamespace WHERE n.nspname='public' AND relkind IN ('r','p','S','v','m')"))).all()
                for name, kind in rows:
                    identifier = '"' + name.replace('"','""') + '"'
                    operation = {'S':'SEQUENCE','v':'VIEW','m':'MATERIALIZED VIEW'}.get(kind, 'TABLE')
                    await connection.execute(text(f'ALTER {operation} public.{identifier} OWNER TO vahan_migrator'))
            else:
                tenant = await connection.scalar(text('SELECT tenant_id FROM deployment_identity WHERE id=1'))
                if tenant and tenant != settings.tenant_id:
                    raise RuntimeError('Database tenant mismatch.')
                if not tenant:
                    await connection.execute(text('INSERT INTO deployment_identity(id,tenant_id) VALUES(1,:tenant)'),
                                             {'tenant':settings.tenant_id})
                await connection.execute(text('REVOKE CREATE ON SCHEMA public FROM PUBLIC'))
                await connection.execute(text('REVOKE CONNECT ON DATABASE vahan FROM PUBLIC'))
                for role in ROLES:
                    await connection.execute(text(f'GRANT CONNECT ON DATABASE vahan TO {role}'))
                    await connection.execute(text(f'GRANT USAGE ON SCHEMA public TO {role}'))
                await connection.execute(text('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO vahan_app'))
                await connection.execute(text('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO vahan_app'))
                await connection.execute(text('GRANT SELECT ON ALL TABLES IN SCHEMA public TO vahan_backup'))
                await connection.execute(text('GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO vahan_backup'))
                await connection.execute(text('REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM vahan_app'))
                await connection.execute(text('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON alembic_version FROM vahan_app'))
                await connection.execute(text('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON deployment_identity FROM vahan_app'))
                # Bootstrap is a migration operation. The long-running API
                # receives neither this password nor administrative DB keys.
                from app.db import schema as db
                from app.repositories.postgres import hash_password, now
                from sqlalchemy.dialects.postgresql import insert
                if settings.ui_auth_username and len(settings.ui_auth_password) >= 12:
                    await connection.execute(insert(db.users).values(username=settings.ui_auth_username,
                        password_hash=hash_password(settings.ui_auth_password), role='admin', active=True,
                        profile={}, created_at=now()).on_conflict_do_nothing())
    finally:
        await engine.dispose()


def main():
    try:
        asyncio.run(configure(True))
        environment = dict(os.environ)
        environment['DATABASE_URL'] = make_url(settings.database_url).set(
            username='vahan_migrator', password=os.environ['VAHAN_DB_MIGRATION_PASSWORD']).render_as_string(hide_password=False)
        subprocess.run([sys.executable, '-m', 'app.migrate'], env=environment, check=True)
        asyncio.run(configure(False))
        print('Database migration and least-privilege roles configured.')
    except Exception:
        # SQL statements can contain role secrets. Never print the raw error.
        raise SystemExit('Database security setup failed. Check protected server diagnostics and configuration.') from None


if __name__ == '__main__':
    main()
