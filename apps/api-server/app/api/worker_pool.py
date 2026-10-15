from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.worker_pool import apply_pool, pool_status, PoolError

router = APIRouter(prefix='/worker-pool', tags=['worker-pool'])

class WorkerCount(BaseModel):
    count: int = Field(ge=1, strict=True)

@router.get('')
async def get_worker_pool():
    try: return await pool_status()
    except PoolError as error: raise HTTPException(503, str(error)) from error

@router.put('')
async def set_worker_pool(command: WorkerCount):
    try: return await apply_pool(command.count)
    except PoolError as error: raise HTTPException(409, str(error)) from error
