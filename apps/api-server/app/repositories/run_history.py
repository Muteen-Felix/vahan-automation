"""One history entry per persisted report run, with an immutable filter name."""
from sqlalchemy import DateTime, case, cast, func, literal, or_, select, union, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import engine, schema as db
from app.repositories.run_schedules import PREFIX as SCHEDULE_PREFIX

PREFIX = 'report-run-history:'


async def record_run(connection, session_id, profile_id, filter_name):
    started_at = await connection.scalar(select(db.batch_queue_sessions.c.created_at)
        .where(db.batch_queue_sessions.c.session_id == str(session_id)))
    if started_at is None:
        return
    await connection.execute(pg_insert(db.app_settings).values(
        key=PREFIX + str(session_id),
        value={'profileId': str(profile_id), 'filterName': filter_name,
               'startedAt': started_at.isoformat()},
    ).on_conflict_do_nothing())


async def preserve_schedule_runs(connection, schedule):
    for session_id in {schedule.get('sessionId'), schedule.get('lastSessionId')} - {None}:
        await record_run(connection, session_id, schedule['profileId'], schedule['profileName'])
        details = await run_details(connection, [session_id])
        if session_id in details:
            progress = details[session_id]
            if (session_id == schedule.get('sessionId') or (
                    not schedule.get('sessionId') and schedule.get('status') == 'STOPPED')) and progress['status'] not in {'COMPLETED', 'COMPLETED_WITH_ERRORS'}:
                progress['status'] = schedule.get('status', progress['status'])
            await connection.execute(update(db.app_settings).where(db.app_settings.c.key == PREFIX + session_id)
                .values(value=db.app_settings.c.value.op('||')({'progress': progress})))


async def run_details(connection, session_ids):
    """Count queue cases once, independently of job attempts and retries."""
    queues, tasks = db.batch_queue_sessions, db.batch_queue_tasks
    counts = select(tasks.c.session_id,
        *[func.count().filter(tasks.c.status == state).label(name) for state, name in (
            ('COMPLETED', 'withData'), ('NO_DATA', 'noData'), ('FAILED', 'failed'),
            ('PENDING', 'pending'), ('PROCESSING', 'running'))],
        func.max(tasks.c.updated_at).label('last_case_at'),
    ).where(tasks.c.session_id.in_(session_ids)).group_by(tasks.c.session_id).subquery()
    policies = db.app_settings.alias('history_retry_policy')
    source = queues.outerjoin(counts, counts.c.session_id == queues.c.session_id).outerjoin(
        policies, policies.c.key == literal('batch-retry-policy:') + queues.c.session_id)
    rows = (await connection.execute(select(queues, counts,
        policies.c.value['phase'].as_string().label('retry_phase')).select_from(source)
        .where(queues.c.session_id.in_(session_ids)))).mappings().all()
    result = {}
    for row in rows:
        values = {name: row[name] or 0 for name in ('withData', 'noData', 'failed', 'pending', 'running')}
        processed = values['withData'] + values['noData'] + values['failed']
        complete = processed == row['total'] and (not row['failed'] or row['retry_phase'] in (None, 'DONE'))
        status = ('COMPLETED_WITH_ERRORS' if values['failed'] else 'COMPLETED') if complete else row['status']
        result[row['session_id']] = {**values, 'totalCases': row['total'], 'processed': processed,
            'status': status, 'lastActivityAt': max(row['updated_at'], row['last_case_at'] or row['updated_at']).isoformat(),
            'finishedAt': row['last_case_at'].isoformat() if complete and row['last_case_at'] else None}
    return result


async def list_runs(offset=0, limit=50):
    sessions = db.report_sessions
    queues = db.batch_queue_sessions
    metadata = db.app_settings.alias('run_metadata')
    schedules = db.app_settings.alias('legacy_schedule')
    # Existing schedules can identify their current and most recent older run.
    legacy = union(*[
        select(schedules.c.value[field].as_string().label('session_id'),
               schedules.c.value['profileId'].as_string().label('profile_id'),
               schedules.c.value['profileName'].as_string().label('filter_name'),
               case((schedules.c.value['sessionId'].as_string() == schedules.c.value[field].as_string(),
                     schedules.c.value['status'].as_string()),
                    ((schedules.c.value['sessionId'].as_string().is_(None)) &
                     schedules.c.value['status'].as_string().in_(['STOPPED', 'COMPLETED', 'COMPLETED_WITH_ERRORS']),
                     schedules.c.value['status'].as_string()), else_=None).label('schedule_status'))
        .where(schedules.c.key.startswith(SCHEDULE_PREFIX),
               schedules.c.value[field].as_string().is_not(None))
        for field in ('sessionId', 'lastSessionId')
    ]).subquery()
    profile_id = func.coalesce(metadata.c.value['profileId'].as_string(),
                               legacy.c.profile_id, sessions.c.id)
    filter_name = func.coalesce(metadata.c.value['filterName'].as_string(),
                                legacy.c.filter_name, literal('Unnamed filter'))
    started_at = func.coalesce(cast(metadata.c.value['startedAt'].as_string(), DateTime(timezone=True)),
                               queues.c.created_at, sessions.c.created_at)
    source = sessions.outerjoin(queues, queues.c.session_id == sessions.c.id).outerjoin(metadata,
        metadata.c.key == literal(PREFIX) + sessions.c.id).outerjoin(legacy, legacy.c.session_id == sessions.c.id)
    included = or_(queues.c.session_id.is_not(None), metadata.c.key.is_not(None))
    ranked = select(
        sessions.c.id.label('session_id'), started_at.label('created_at'), filter_name.label('filter_name'),
        metadata.c.value['progress'].label('saved_progress'),
        legacy.c.schedule_status,
        func.row_number().over(partition_by=profile_id,
            order_by=(started_at, sessions.c.id)).label('run_number'),
        func.count().over(partition_by=profile_id).label('total_runs'),
    ).select_from(source).where(included).subquery()
    async with engine.connect() as connection:
        total = await connection.scalar(select(func.count()).select_from(source).where(included))
        rows = (await connection.execute(select(ranked)
            .order_by(ranked.c.created_at.desc(), ranked.c.session_id.desc())
            .offset(offset).limit(limit))).mappings().all()
        details = await run_details(connection, [row['session_id'] for row in rows])
        for row in rows:
            progress = details.get(row['session_id'])
            if progress and row['schedule_status'] and progress['status'] not in {'COMPLETED', 'COMPLETED_WITH_ERRORS'}:
                progress['status'] = row['schedule_status']
    return {'total': total, 'offset': offset, 'limit': limit, 'runs': [
        {'sessionId': row['session_id'], 'filterName': row['filter_name'],
         'runNumber': row['run_number'], 'totalRuns': row['total_runs'],
         **details.get(row['session_id'], row['saved_progress'] or {
             'status': 'UNKNOWN', 'totalCases': None, 'processed': None,
             'withData': None, 'noData': None, 'failed': None, 'pending': None, 'running': None,
             'lastActivityAt': None, 'finishedAt': None}),
         'startedAt': row['created_at'].isoformat()} for row in rows
    ]}
