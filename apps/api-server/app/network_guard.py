"""Durable server connectivity guard; browser visibility never owns recovery."""
import asyncio
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import UUID
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.db import engine, schema as db
from app.repositories.run_schedules import RunScheduleRepository, now
from app.models.job import JobStatus
from app.services import services
from app.realtime.server import sio

KEY = 'network-connectivity'
_lock = asyncio.Lock()

async def status():
    async with engine.connect() as connection:
        return await connection.scalar(select(db.app_settings.c.value).where(db.app_settings.c.key == KEY)) or {
            'online': True, 'checkedAt': None, 'message': 'Connection has not been checked yet.'}

async def require_connection():
    if not (await status())['online']:
        raise ValueError('NETWORK_PAUSED: connection to VAHAN is unavailable. Work will continue after recovery.')

async def probe():
    def check():
        try:
            # HEAD tests the same upstream used by the workers, without loading
            # images, executing JavaScript or generating reports.
            request = Request('https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en', method='HEAD')
            with urlopen(request, timeout=4) as response:
                return response.status < 500, None
        except HTTPError as error:
            # Authentication, forbidden and unsupported HEAD are reachable;
            # they must keep their own error classes, not become network loss.
            return error.code < 500, f'VAHAN HTTP {error.code}' if error.code >= 500 else None
        except (OSError, TimeoutError):
            return False, 'Could not connect to VAHAN (DNS, timeout or connection failure).'
    return await asyncio.to_thread(check)

async def record(online, message=None):
    async with _lock:
        previous = await status()
        value = {'online': online, 'checkedAt': now().isoformat(),
            'changedAt': previous.get('changedAt') if previous['online'] == online else now().isoformat(),
            'message': message or ('Connection restored. Resuming automatically paused work.' if online else 'Connection unavailable. Report work is paused until recovery.')}
        async with engine.begin() as connection:
            await connection.execute(pg_insert(db.app_settings).values(key=KEY, value=value)
                .on_conflict_do_update(index_elements=[db.app_settings.c.key], set_={'value': value}))
        if not online:
            await suspend_runs()
        if previous['online'] != online:
            await sio.emit('network:status', value, namespace='/ui')
        return value

async def suspend_runs():
    repo = RunScheduleRepository()
    for value in await repo.list():
        if value['status'] in {'PREPARING', 'RESUMING', 'RUNNING'}:
            try:
                await repo.pause(value['id'], value['owner'], network=True)
            except (ValueError, LookupError):
                pass  # A user pause/delete won the row lock.
    async with engine.connect() as connection:
        jobs = (await connection.execute(select(db.jobs.c.id, db.jobs.c.runner_id).where(
            db.jobs.c.status.not_in(['COMPLETED', 'NO_DATA', 'FAILED', 'CANCELLED'])))).all()
        leases = (await connection.execute(select(db.runner_planning_leases.c.runner_id, db.runner_planning_leases.c.token,
            db.runners.c.socket_id).join(db.runners, db.runners.c.id == db.runner_planning_leases.c.runner_id)
            .where(db.runner_planning_leases.c.expires_at > now()))).all()
    for job_id, runner_id in jobs:
        updated = await services.jobs.transition_status(UUID(job_id), JobStatus.CANCELLED,
            error='NETWORK_PAUSED: interrupted by connection loss; queued for recovery.')
        if updated is None:
            continue  # A confirmed result was committed first; preserve it.
        await services.runners.release_job(runner_id, job_id)
        await sio.emit('job:cancelled', {'jobId': job_id}, room=f'runner:{runner_id}', namespace='/runner')
    async def cancel_options(lease):
        if not lease.socket_id:
            return
        try:
            await sio.call('runner:cancel-options', {'requestId': lease.token}, to=lease.socket_id, namespace='/runner', timeout=5)
        except Exception:
            pass  # The runner's existing options deadline remains bounded.
    await asyncio.gather(*(cancel_options(lease) for lease in leases))

async def monitor():
    successes = 0
    while True:
        try:
            online, error = await probe()
            if online:
                successes += 1
                if successes >= 2 or (await status())['online']:
                    await record(True)
            else:
                successes = 0
                await record(False, error)
        except asyncio.CancelledError:
            raise
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Connectivity monitor failed; retaining the last durable state.')
        await asyncio.sleep(5)
