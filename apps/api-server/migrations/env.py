import asyncio
from sqlalchemy import text
from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from app.config import settings
from app.db.schema import metadata

def configure(connection):
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()

async def online():
    engine = create_async_engine(settings.database_url, connect_args={
        'server_settings': {'application_name': 'vahan-migrate', 'lock_timeout': '5000'}})
    async with engine.connect() as connection:
        # Session lock survives the commits required by concurrent index builds.
        await connection.execute(text('SELECT pg_advisory_lock(748192603)'))
        await connection.commit()
        try:
            await connection.run_sync(configure)
        finally:
            await connection.rollback()
            await connection.execute(text('SELECT pg_advisory_unlock(748192603)'))
            await connection.commit()
    await engine.dispose()

if context.is_offline_mode():
    context.configure(url=settings.database_url, target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
