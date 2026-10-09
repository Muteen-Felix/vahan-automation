"""Atomic database-backed limits survive restarts and concurrent requests."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import hmac
from sqlalchemy import case, delete, update
from sqlalchemy.dialects.postgresql import insert
from fastapi import HTTPException
from app.config import settings
from app.db import engine, schema as db
from app.repositories.postgres import now


@dataclass(frozen=True)
class Reservation:
    key: str
    started_at: datetime


async def consume(name: str, limit: int, seconds: int) -> Reservation:
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
    return Reservation(key=key, started_at=row.started_at)


async def refund(reservation: Reservation) -> None:
    """Release an accepted attempt without changing a newer rate-limit window."""
    table = db.security_rate_limits
    window = (table.c.key == reservation.key) & (table.c.started_at == reservation.started_at)
    async with engine.begin() as connection:
        await connection.execute(update(table).where(window, table.c.hits > 0)
                                 .values(hits=table.c.hits - 1))
        await connection.execute(delete(table).where(window, table.c.hits == 0))
