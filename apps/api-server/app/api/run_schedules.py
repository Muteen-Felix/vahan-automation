from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
import base64
import binascii
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.access import owner_filter, require_admin
from app.db import engine, schema as db
from app.models.job import Job, JobStatus
from app.models.run_schedule import RunScheduleCreate, RunScheduleToggle, RunScheduleResume
from app.repositories.run_schedules import RunScheduleRepository, public_schedule
from app.scheduler_wakeup import wake_scheduler
from app.services import services

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
    waiting = []
    for job in jobs:
        if job.updated_at <= datetime.now(timezone.utc) - timedelta(minutes=10):
            from app.realtime.server import sio
            failed = await services.jobs.update_status(job.id, JobStatus.FAILED,
                error='CAPTCHA_WAIT_TIMEOUT: No operator input within 10 minutes. Review and continue the saved run.',
                expected_status=JobStatus.WAITING_CAPTCHA, expected_captcha_id=job.captcha_id)
            if failed:
                await services.runners.release_job(job.runner_id, str(job.id))
                await sio.emit('job:cancelled', {'jobId': str(job.id)}, room=f'runner:{job.runner_id}', namespace='/runner')
                await sio.emit('job:status', failed.model_dump(mode='json', by_alias=True), room=f'job:{job.id}', namespace='/ui')
            continue
        waiting.append(job)
    return [{'jobId': str(job.id), 'runnerId': job.runner_id, 'captchaId': job.captcha_id,
        'scenarioName': job.scenario_name}
        for job in waiting if job.captcha_id]


@router.get('/captchas/{job_id}')
async def inspect_captcha(job_id: UUID, request: Request, response: Response):
    """Read the live image for a human operator; never persist image or answer."""
    from app.realtime.server import sio
    from socketio.exceptions import TimeoutError as SocketIOTimeoutError
    require_admin(request)
    job = await services_job(job_id, request)
    runner = await services.runners.get(job.runner_id)
    if not runner or not runner.socket_id:
        raise HTTPException(409, 'The browser worker is offline.')
    try:
        result = await sio.call('captcha:inspect', {'jobId': str(job_id), 'captchaId': job.captcha_id},
                                to=runner.socket_id, namespace='/runner', timeout=10)
    except SocketIOTimeoutError:
        raise HTTPException(504, 'The browser worker did not return the CAPTCHA image in time.') from None
    if not isinstance(result, dict) or not result.get('ok'):
        raise HTTPException(409, 'The worker no longer has this waiting CAPTCHA. Reload the list.')
    current = await services_job(job_id, request)
    if result.get('captchaId') != current.captcha_id:
        raise HTTPException(409, 'The CAPTCHA changed while loading. Reload its image.')
    image = result.get('imageDataUrl', '')
    if not isinstance(image, str) or len(image) > 1_000_000:
        raise HTTPException(502, 'The worker returned an invalid CAPTCHA image.')
    match = re.fullmatch(r'data:image/png;base64,([A-Za-z0-9+/]+={0,2})', image)
    try:
        data = base64.b64decode(match.group(1), validate=True) if match else b''
    except (ValueError, binascii.Error):
        data = b''
    if len(data) > 750_000 or not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise HTTPException(502, 'The worker returned an invalid CAPTCHA image.')
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    return {'jobId': str(job_id), 'captchaId': current.captcha_id, 'imageDataUrl': image}


async def services_job(job_id, request):
    from app.services import services
    job = await services.jobs.get(job_id)
    owner = owner_filter(request)
    if not job or (owner is not None and job.owner_username != owner):
        raise HTTPException(404, 'Job not found.')
    if job.status != JobStatus.WAITING_CAPTCHA or not job.captcha_id:
        raise HTTPException(409, 'This job is no longer waiting for CAPTCHA.')
    return job


@router.post('', status_code=201)
async def create_schedule(command: RunScheduleCreate, request: Request):
    value = await call(repository.create(request.state.authenticated_user, command))
    wake_scheduler()
    return public_schedule(value)


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
