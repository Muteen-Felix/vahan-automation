from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.access import owner_filter
from app.db import engine, schema as db
from app.models.job import Job, JobStatus
from app.models.run_schedule import RunScheduleCreate, RunScheduleToggle, RunScheduleResume
from app.repositories.run_schedules import RunScheduleRepository, public_schedule

router = APIRouter(prefix='/run-schedules', tags=['run-schedules'])
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
    return await attach_diagnostics([public_schedule(value) for value in await repository.list(request.state.authenticated_user)])


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
    return public_schedule(await call(repository.create(request.state.authenticated_user, command)))


@router.patch('/{schedule_id}')
async def toggle_schedule(schedule_id: UUID, command: RunScheduleToggle, request: Request):
    return public_schedule(await call(repository.toggle(schedule_id, request.state.authenticated_user, command.enabled)))


@router.post('/{schedule_id}/stop')
async def stop_schedule(schedule_id: UUID, request: Request):
    from app.run_scheduler import stop_scheduled_run
    value = await call(repository.get(schedule_id, request.state.authenticated_user))
    await stop_scheduled_run(value)
    return public_schedule(await repository.get(schedule_id, request.state.authenticated_user))


@router.post('/{schedule_id}/pause')
async def pause_schedule(schedule_id: UUID, request: Request):
    return public_schedule(await call(repository.pause(schedule_id, request.state.authenticated_user)))


@router.post('/{schedule_id}/resume')
async def resume_schedule(schedule_id: UUID, command: RunScheduleResume, request: Request):
    return public_schedule(await call(repository.resume(schedule_id, request.state.authenticated_user, command.worker_count)))


@router.delete('/{schedule_id}')
async def delete_schedule(schedule_id: UUID, request: Request):
    await call(repository.delete(schedule_id, request.state.authenticated_user))
    return {'ok': True}
