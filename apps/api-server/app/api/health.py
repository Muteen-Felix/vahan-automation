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
    return {"status": "ok", "storage": "postgresql"}
