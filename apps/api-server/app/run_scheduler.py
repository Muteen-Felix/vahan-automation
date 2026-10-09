"""Backend orchestration: schedules keep running without a dashboard connection."""
import asyncio
import logging
from datetime import datetime, timedelta
from uuid import UUID
from fastapi import HTTPException

from sqlalchemy import select, text
from app.db import engine, schema as db
from app.models.job import Job, JobStatus
from app.repositories.postgres import TERMINAL
from app.models.runner import RunnerStatus
from app.repositories.batch_queue import BatchQueueRepository, MAX_FAILURES
from app.repositories.run_schedules import RunScheduleRepository, now, active_elapsed_ms
from app.realtime.server import sio
from app.services import services
from app.worker_pool import apply_pool, PoolError
from app.scheduler_wakeup import wait_for_scheduler_wakeup, wake_scheduler

logger = logging.getLogger(__name__)
repository = RunScheduleRepository()
queue = BatchQueueRepository()
LEADER_LOCK = 846_217_035


def preflight_waiting(error):
    detail=getattr(error,'detail',None)
    return isinstance(error,HTTPException) and isinstance(detail,dict) and detail.get('code')=='PREFLIGHT_WAITING'


async def owner_active(owner):
    async with engine.connect() as connection:
        return bool(await connection.scalar(select(db.users.c.active).where(db.users.c.username == owner)))


async def execution_busy(session_id):
    async with engine.connect() as connection:
        busy = await connection.scalar(select(db.runners.c.id).where(db.runners.c.current_job_id.is_not(None)).limit(1))
        planning = await connection.scalar(select(db.runner_planning_leases.c.runner_id).where(
            db.runner_planning_leases.c.expires_at > now()).limit(1))
        running_queue = await connection.scalar(select(db.batch_queue_tasks.c.session_id)
            .join(db.batch_queue_sessions, db.batch_queue_tasks.c.session_id == db.batch_queue_sessions.c.session_id)
            .where(db.batch_queue_sessions.c.status == 'RUNNING', db.batch_queue_tasks.c.session_id != session_id,
                db.batch_queue_tasks.c.status.in_(['PENDING', 'PROCESSING'])).limit(1))
        return bool(busy or planning or running_queue)


async def automatic_preflight(value, runner_ids):
    """Run the shared UI health gate under the schedule owner's identity."""
    from starlette.requests import Request
    from app.api.ui_health import preflight, PreflightInput
    from app.repositories.ui_contract import require_gate
    request = Request({'type': 'http'})
    request.state.authenticated_user = value['owner']
    result = await preflight(PreflightInput(runnerIds=runner_ids), request)
    return await require_gate(value['owner'], runner_ids, result['preflightId'], fresh=True)


async def stop_scheduled_run(value, message='Scheduled run stopped.'):
    session_id = value.get('sessionId')
    # Fence the scheduler before pausing and cancelling any assignments.
    await repository.patch(value['id'], {'sessionId': None, 'enabled': False, 'nextRunAt': None,
        'status': 'STOPPED', 'networkPaused': False, 'tasks': None, 'message': message, 'lastFinishedAt': now().isoformat(),
        'activeElapsedMs': active_elapsed_ms(value), 'activeSegmentStartedAt': None}, value['owner'])
    if not session_id:
        return
    try:
        await queue.set_status(UUID(session_id), value['owner'], 'PAUSED')
    except LookupError:
        return  # Stop during planning, before the queue was created.
    async with engine.connect() as connection:
        payloads = list(await connection.scalars(select(db.jobs.c.payload).where(
            db.jobs.c.session_id == session_id, db.jobs.c.status.not_in([status.value for status in TERMINAL]))))
    for payload in payloads:
        job = Job.model_validate(payload)
        updated = await services.jobs.transition_status(job.id, JobStatus.CANCELLED)
        if updated is None:
            continue
        await services.runners.release_job(job.runner_id, str(job.id))
        await sio.emit('job:cancelled', {'jobId': str(job.id)}, room=f'runner:{job.runner_id}', namespace='/runner')
        await sio.emit('job:status', updated.model_dump(mode='json', by_alias=True),
            room=f'job:{job.id}', namespace='/ui')


async def checkpoint(value, changes):
    return await repository.patch(value['id'], changes, session_id=value['sessionId'],
        execution_epoch=value.get('executionEpoch', 0))


def queue_counts(tasks):
    # A final sweep reopens exhausted cases, not their original processed-case
    # count. Keep progress/rate monotonic while the separate phase tracks recovery.
    return {'total': len(tasks), 'done': sum(task['status'] in {'COMPLETED', 'NO_DATA', 'FAILED'}
                                          or task.get('failures', 0) >= MAX_FAILURES for task in tasks),
        'withData': sum(task['status'] == 'COMPLETED' for task in tasks),
        'noData': sum(task['status'] == 'NO_DATA' for task in tasks),
        'failed': sum((task['status'] == 'FAILED' or task.get('failures', 0) > 0)
                      and task['status'] not in {'COMPLETED', 'NO_DATA'} for task in tasks)}


def queue_finished(snapshot, counts):
    retry = snapshot.get('retry')
    return counts.get('total') and counts['done'] == counts['total'] and (
        not retry or retry['complete'] or counts['failed'] == 0)


def retry_message(snapshot, counts):
    retry = snapshot.get('retry') or {}
    if retry.get('phase') == 'CHECKPOINT':
        return f"Retrying failed cases in checkpoint {retry['checkpointStart'] + 1}–{retry['checkpointEnd']} before the next group."
    if retry.get('phase') == 'FINAL':
        return f"Final recovery: distributing {retry['failedRemaining']} failed cases across the workers."
    return f"Collected {counts['done']}/{counts['total']} cases."


async def still_current(value):
    try:
        current = await repository.get(value['id'])
    except LookupError:
        return False  # A paused schedule can be deleted while an old tick finishes.
    return current.get('sessionId') == value['sessionId'] and current.get('executionEpoch', 0) == value.get('executionEpoch', 0)


async def complete_run(value, counts, retry=None):
    if not await still_current(value):
        return
    await queue.set_status(UUID(value['sessionId']), value['owner'], 'PAUSED')
    if retry:
        counts = {**counts, 'retryProgress': {**retry, 'phase': 'DONE', 'complete': True}}
    await repository.complete(value, counts)


async def prepare_run(value):
    from app.api.batch_queue import QueueTaskInput
    from app.api.filter_profiles import compile_profile_plan
    from app.repositories.ui_contract import require_gate, bind_gate
    session_id = value['sessionId']
    resuming = value['status'] == 'RESUMING'
    try:
        try:
            snapshot = await queue.snapshot(UUID(session_id), value['owner'])
        except LookupError:
            snapshot = None
        if snapshot:
            counts = queue_counts(snapshot['tasks'])
            if queue_finished(snapshot, counts):
                await complete_run(value, counts, snapshot.get('retry'))
                return
        if not await still_current(value):
            return
        if await execution_busy(session_id):
            await checkpoint(value, {'stage': 'Waiting for other work', 'message': 'Waiting for the current run or filter preview to finish.'})
            return
        await checkpoint(value, {'stage': 'Worker pool', 'message': f"Preparing {value['workerCount']} workers."})
        await apply_pool(value['workerCount'])
        if not await still_current(value):
            return
        ready = sorted([runner for runner in await services.runners.list()
            if runner.source.value == 'new' and runner.status == RunnerStatus.ONLINE
            and not runner.current_job_id], key=lambda runner: runner.id)
        if not ready:
            await checkpoint(value, {'stage': 'Worker connection', 'message': 'Waiting for a connected, idle browser worker.'})
            return
        runner_ids = [runner.id for runner in ready]
        # Resume is a new execution segment and must check the selected pool again.
        if resuming or not value.get('preflightId'):
            await checkpoint(value, {'stage': 'UI Health preflight', 'message': 'Checking the website structure on every selected worker before loading Maker data.'})
            gate = await automatic_preflight(value, runner_ids)
            value = await checkpoint(value, {'preflightId': gate, 'preflightAt': now().isoformat()})
            if value is None:
                return
        if not snapshot:
            tasks = value.get('tasks')
            if tasks is None:
                async def progress(message):
                    await checkpoint(value, {'stage': 'Loading report filters / Maker', 'message': message})
                profile = {'id': value['profileId'], 'name': value['profileName'],
                    'revision': value['profileRevision'], 'definition': value['definition']}
                plan = await compile_profile_plan(profile, ready[0].id, value['owner'], value['year'], progress)
                tasks = [{'name': task['name'], 'filters': task['filters']} for task in plan['scenarios']]
                updated = await checkpoint(value, {'tasks': tasks, 'total': len(tasks)})
                if updated is None:
                    return
                value = updated
            if not await still_current(value):
                return
            try:
                gate = await require_gate(value['owner'], runner_ids, value.get('preflightId'), fresh=True)
            except ValueError:
                gate = await automatic_preflight(value, runner_ids)
            if not await still_current(value):
                return
            await checkpoint(value, {'stage': 'Publishing report queue', 'message': f'Publishing {len(tasks)} cases for workers.'})
            await queue.start(UUID(session_id), value['owner'], [QueueTaskInput.model_validate(task) for task in tasks], value['workerCount'])
            await bind_gate(session_id, gate)
        else:
            gate = await require_gate(value['owner'], runner_ids, value.get('preflightId'), fresh=True)
            if not await still_current(value):
                return
            await bind_gate(session_id, gate)
            if snapshot['status'] == 'PAUSED':
                await queue.set_status(UUID(session_id), value['owner'], 'RUNNING', value['workerCount'])
        started = now().isoformat()
        first_start = value.get('lastSessionId') != session_id or not value.get('lastRunAt')
        updated = await checkpoint(value, {'stage': 'Collecting reports', 'status': 'RUNNING', 'message': 'Scheduled report collection is running.',
            'lastSessionId': session_id, 'lastRunAt': started if first_start else value['lastRunAt'],
            'activeSegmentStartedAt': started, 'activeElapsedMs': value.get('activeElapsedMs', 0),
            'pausedAt': None, 'tasks': None, 'retryAfter': None, 'preparationAttempts': 0})
        if updated is None:
            # A pause or stop raced with queue creation/resume. Fence the queue too.
            await queue.set_status(UUID(session_id), value['owner'], 'PAUSED')
        else:
            wake_scheduler()
    except PoolError as error:
        await checkpoint(value, {'operationError': str(error), 'message': str(error), 'retryAfter': (now() + timedelta(seconds=30)).isoformat()})
    except asyncio.CancelledError:
        raise
    except Exception as error:
        if preflight_waiting(error):
            await checkpoint(value, {'stage':'UI Health preflight','operationError':None,
                'message':'Waiting for all selected workers to become online and idle before checking the website.',
                'retryAfter':(now()+timedelta(seconds=5)).isoformat()})
            return
        attempts = value.get('preparationAttempts', 0) + 1
        changes = {'operationError': str(error), 'message': f'Could not prepare scheduled reports: {error}', 'preparationAttempts': attempts,
            'retryAfter': (now() + timedelta(seconds=60)).isoformat()}
        if attempts >= 3:
            if resuming:
                changes.update(status='PAUSED', retryAfter=None, pausedAt=now().isoformat())
            else:
                changes.update(status='ERROR', enabled=False, sessionId=None, nextRunAt=None, tasks=None)
        await checkpoint(value, changes)
        logger.exception('Scheduled report preparation failed: %s', value['id'])


async def pause_run_tick(value):
    try:
        await queue.set_status(UUID(value['sessionId']), value['owner'], 'PAUSED')
        snapshot = await queue.snapshot(UUID(value['sessionId']), value['owner'])
    except LookupError:
        snapshot = None  # Pause before a queue was prepared; retain the same session ID.
    counts = queue_counts(snapshot['tasks']) if snapshot else {}
    if snapshot and queue_finished(snapshot, counts):
        await complete_run(value, counts, snapshot.get('retry'))
        return
    processing = [task for task in snapshot['tasks'] if task['status'] == 'PROCESSING'] if snapshot else []
    if processing:
        await checkpoint(value, {**counts, 'message': f'Pausing: waiting for {len(processing)} active cases to save.'})
        return
    await checkpoint(value, {**counts, 'status': 'PAUSED', 'pausedAt': now().isoformat(),
        'activeElapsedMs': active_elapsed_ms(value), 'activeSegmentStartedAt': None,
        'message': 'Network unavailable. Work will continue automatically after recovery.' if value.get('networkPaused') else 'Run paused. Choose workers and continue the saved session.'})


async def dispatch_run(value):
    session_id = value['sessionId']
    snapshot = await queue.snapshot(UUID(session_id), value['owner'])
    if snapshot['status'] != 'RUNNING':
        await checkpoint(value, {'message': 'The report queue is paused.'})
        return
    counts = queue_counts(snapshot['tasks'])
    if queue_finished(snapshot, counts):
        await complete_run(value, counts, snapshot.get('retry'))
        return
    if await checkpoint(value, {**counts, 'stage': 'Recovering failed cases' if (snapshot.get('retry') or {}).get('phase') in {'CHECKPOINT', 'FINAL'} else 'Collecting reports', 'retryProgress': snapshot.get('retry'), 'message': retry_message(snapshot, counts)}) is None:
        return
    from app.repositories.ui_contract import require_gate, bind_gate
    runner_ids = [runner.id for runner in await services.runners.list()
        if runner.source.value == 'new' and runner.status in {RunnerStatus.ONLINE, RunnerStatus.BUSY}]
    if not runner_ids:
        await checkpoint(value, {'stage': 'Waiting for workers', 'operationError': None,
            'message': 'Waiting for a connected browser worker before continuing the queue.'})
        return
    try:
        await require_gate(value['owner'], runner_ids, session_id=session_id)
    except ValueError as error:
        await checkpoint(value, {'stage': 'UI Health gate', 'operationError': str(error), 'message': str(error)})
        if await execution_busy(session_id):
            return
        try:
            gate = await automatic_preflight(value, runner_ids)
            if not await still_current(value):
                return
            await bind_gate(session_id, gate)
        except Exception as check_error:
            if preflight_waiting(check_error):
                await checkpoint(value, {'stage':'Waiting for workers','operationError':None,
                    'message':'Waiting for all selected workers to become idle before checking the website.',
                    'retryAfter':(now()+timedelta(seconds=5)).isoformat()})
                return
            await checkpoint(value, {'stage': 'UI Health gate', 'operationError': str(check_error), 'message': f'Waiting for a successful UI health check: {check_error}'})
            return
    # Redis Stream consumers claim tasks themselves. The scheduler updates the
    # run state and UI Health gate, but does not select or notify a worker.


async def scheduler_tick():
    from app.network_guard import status as network_status, suspend_runs
    connected = (await network_status())['online']
    if not connected:
        await suspend_runs()
    records = await repository.list()
    active = [value for value in records if value.get('sessionId')]
    for value in active:
        if not await owner_active(value['owner']):
            await stop_scheduled_run(value, 'The schedule owner account is inactive.')
            continue
        if value.get('networkPaused') and value['status'] == 'PAUSED':
            if connected:
                await repository.resume(value['id'], value['owner'], value['workerCount'])
                wake_scheduler()
            continue
        if not connected and value['status'] != 'PAUSING':
            continue
        if value.get('retryAfter') and datetime.fromisoformat(value['retryAfter']) > now():
            continue
        try:
            if value['status'] == 'PAUSING':
                await pause_run_tick(value)
            elif value['status'] in {'PREPARING', 'RESUMING'}:
                await prepare_run(value)
            elif value['status'] == 'RUNNING':
                await dispatch_run(value)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await checkpoint(value, {'operationError': str(error),
                'message': f'Scheduler could not continue {value["status"].lower()}: {error}',
                'retryAfter': (now() + timedelta(seconds=30)).isoformat()})
            logger.exception('Scheduled execution failed: %s', value['id'])
    # Serialize scheduled batches, retaining due schedules while workers are occupied.
    if active or not connected:
        return
    for value in records:
        if not value['enabled'] or not value.get('nextRunAt') or datetime.fromisoformat(value['nextRunAt']) > now():
            continue
        if not await owner_active(value['owner']):
            await repository.patch(value['id'], {'enabled': False, 'status': 'ERROR', 'message': 'The schedule owner account is inactive.'})
            continue
        if await repository.begin_run(value['id']):
            wake_scheduler()
            break


async def run_scheduler():
    """One PostgreSQL leader across API processes; all execution checkpoints are durable."""
    while True:
        try:
            async with engine.connect() as connection:
                leader = bool(await connection.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': LEADER_LOCK}))
                await connection.commit()
                try:
                    if leader:
                        while True:
                            try:
                                # Check leadership connectivity before any new assignment.
                                await connection.execute(text('SELECT 1'))
                                await connection.commit()
                                await scheduler_tick()
                            except asyncio.CancelledError:
                                raise
                            except Exception:
                                logger.exception('Scheduled report tick failed; retrying from its checkpoint.')
                                await connection.rollback()
                                if connection.invalidated:
                                    break
                            await wait_for_scheduler_wakeup()
                finally:
                    if leader and not connection.invalidated:
                        await connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': LEADER_LOCK})
                        await connection.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('Run scheduler is waiting for PostgreSQL.')
        await asyncio.sleep(5)
