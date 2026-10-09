from fastapi import APIRouter
from sqlalchemy import text
from app.db import engine

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready():
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1 FROM users LIMIT 1"))
    from app.redis_queue import queue_stream
    await queue_stream.client.ping()
    return {"status": "ok", "storage": "postgresql", "queue": "redis-streams"}


@router.get('/network/status')
async def network_status():
    from app.network_guard import status
    return await status()
