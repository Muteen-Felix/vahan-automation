from fastapi import APIRouter, HTTPException
from functools import lru_cache
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from app.db import engine

router = APIRouter(tags=["health"])


@lru_cache(maxsize=1)
def required_revision():
    return ScriptDirectory.from_config(Config(str(Path(__file__).resolve().parents[2] / 'alembic.ini'))).get_current_head()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready():
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1 FROM users LIMIT 1"))
            revisions = set((await connection.execute(text('SELECT version_num FROM alembic_version'))).scalars())
        if revisions != {required_revision()}:
            raise HTTPException(503, 'Database migration is not at the required revision.')
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(503, 'Database readiness could not be verified.') from error
    return {"status": "ok", "storage": "postgresql", "queue": "postgresql"}


@router.get('/network/status')
async def network_status():
    from app.network_guard import status
    return await status()
