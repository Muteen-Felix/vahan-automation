import asyncio
from fastapi import APIRouter, Request
from sqlalchemy import text
from app.db import engine

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready():
    async with asyncio.timeout(3):
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1 FROM users LIMIT 1"))
    return {"status": "ok", "storage": "postgresql"}


@router.get('/database/status')
async def database_status(request: Request):
    from app.access import require_admin
    require_admin(request)
    async with engine.connect() as connection:
        tables = [dict(row) for row in (await connection.execute(text('''
            SELECT relname AS name, n_live_tup AS estimated_rows, n_dead_tup AS dead_rows,
                   pg_total_relation_size(relid) AS bytes, last_autovacuum, last_autoanalyze
            FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 25
        '''))).mappings()]
        activity = dict((await connection.execute(text('''SELECT
            count(*) AS connections,
            count(*) FILTER (WHERE state='active') AS active,
            count(*) FILTER (WHERE wait_event_type='Lock') AS waiting_for_lock,
            count(*) FILTER (WHERE state='idle in transaction') AS idle_transactions
            FROM pg_stat_activity WHERE datname=current_database()'''))).mappings().one())
        size = await connection.scalar(text('SELECT pg_database_size(current_database())'))
    from app.db.read_cache import cache_status
    pool = engine.pool
    return {'storage':'postgresql','bytes':size,'readCache':cache_status(),'activity':activity,'tables':tables,
            'pool':{'size':pool.size(),'checkedOut':pool.checkedout(),'overflow':max(0,pool.overflow())}}


@router.get('/network/status')
async def network_status():
    from app.network_guard import status
    return await status()
