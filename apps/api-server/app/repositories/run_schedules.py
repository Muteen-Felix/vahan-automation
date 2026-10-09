"""Durable run schedules stored as versioned PostgreSQL application settings."""
import calendar
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete, insert, select, update
from app.db import engine, schema as db
from app.repositories.filter_profiles import FilterProfileRepository
from app.models.job import JobStatus

PREFIX = 'automatic-report-schedule:'
TIME_ZONE = 'Asia/Ho_Chi_Minh'


def now():
    return datetime.now(timezone.utc)


def next_daily_run(starts_at, current, time_zone=TIME_ZONE):
    """Keep the original schedule wall-clock time and skip missed daily slots."""
    zone = ZoneInfo(time_zone)
    anchor = datetime.fromisoformat(starts_at).astimezone(zone)
    current = current.astimezone(zone)
    candidate = anchor.replace(year=current.year, month=current.month, day=current.day)
    if candidate <= current:
        candidate += timedelta(days=1)
    return max(candidate, anchor).astimezone(timezone.utc).isoformat()


def next_monthly_run(starts_at, current, time_zone=TIME_ZONE):
    """Keep the original schedule day and wall-clock time; clamp short months to month end."""
    zone = ZoneInfo(time_zone)
    anchor = datetime.fromisoformat(starts_at).astimezone(zone)
    current = current.astimezone(zone)
    anchor_month = anchor.year * 12 + anchor.month - 1
    current_month = current.year * 12 + current.month - 1

    def in_month(index):
        year, month = divmod(index, 12)
        month += 1
        day = min(anchor.day, calendar.monthrange(year, month)[1])
        return anchor.replace(year=year, month=month, day=day)

    month = max(anchor_month, current_month)
    candidate = in_month(month)
    if candidate <= current:
        candidate = in_month(month + 1)
    return candidate.astimezone(timezone.utc).isoformat()


def public_schedule(value):
    result = {key: item for key, item in value.items() if key not in {'definition', 'tasks', 'owner'}}
    result.setdefault('timeZone', TIME_ZONE)
    result['canResume'] = bool(value['status'] == 'PAUSED' and not value.get('networkPaused') and value.get('sessionId') or
        value['status'] == 'STOPPED' and value.get('lastSessionId') and (value['done'] < value['total']
            or value.get('retryProgress') and not value['retryProgress']['complete']))
    return result


def active_elapsed_ms(value, current=None):
    current = current or now()
    accumulated = max(0, value.get('activeElapsedMs') or 0)
    segment = value.get('activeSegmentStartedAt')
    if segment:
        return accumulated + max(0, (current - datetime.fromisoformat(segment)).total_seconds() * 1000)
    if 'activeElapsedMs' not in value and value.get('lastRunAt'):
        end = datetime.fromisoformat(value['lastFinishedAt']) if value.get('lastFinishedAt') and value['status'] in {'STOPPED', 'COMPLETED', 'COMPLETED_WITH_ERRORS'} else current
        return max(0, (end - datetime.fromisoformat(value['lastRunAt'])).total_seconds() * 1000)
    return accumulated


class RunScheduleRepository:
    async def begin_run(self, schedule_id):
        async with engine.begin() as connection:
            key = PREFIX + str(schedule_id)
            value = await connection.scalar(select(db.app_settings.c.value).where(
                db.app_settings.c.key == key).with_for_update())
            if (not value or not value['enabled'] or value.get('sessionId') or not value.get('nextRunAt')
                    or datetime.fromisoformat(value['nextRunAt']) > now()):
                return None
            value = {**value, 'sessionId': str(uuid4()), 'status': 'PREPARING',
                'message': 'Preparing the scheduled report profile.', 'total': 0, 'done': 0, 'withData': 0,
                'noData': 0, 'failed': 0, 'preparationAttempts': 0, 'retryAfter': None, 'updatedAt': now().isoformat(),
                'activeElapsedMs': 0, 'activeSegmentStartedAt': None, 'pausedAt': None,
                'lastRunAt': None, 'lastFinishedAt': None, 'retryProgress': None, 'operation': None, 'networkPaused': False,
                'executionEpoch': value.get('executionEpoch', 0) + 1}
            await connection.execute(update(db.app_settings).where(db.app_settings.c.key == key).values(value=value))
        return value

    async def list(self, owner=None):
        query = select(db.app_settings.c.value).where(db.app_settings.c.key.like(PREFIX + '%'))
        if owner is not None:
            query = query.where(db.app_settings.c.value['owner'].as_string() == owner)
        async with engine.connect() as connection:
            records = list(await connection.scalars(query))
        return sorted(records, key=lambda value: (value['nextRunAt'] or value['startsAt'], value['id']))

    async def get(self, schedule_id, owner=None):
        async with engine.connect() as connection:
            value = await connection.scalar(select(db.app_settings.c.value).where(
                db.app_settings.c.key == PREFIX + str(schedule_id)))
        if value is None or (owner is not None and value['owner'] != owner):
            raise LookupError('Run schedule not found.')
        return value

    async def patch(self, schedule_id, changes, owner=None, session_id=None, execution_epoch=None):
        async with engine.begin() as connection:
            key = PREFIX + str(schedule_id)
            value = await connection.scalar(select(db.app_settings.c.value).where(
                db.app_settings.c.key == key).with_for_update())
            if value is None or (owner is not None and value['owner'] != owner):
                if value is None and session_id is not None:
                    return None  # The schedule was deleted while a scheduler callback was in flight.
                raise LookupError('Run schedule not found.')
            if session_id is not None and value.get('sessionId') != session_id:
                return None  # A stop action already ended this scheduled run.
            if execution_epoch is not None and value.get('executionEpoch', 0) != execution_epoch:
                return None  # A pause/resume fenced this older scheduler operation.
            stamp = now().isoformat()
            if 'operation' not in changes and ('stage' in changes or value.get('operation')):
                changes = dict(changes)
                previous = value.get('operation') or {}
                stage = changes.pop('stage', previous.get('stage', 'Preparing'))
                detail = changes.get('message', previous.get('detail', ''))
                progressed = stage != previous.get('stage') or detail != previous.get('detail') or any(
                    key in changes and changes[key] != value.get(key) for key in ('done', 'withData', 'noData', 'failed'))
                changes['operation'] = {'stage': stage, 'detail': detail,
                    'startedAt': stamp if stage != previous.get('stage') else previous.get('startedAt', stamp),
                    'progressAt': stamp if progressed else previous.get('progressAt', stamp),
                    'heartbeatAt': stamp, 'error': changes.pop('operationError', None)}
            value = {**value, **changes, 'updatedAt': stamp}
            await connection.execute(update(db.app_settings).where(db.app_settings.c.key == key).values(value=value))
        return value

    async def pause(self, schedule_id, owner, network=False):
        async with engine.begin() as connection:
            key = PREFIX + str(schedule_id)
            value = await connection.scalar(select(db.app_settings.c.value).where(db.app_settings.c.key == key).with_for_update())
            if not value or value['owner'] != owner:
                raise LookupError('Run schedule not found.')
            if value['status'] in {'PAUSING', 'PAUSED'}:
                if not network and value.get('networkPaused'):
                    value = {**value, 'networkPaused': False, 'executionEpoch': value.get('executionEpoch', 0) + 1,
                        'message': 'Run kept paused by the user.', 'updatedAt': now().isoformat()}
                    await connection.execute(update(db.app_settings).where(db.app_settings.c.key == key).values(value=value))
                return value
            if not value.get('sessionId') or value['status'] not in {'PREPARING', 'RUNNING', 'RESUMING'}:
                raise ValueError('Only an active scheduled run can be paused.')
            session = (await connection.execute(select(db.batch_queue_sessions).where(
                db.batch_queue_sessions.c.session_id == value['sessionId']).with_for_update())).mappings().first()
            if session:
                if session['owner_username'] != owner:
                    raise ValueError('Report queue owner does not match the schedule.')
                await connection.execute(update(db.batch_queue_sessions).where(
                    db.batch_queue_sessions.c.session_id == value['sessionId']).values(status='PAUSED', updated_at=now()))
            # Existing cases drain normally; committed data is never cancelled.
            value = {**value, 'status': 'PAUSING', 'executionEpoch': value.get('executionEpoch', 0) + 1,
                'retryAfter': None, 'networkPaused': network, 'message': 'Network unavailable. Waiting to resume automatically.' if network else 'Pausing: waiting for active cases to save.', 'updatedAt': now().isoformat()}
            await connection.execute(update(db.app_settings).where(db.app_settings.c.key == key).values(value=value))
        return value

    async def resume(self, schedule_id, owner, worker_count):
        if isinstance(worker_count, bool) or not isinstance(worker_count, int) or not 1 <= worker_count <= 10:
            raise ValueError('Choose between 1 and 10 workers.')
        async with engine.begin() as connection:
            key = PREFIX + str(schedule_id)
            value = await connection.scalar(select(db.app_settings.c.value).where(db.app_settings.c.key == key).with_for_update())
            if not value or value['owner'] != owner:
                raise LookupError('Run schedule not found.')
            if value['status'] in {'RUNNING', 'RESUMING'} and worker_count == value['workerCount']:
                return value
            if value['status'] not in {'PAUSED', 'STOPPED'}:
                raise ValueError('Wait until the scheduled run is paused before changing workers or continuing.')
            session_id = value.get('sessionId') or value.get('lastSessionId')
            if not session_id:
                raise ValueError('This schedule has no saved report session to continue.')
            session = (await connection.execute(select(db.batch_queue_sessions).where(
                db.batch_queue_sessions.c.session_id == session_id).with_for_update())).mappings().first()
            if session:
                if session['owner_username'] != owner or session['status'] != 'PAUSED':
                    raise ValueError('The saved report queue must be paused and owned by this user.')
                unfinished = await connection.scalar(select(db.batch_queue_tasks.c.position).where(
                    db.batch_queue_tasks.c.session_id == session_id,
                    db.batch_queue_tasks.c.status.in_(['PENDING', 'PROCESSING'])).limit(1))
                if unfinished is None:
                    policy = await connection.scalar(select(db.app_settings.c.value).where(
                        db.app_settings.c.key == 'batch-retry-policy:' + session_id))
                    eligible = policy and not policy.get('finalPassStarted') and await connection.scalar(
                        select(db.batch_queue_tasks.c.position).where(db.batch_queue_tasks.c.session_id == session_id,
                            db.batch_queue_tasks.c.status == 'FAILED').limit(1)) is not None
                    if not eligible:
                        raise ValueError('All saved cases have finished. Create a new schedule to run again.')
            elif value['status'] == 'STOPPED':
                raise ValueError('The stopped schedule has no saved queue to continue.')
            elapsed = active_elapsed_ms(value)
            value = {**value, 'sessionId': session_id, 'status': 'RESUMING', 'workerCount': worker_count,
                'executionEpoch': value.get('executionEpoch', 0) + 1, 'preparationAttempts': 0, 'retryAfter': None,
                'activeElapsedMs': elapsed, 'activeSegmentStartedAt': None, 'lastFinishedAt': None, 'pausedAt': None,
                'networkPaused': False, 'message': f'Preparing {worker_count} workers to continue the saved session.', 'updatedAt': now().isoformat()}
            await connection.execute(update(db.app_settings).where(db.app_settings.c.key == key).values(value=value))
        return value

    async def set_owner_time_zone(self, owner, time_zone):
        updated = []
        async with engine.begin() as connection:
            records = (await connection.execute(select(db.app_settings.c.key, db.app_settings.c.value)
                .where(db.app_settings.c.key.like(PREFIX + '%'),
                    db.app_settings.c.value['owner'].as_string() == owner)
                .with_for_update())).all()
            for key, value in records:
                if value.get('timeZone', TIME_ZONE) != time_zone:
                    value = {**value, 'timeZone': time_zone, 'updatedAt': now().isoformat()}
                    await connection.execute(update(db.app_settings).where(db.app_settings.c.key == key).values(value=value))
                updated.append(value)
        return updated

    async def create(self, owner, command):
        profile = await FilterProfileRepository().get(owner, command.profile_id)
        year = (profile['definition'].get('report') or {}).get('year', command.year)
        value = {'version': 1, 'id': str(uuid4()), 'owner': owner,
            'profileId': profile['id'], 'profileName': profile['name'], 'profileRevision': profile['revision'],
            'definition': profile['definition'], 'year': year, 'workerCount': command.worker_count,
            'startsAt': command.starts_at.isoformat(), 'nextRunAt': command.starts_at.isoformat(),
            'timeZone': command.time_zone, 'repeat': command.repeat, 'enabled': True, 'status': 'WAITING',
            'sessionId': None, 'lastSessionId': None, 'lastRunAt': None, 'lastFinishedAt': None,
            'message': 'Waiting for the scheduled start time.', 'total': 0, 'done': 0,
            'withData': 0, 'noData': 0, 'failed': 0, 'preparationAttempts': 0, 'retryAfter': None,
            'createdAt': now().isoformat(), 'updatedAt': now().isoformat(),
            'activeElapsedMs': 0, 'activeSegmentStartedAt': None, 'pausedAt': None, 'executionEpoch': 0}
        async with engine.begin() as connection:
            await connection.execute(insert(db.app_settings).values(key=PREFIX + value['id'], value=value))
        return value

    async def complete(self, value, counts):
        async with engine.begin() as connection:
            key = PREFIX + value['id']
            current = await connection.scalar(select(db.app_settings.c.value).where(db.app_settings.c.key == key).with_for_update())
            if not current or current.get('sessionId') != value['sessionId'] or current.get('executionEpoch', 0) != value.get('executionEpoch', 0):
                return None
            finished = now()
            time_zone = current.get('timeZone', TIME_ZONE)
            next_run = (next_daily_run(current['startsAt'], finished, time_zone) if current['repeat'] == 'daily'
                else next_monthly_run(current['startsAt'], finished, time_zone) if current['repeat'] == 'monthly' else None)
            current = {**current, **counts, 'status': 'COMPLETED_WITH_ERRORS' if counts['failed'] else 'COMPLETED',
                'message': f"Finished {counts['done']}/{counts['total']} cases. {counts['failed']} failed.",
                'sessionId': None, 'lastSessionId': value['sessionId'], 'lastFinishedAt': finished.isoformat(),
                'nextRunAt': next_run, 'enabled': current['enabled'] and next_run is not None,
                'activeElapsedMs': active_elapsed_ms(current, finished), 'activeSegmentStartedAt': None,
                'pausedAt': None, 'networkPaused': False, 'preparationAttempts': 0, 'retryAfter': None, 'updatedAt': finished.isoformat()}
            await connection.execute(update(db.app_settings).where(db.app_settings.c.key == key).values(value=current))
        return current

    async def toggle(self, schedule_id, owner, enabled):
        async with engine.begin() as connection:
            key = PREFIX + str(schedule_id)
            value = await connection.scalar(select(db.app_settings.c.value).where(db.app_settings.c.key == key).with_for_update())
            if not value or value['owner'] != owner:
                raise LookupError('Run schedule not found.')
            if enabled and not value.get('sessionId') and value['repeat'] == 'once' and not value['nextRunAt']:
                raise ValueError('This one-time schedule has ended. Create a schedule with a new date and time.')
            changes = {'enabled': enabled}
            if enabled and not value.get('sessionId'):
                legacy_resume = value['status'] == 'STOPPED' and value.get('lastSessionId') and value['done'] < value['total']
                if not legacy_resume:
                    changes.update(status='WAITING', preparationAttempts=0, retryAfter=None)
                if value['repeat'] == 'daily':
                    changes['nextRunAt'] = next_daily_run(value['startsAt'], now(), value.get('timeZone', TIME_ZONE))
                elif value['repeat'] == 'monthly':
                    changes['nextRunAt'] = next_monthly_run(value['startsAt'], now(), value.get('timeZone', TIME_ZONE))
            stamp = now().isoformat()
            if 'operation' not in changes and ('stage' in changes or value.get('operation')):
                changes = dict(changes)
                previous = value.get('operation') or {}
                stage = changes.pop('stage', previous.get('stage', 'Preparing'))
                detail = changes.get('message', previous.get('detail', ''))
                progressed = stage != previous.get('stage') or detail != previous.get('detail') or any(
                    key in changes and changes[key] != value.get(key) for key in ('done', 'withData', 'noData', 'failed'))
                changes['operation'] = {'stage': stage, 'detail': detail,
                    'startedAt': stamp if stage != previous.get('stage') else previous.get('startedAt', stamp),
                    'progressAt': stamp if progressed else previous.get('progressAt', stamp),
                    'heartbeatAt': stamp, 'error': changes.pop('operationError', None)}
            value = {**value, **changes, 'updatedAt': stamp}
            await connection.execute(update(db.app_settings).where(db.app_settings.c.key == key).values(value=value))
        return value

    async def delete(self, schedule_id, owner):
        async with engine.begin() as connection:
            key = PREFIX + str(schedule_id)
            value = await connection.scalar(select(db.app_settings.c.value).where(
                db.app_settings.c.key == key).with_for_update())
            if not value or value['owner'] != owner:
                raise LookupError('Run schedule not found.')
            if value['status'] in {'PREPARING', 'RUNNING', 'PAUSING', 'RESUMING'} or (
                    value.get('sessionId') and value['status'] not in {'PAUSED', 'STOPPED'}):
                raise ValueError('Wait until the scheduled run is paused before deleting its schedule.')
            session_id = value.get('sessionId') or value.get('lastSessionId')
            if session_id:
                session = (await connection.execute(select(db.batch_queue_sessions).where(
                    db.batch_queue_sessions.c.session_id == session_id).with_for_update())).mappings().first()
                if session and (session['owner_username'] != owner or session['status'] != 'PAUSED'):
                    raise ValueError('The saved report queue must be paused and owned by this user.')
                terminal = [JobStatus.COMPLETED.value, JobStatus.NO_DATA.value,
                    JobStatus.FAILED.value, JobStatus.CANCELLED.value]
                active_job = await connection.scalar(select(db.jobs.c.id).where(
                    db.jobs.c.session_id == session_id, db.jobs.c.status.not_in(terminal)).limit(1))
                if active_job:
                    raise ValueError('Wait for active cases to finish saving before deleting the schedule.')
                # Keep report sessions, jobs, files and collected data. Only the
                # discarded execution queue (including unfinished cases) is removed.
                if session:
                    missing_job = await connection.scalar(select(db.batch_queue_tasks.c.position).where(
                        db.batch_queue_tasks.c.session_id == session_id,
                        db.batch_queue_tasks.c.status == 'PROCESSING',
                        db.batch_queue_tasks.c.job_id.is_(None)).limit(1))
                    if missing_job is not None:
                        raise ValueError('Wait for active cases to finish saving before deleting the schedule.')
                    await connection.execute(delete(db.batch_queue_sessions).where(
                        db.batch_queue_sessions.c.session_id == session_id))
                await connection.execute(delete(db.app_settings).where(
                    db.app_settings.c.key == 'batch-retry-policy:' + session_id))
            await connection.execute(delete(db.app_settings).where(db.app_settings.c.key == key))
