"""One history entry per persisted report run, with an immutable filter name."""
from sqlalchemy import DateTime, cast, func, literal, or_, select, union
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


async def list_runs(offset=0, limit=50):
    sessions = db.report_sessions
    queues = db.batch_queue_sessions
    metadata = db.app_settings.alias('run_metadata')
    schedules = db.app_settings.alias('legacy_schedule')
    # Existing schedules can identify their current and most recent older run.
    legacy = union(*[
        select(schedules.c.value[field].as_string().label('session_id'),
               schedules.c.value['profileId'].as_string().label('profile_id'),
               schedules.c.value['profileName'].as_string().label('filter_name'))
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
        func.row_number().over(partition_by=profile_id,
            order_by=(started_at, sessions.c.id)).label('run_number'),
        func.count().over(partition_by=profile_id).label('total_runs'),
    ).select_from(source).where(included).subquery()
    async with engine.connect() as connection:
        total = await connection.scalar(select(func.count()).select_from(source).where(included))
        rows = (await connection.execute(select(ranked)
            .order_by(ranked.c.created_at.desc(), ranked.c.session_id.desc())
            .offset(offset).limit(limit))).mappings().all()
    return {'total': total, 'offset': offset, 'limit': limit, 'runs': [
        {'sessionId': row['session_id'], 'filterName': row['filter_name'],
         'runNumber': row['run_number'], 'totalRuns': row['total_runs'],
         'startedAt': row['created_at'].isoformat()} for row in rows
    ]}
