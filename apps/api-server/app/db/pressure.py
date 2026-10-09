"""Bound heavy operations and classify recoverable DB pressure without retrying writes."""
import asyncio
from contextlib import asynccontextmanager
from functools import wraps
from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeout
from app.config import settings


class DatabaseBusy(RuntimeError):
    pass


_bulk_slots = asyncio.Semaphore(settings.bulk_operation_concurrency)


@asynccontextmanager
async def bulk_operation():
    try:
        await asyncio.wait_for(_bulk_slots.acquire(), timeout=2)
    except TimeoutError as error:
        raise DatabaseBusy('Report processing is busy. Retry shortly.') from error
    try:
        yield
    finally:
        _bulk_slots.release()


def bounded_bulk(operation):
    @wraps(operation)
    async def run(*args, **kwargs):
        async with bulk_operation():
            return await operation(*args, **kwargs)
    return run


def pressure_code(error):
    if isinstance(error, DatabaseBusy):
        return 'REPORT_PROCESSING_BUSY'
    if isinstance(error, (PoolTimeout, TimeoutError)):
        return 'DATABASE_BUSY'
    if isinstance(error, DBAPIError):
        original = error.orig
        code = getattr(original, 'sqlstate', None) or getattr(original, 'pgcode', None)
        if error.connection_invalidated or (code and (code.startswith('08') or code in {
            '40001', '40P01', '53300', '55P03', '57014', '57P01', '57P02', '57P03',
        })):
            return 'DATABASE_TEMPORARILY_UNAVAILABLE'
    return None
