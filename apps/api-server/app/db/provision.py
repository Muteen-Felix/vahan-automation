"""Short-lived administrative bootstrap. Runtime containers receive only the DML credential."""
import asyncio, os, re
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from app.config import settings


def identifier(value):
    return '"'+value.replace('"','""')+'"'


async def provision():
    username=os.environ.get('DB_APP_USERNAME','vahan_app')
    password=os.environ.get('DB_APP_PASSWORD','')
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}',username) or username in {'vahan','postgres'}:
        raise RuntimeError('Use a separate lowercase runtime database role.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,}',password):
        raise RuntimeError('Generate DB_APP_PASSWORD using scripts/setup-docker.py.')
    admin=create_async_engine(settings.database_url,poolclass=NullPool)
    try:
        async with admin.begin() as c:
            await c.execute(text('SELECT pg_advisory_xact_lock(748192604)'))
            owner,database=(await c.execute(text('SELECT current_user,current_database()'))).one()
            if username==owner:raise RuntimeError('Runtime role must differ from migration owner.')
            exists=await c.scalar(text('SELECT 1 FROM pg_roles WHERE rolname=:name'),{'name':username})
            memberships=list(await c.scalars(text('SELECT parent.rolname FROM pg_auth_members m JOIN pg_roles parent ON parent.oid=m.roleid JOIN pg_roles child ON child.oid=m.member WHERE child.rolname=:name'),{'name':username}))
            role=identifier(username)
            for parent in memberships:await c.execute(text(f'REVOKE {identifier(parent)} FROM {role}'))
            if not exists:await c.execute(text(f'CREATE ROLE {role} LOGIN'))
            # URL-safe credentials contain no SQL quote characters. Do not log this statement.
            await c.execute(text(f"ALTER ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '{password}'"))
            for sql in [
                f'GRANT CONNECT ON DATABASE {identifier(database)} TO {role}',
                'REVOKE CREATE ON SCHEMA public FROM PUBLIC',
                f'REVOKE CREATE ON SCHEMA public FROM {role}',
                f'GRANT USAGE ON SCHEMA public TO {role}',
                f'GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {role}',
                f'GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}',
                f'ALTER DEFAULT PRIVILEGES FOR ROLE {identifier(owner)} IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO {role}',
                f'ALTER DEFAULT PRIVILEGES FOR ROLE {identifier(owner)} IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO {role}',
            ]:await c.execute(text(sql))
            if await c.scalar(text("SELECT to_regclass('public.alembic_version')")):
                await c.execute(text(f'REVOKE INSERT,UPDATE,DELETE ON alembic_version FROM {role}'))
    except Exception:
        # Administrative SQL may contain a credential, so hide exception context/parameters.
        raise RuntimeError('Runtime database role provisioning failed; inspect protected PostgreSQL logs.') from None
    finally:await admin.dispose()


if __name__=='__main__':
    asyncio.run(provision())
    print('Runtime database role ready (DML only).')
