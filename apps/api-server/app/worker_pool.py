"""Limit active browser work in SQL; runner containers are managed by deployment."""
from datetime import datetime, timezone

from sqlalchemy import func, select, update, union
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.db import engine, schema as db
from app.state_codec import decode_user_state

# Preserve the saved worker limit when upgrading from the Docker controller.
KEY = 'docker-worker-pool'
DEFAULT_CONCURRENCY = 1


class PoolError(ValueError):
    pass


async def initialize_pool(reset_phase=False):
    async with engine.begin() as connection:
        saved = await connection.scalar(select(db.user_state.c.value).where(
            db.user_state.c.key == 'vahanRunSettingsV1').order_by(db.user_state.c.updated_at.desc()).limit(1))
        saved = decode_user_state(saved) if saved else {}
        count = saved.get('workerCount', DEFAULT_CONCURRENCY) if isinstance(saved, dict) else DEFAULT_CONCURRENCY
        if type(count) is not int or count < 1:
            count = DEFAULT_CONCURRENCY
        await connection.execute(pg_insert(db.app_settings).values(key=KEY,
            value={'desiredCount': count, 'phase': 'ready'}).on_conflict_do_nothing())
        if reset_phase:
            current = await pool_value(connection, lock=True)
            await connection.execute(update(db.app_settings).where(db.app_settings.c.key == KEY).values(
                value={**current, 'phase': 'ready'}))


async def pool_value(connection, lock=False):
    if lock:
        await connection.execute(pg_insert(db.app_settings).values(key=KEY,
            value={'desiredCount': DEFAULT_CONCURRENCY, 'phase': 'ready'}).on_conflict_do_nothing())
    query = select(db.app_settings.c.value).where(db.app_settings.c.key == KEY)
    if lock:
        # This cross-process lock serializes claims and limit changes. The
        # caller holds it until its assignment or reservation commits.
        query = query.with_for_update()
    return await connection.scalar(query) or {'desiredCount': DEFAULT_CONCURRENCY, 'phase': 'ready'}


def worker_enabled(runner_id, count):
    return bool(runner_id) and count >= 1


async def active_workers(connection):
    active = union(
        select(db.runners.c.id).where(db.runners.c.current_job_id.is_not(None)),
        select(db.runner_planning_leases.c.runner_id).where(
            db.runner_planning_leases.c.expires_at > datetime.now(timezone.utc)))
    return set(await connection.scalars(active))


async def capacity_available(connection, runner_ids):
    pool = await pool_value(connection, lock=True)
    return len((await active_workers(connection)) | set(runner_ids)) <= pool['desiredCount']


async def assignment_allowed(connection, runner_id):
    return (await assignment_status(connection, runner_id))[0] == 'ready'


async def assignment_status(connection, runner_id):
    from app.network_guard import KEY as network_key
    network = await connection.scalar(select(db.app_settings.c.value).where(
        db.app_settings.c.key == network_key).with_for_update(read=True))
    if network and not network['online']:
        return 'offline', None
    pool = await pool_value(connection, lock=True)
    if pool['phase'] != 'ready':
        return 'updating', pool['desiredCount']
    if not worker_enabled(runner_id, pool['desiredCount']):
        return 'disabled', pool['desiredCount']
    return 'ready', pool['desiredCount']


async def _status(connection, pool):
    rows = (await connection.execute(select(db.runners.c.id, db.runners.c.connected).order_by(
        db.runners.c.id))).mappings().all()
    connected = {row['id'] for row in rows if row['connected']}
    active = await active_workers(connection)
    rows = [row for row in rows if row['id'] in connected or row['id'] in active]
    workers = [{'number': number, 'runnerId': row['id'], 'running': row['id'] in connected,
                'enabled': True, 'busy': row['id'] in active}
               for number, row in enumerate(rows, start=1)]
    return {'enabled': True, 'mode': 'logical', **pool, 'runningCount': len(connected),
            'activeCount': len(active), 'workers': workers}


async def pool_status():
    async with engine.connect() as connection:
        return await _status(connection, await pool_value(connection))


async def apply_pool(count):
    if type(count) is not int or count < 1:
        raise PoolError('Choose a positive concurrency limit.')
    async with engine.begin() as connection:
        previous = await pool_value(connection, lock=True)
        if previous['phase'] != 'ready':
            raise PoolError('Worker limit is being changed. Please retry shortly.')
        if previous['desiredCount'] != count:
            active = await active_workers(connection)
            if len(active) > count:
                raise PoolError('Wait for active reports and filter checks to finish before reducing the worker limit.')
            # Growing the pool does not silently grow an existing queue.
            await connection.execute(update(db.batch_queue_sessions).where(
                db.batch_queue_sessions.c.status == 'RUNNING').values(
                    max_workers=func.least(db.batch_queue_sessions.c.max_workers, count)))
            await connection.execute(update(db.app_settings).where(db.app_settings.c.key == KEY).values(
                value={'desiredCount': count, 'phase': 'ready'}))
        return await _status(connection, {'desiredCount': count, 'phase': 'ready'})
