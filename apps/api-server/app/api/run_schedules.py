from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from app.access import owner_filter, require_admin
from app.db import engine, schema as db
from app.models.job import Job, JobStatus
from app.models.run_schedule import RunScheduleCreate, RunScheduleTimeZone, RunScheduleToggle, RunScheduleResume
from app.repositories.run_schedules import RunScheduleRepository, public_schedule
from app.scheduler_wakeup import wake_scheduler

router = APIRouter(prefix='/run-schedules', tags=['run-schedules'], dependencies=[Depends(require_admin)])
repository = RunScheduleRepository()


async def call(operation):
    try:
        return await operation
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.get('')
async def list_schedules(request: Request):
    from app.run_diagnostics import attach_diagnostics
    return await attach_diagnostics([public_schedule(value) for value in await repository.list(owner_filter(request))])


async def schedule_owner(schedule_id, request):
    require_admin(request)
    value = await call(repository.get(schedule_id, owner_filter(request)))
    return value['owner']


@router.get('/captchas')
async def current_captchas(request: Request):
    query = select(db.jobs.c.payload).where(db.jobs.c.status == JobStatus.WAITING_CAPTCHA.value).order_by(db.jobs.c.updated_at.desc())
    owner = owner_filter(request)
    if owner is not None:
        query = query.where(db.jobs.c.owner_username == owner)
    async with engine.connect() as connection:
        payloads = list(await connection.scalars(query.limit(10)))
    jobs = [Job.model_validate(payload) for payload in payloads]
    return [{'jobId': str(job.id), 'runnerId': job.runner_id, 'captchaId': job.captcha_id,
        'scenarioName': job.scenario_name}
        for job in jobs if job.captcha_id]


@router.post('', status_code=201)
async def create_schedule(command: RunScheduleCreate, request: Request):
    value = await call(repository.create(request.state.authenticated_user, command))
    wake_scheduler()
    return public_schedule(value)


@router.post('/time-zone')
async def set_schedule_time_zone(command: RunScheduleTimeZone, request: Request):
    values = await call(repository.set_owner_time_zone(request.state.authenticated_user, command.time_zone))
    wake_scheduler()
    return [public_schedule(value) for value in values]


@router.patch('/{schedule_id}')
async def toggle_schedule(schedule_id: UUID, command: RunScheduleToggle, request: Request):
    value = await call(repository.toggle(schedule_id, await schedule_owner(schedule_id, request), command.enabled))
    wake_scheduler()
    return public_schedule(value)


@router.post('/{schedule_id}/stop')
async def stop_schedule(schedule_id: UUID, request: Request):
    from app.run_scheduler import stop_scheduled_run
    value = await call(repository.get(schedule_id, owner_filter(request)))
    await stop_scheduled_run(value)
    wake_scheduler()
    return public_schedule(await repository.get(schedule_id, owner_filter(request)))


@router.post('/{schedule_id}/pause')
async def pause_schedule(schedule_id: UUID, request: Request):
    value = await call(repository.pause(schedule_id, await schedule_owner(schedule_id, request)))
    wake_scheduler()
    return public_schedule(value)


@router.post('/{schedule_id}/resume')
async def resume_schedule(schedule_id: UUID, command: RunScheduleResume, request: Request):
    value = await call(repository.resume(schedule_id, await schedule_owner(schedule_id, request), command.worker_count))
    wake_scheduler()
    return public_schedule(value)


@router.delete('/{schedule_id}')
async def delete_schedule(schedule_id: UUID, request: Request):
    await call(repository.delete(schedule_id, await schedule_owner(schedule_id, request)))
    wake_scheduler()
    return {'ok': True}
