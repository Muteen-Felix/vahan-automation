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
worker_router = APIRouter(prefix='/runner', tags=['runner-queue'])
queue = BatchQueueRepository()


class QueueTaskInput(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    filters: VahanFilters


class StartQueueInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    session_id: UUID = Field(alias='sessionId')
    tasks: list[QueueTaskInput] = Field(min_length=1, max_length=3000)
    preflight_id: UUID | None = Field(default=None,alias='preflightId')
    max_workers: int = Field(default=1, alias='maxWorkers', ge=1, strict=True)


class ResumeQueueInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    preflight_id: UUID | None = Field(default=None,alias='preflightId')
    max_workers: int | None = Field(default=None, alias='maxWorkers', ge=1, strict=True)


class ClaimInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    runner_id: str = Field(alias='runnerId', min_length=1, max_length=128)


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
    from app.services import services
    from app.worker_pool import apply_pool, PoolError
    ids=[runner.id for runner in await services.runners.list()
        if runner.source.value == 'new' and runner.status.value == 'ONLINE' and not runner.current_job_id]
    if not ids:
        raise HTTPException(409, 'Start at least one browser worker before starting the queue.')
    gate=await call(require_gate(request.state.authenticated_user,ids,command.preflight_id,fresh=True))
    try:
        await apply_pool(command.max_workers)
    except PoolError as error:
        raise HTTPException(409, str(error)) from error
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
    from app.services import services
    ids=[runner.id for runner in await services.runners.list()
        if runner.source.value == 'new' and runner.status.value == 'ONLINE' and not runner.current_job_id]
    if not ids:
        raise HTTPException(409, 'Start at least one browser worker before resuming the queue.')
    gate=await call(require_gate(request.state.authenticated_user,ids,command.preflight_id if command else None,fresh=True))
    await bind_gate(session_id,gate)
    from app.worker_pool import apply_pool, PoolError
    try:
        await apply_pool(count)
    except PoolError as error:
        raise HTTPException(409, str(error)) from error
    await call(queue.set_status(session_id, request.state.authenticated_user, 'RUNNING',
        command.max_workers if command else None))
    return {'status': 'RUNNING'}


@router.post('/sessions/{session_id}/tasks/{position}/settle')
async def settle_task(session_id: UUID, position: int, request: Request):
    return await call(queue.settle(session_id, request.state.authenticated_user, position))


async def claim_task(session_id: UUID, command: ClaimInput, request: Request):
    """Compatibility helper for pre-Streams internal callers; no HTTP route is registered."""
    from app.repositories.ui_contract import require_gate
    if await call(queue.needs_work(session_id, request.state.authenticated_user)):
        await call(require_gate(request.state.authenticated_user, [command.runner_id],
            session_id=session_id, bound=True))
    result = await call(queue.claim(session_id, request.state.authenticated_user, command.runner_id))
    job = result.pop('job', None)
    if result['type'] == 'assigned' and job is None:
        from app.services import services
        job = await services.jobs.get(UUID(result['jobId']))
    if job:
        await sio.emit('job:assigned', {'jobId': str(job.id), 'filters': job.filters.runner_payload(),
            'scenarioName': job.scenario_name, 'source': job.source.value},
            room=f'runner:{command.runner_id}', namespace='/runner')
    return result


class QueueClaimRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    session_id: UUID | None = Field(default=None, alias='sessionId')


@worker_router.post('/queue/claim')
async def claim_queue_task(request: Request, command: QueueClaimRequest | None = None):
    """Let a ready runner claim the next case directly from a PostgreSQL queue."""
    runner_id = request.headers.get('x-vahan-runner-id', '').strip()
    if not getattr(request.state, 'authenticated_runner', False) or not runner_id:
        raise HTTPException(401, 'Runner authentication is required.')
    from app.repositories.ui_contract import require_gate
    if command and command.session_id:
        async with engine.connect() as connection:
            owner = await connection.scalar(select(db.batch_queue_sessions.c.owner_username).where(
                db.batch_queue_sessions.c.session_id == str(command.session_id)))
        candidates = [(command.session_id, owner)] if owner else []
    else:
        candidates = await queue.candidate_sessions()
    if not candidates:
        return {'type': 'done' if command and command.session_id else 'idle'}

    gate_required = waiting = False
    for session_id, owner in candidates:
        try:
            if await queue.needs_work(session_id, owner):
                await require_gate(owner, [runner_id], session_id=session_id, bound=True)
        except ValueError as error:
            if str(error).startswith(('UI_PREFLIGHT_REQUIRED:', 'UI_HEALTH_BLOCKED:')):
                gate_required = True
                continue
            raise HTTPException(409, str(error)) from error
        result = await queue.claim(session_id, owner, runner_id)
        if result['type'] == 'assigned':
            job = result.pop('job', None)
            if job is None:
                from app.services import services
                job = await services.jobs.get(UUID(result['jobId']))
            job_payload = job.model_dump(mode='json', by_alias=True) if job else None
            if job_payload:
                job_payload['jobId'] = str(job.id)
            result['job'] = job_payload
            return result
        if result['type'] == 'waiting':
            waiting = True
        elif result['type'] in {'runner_unavailable', 'network_paused', 'pool_updating'}:
            return result
        elif command and command.session_id:
            return result
    if gate_required:
        return {'type': 'gate_required'}
    return {'type': 'waiting' if waiting else 'idle'}
