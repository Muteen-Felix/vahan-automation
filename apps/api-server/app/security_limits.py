"""Atomic database-backed limits survive restarts and concurrent requests."""
from datetime import timedelta
import hashlib
import hmac
from sqlalchemy import case, delete
from sqlalchemy.dialects.postgresql import insert
from fastapi import HTTPException
from app.config import settings
from app.db import engine, schema as db
from app.repositories.postgres import now


async def consume(name: str, limit: int, seconds: int):
    key = hmac.new(settings.ui_auth_token_secret.encode(),
                   f'{settings.tenant_id}:{name}'.encode(), hashlib.sha256).hexdigest()
    started = now()
    cutoff = started - timedelta(seconds=seconds)
    table = db.security_rate_limits
    expired = table.c.started_at <= cutoff
    statement = insert(table).values(key=key, started_at=started, hits=1)
    statement = statement.on_conflict_do_update(index_elements=[table.c.key], set_={
        'started_at': case((expired, started), else_=table.c.started_at),
        'hits': case((expired, 1), else_=table.c.hits + 1),
    }).returning(table.c.hits, table.c.started_at)
    async with engine.begin() as connection:
        row = (await connection.execute(statement)).one()
        # Retention is independent of application audit retention.
        await connection.execute(delete(table).where(table.c.started_at < started - timedelta(days=1)))
    if row.hits > limit:
        retry = max(1, seconds - int((started - row.started_at).total_seconds()))
        raise HTTPException(429, 'Too many requests. Please try again later.',
                            headers={'Retry-After': str(retry)})
