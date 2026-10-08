"""Authenticated controller for the durable State/RTO work queue."""
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.models.filters import VahanFilters
from app.repositories.batch_queue import BatchQueueRepository
from app.db import engine,schema as db
from sqlalchemy import select
from app.realtime.server import sio

router = APIRouter(prefix='/batch-queue', tags=['batch-queue'])
queue = BatchQueueRepository()


class QueueTaskInput(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    filters: VahanFilters


class StartQueueInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    session_id: UUID = Field(alias='sessionId')
    tasks: list[QueueTaskInput] = Field(min_length=1, max_length=3000)
    preflight_id: UUID | None = Field(default=None,alias='preflightId')
    max_workers: int = Field(default=10, alias='maxWorkers', ge=1, le=10, strict=True)


class ClaimInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    runner_id: str = Field(alias='runnerId', min_length=1, max_length=128)

class ResumeQueueInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    preflight_id: UUID | None = Field(default=None,alias='preflightId')
    max_workers: int | None = Field(default=None, alias='maxWorkers', ge=1, le=10, strict=True)


async def call(operation):
    try:
        return await operation
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.post('/sessions')
async def start_queue(command: StartQueueInput, request: Request):
    from app.repositories.ui_contract import require_gate,bind_gate
    ids=[f'playwright-{index+1}' for index in range(command.max_workers)]
    gate=await call(require_gate(request.state.authenticated_user,ids,command.preflight_id,fresh=True))
    await call(queue.start(command.session_id, request.state.authenticated_user, command.tasks, command.max_workers))
    await bind_gate(command.session_id,gate)
    return await call(queue.snapshot(command.session_id, request.state.authenticated_user))


@router.get('/sessions/{session_id}')
async def get_queue(session_id: UUID, request: Request):
    return await call(queue.snapshot(session_id, request.state.authenticated_user))


@router.post('/sessions/{session_id}/pause')
async def pause_queue(session_id: UUID, request: Request):
    await call(queue.set_status(session_id, request.state.authenticated_user, 'PAUSED'))
    return {'status': 'PAUSED'}


@router.post('/sessions/{session_id}/resume')
async def resume_queue(session_id: UUID, request: Request, command: ResumeQueueInput | None = None):
    from app.repositories.ui_contract import require_gate,bind_gate
    saved=await call(queue.snapshot(session_id,request.state.authenticated_user))
    count=command.max_workers if command and command.max_workers else saved['maxWorkers']
    gate=await call(require_gate(request.state.authenticated_user,[f'playwright-{i+1}' for i in range(count)],command.preflight_id if command else None,fresh=True))
    await bind_gate(session_id,gate)
    await call(queue.set_status(session_id, request.state.authenticated_user, 'RUNNING',
        command.max_workers if command else None))
    return {'status': 'RUNNING'}


@router.post('/sessions/{session_id}/tasks/{position}/settle')
async def settle_task(session_id: UUID, position: int, request: Request):
    return await call(queue.settle(session_id, request.state.authenticated_user, position))


@router.post('/sessions/{session_id}/claim')
async def claim_task(session_id: UUID, command: ClaimInput, request: Request):
    from app.repositories.ui_contract import require_gate
    # Final recovery can requeue formerly FAILED rows. It requires the same
    # SQL gate as primary/checkpoint work before creating another job.
    if await call(queue.needs_work(session_id,request.state.authenticated_user)):
        await call(require_gate(request.state.authenticated_user,[command.runner_id],session_id=session_id,bound=True))
    result = await call(queue.claim(session_id, request.state.authenticated_user, command.runner_id))
    job = result.pop('job', None)
    if result['type'] == 'assigned' and job is None:
        from app.services import services
        job = await services.jobs.get(UUID(result['jobId']))
    if job:
        await sio.emit('job:assigned', {
            'jobId': str(job.id), 'filters': job.filters.runner_payload(),
            'scenarioName': job.scenario_name, 'source': job.source.value,
        }, room=f'runner:{command.runner_id}', namespace='/runner')
    return result
