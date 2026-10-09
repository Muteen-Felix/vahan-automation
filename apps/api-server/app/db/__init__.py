from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.config import settings

engine = create_async_engine(
    settings.database_url,
    hide_parameters=True,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout_seconds,
    pool_recycle=1800,
    pool_use_lifo=True,
    connect_args={
        'timeout': 10,
        'command_timeout': settings.db_statement_timeout_ms / 1000 + 5,
        'server_settings': {
            'application_name': 'vahan-api',
            'statement_timeout': str(settings.db_statement_timeout_ms),
            'lock_timeout': str(settings.db_lock_timeout_ms),
            'idle_in_transaction_session_timeout': str(settings.db_idle_transaction_timeout_ms),
        },
    },
)
sessions = async_sessionmaker(engine, expire_on_commit=False)
