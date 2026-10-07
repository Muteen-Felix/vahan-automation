"""Keep the physical crawler pool aligned with the dashboard's worker count."""
import asyncio
import json
import logging
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.config import settings
from app.db import engine, schema as db
from app.state_codec import decode_user_state

KEY = 'docker-worker-pool'
_lock = asyncio.Lock()
logger = logging.getLogger(__name__)

class PoolError(ValueError):
    pass

class ControllerClient:
    async def request(self, count=None):
        def send():
            request = Request(settings.worker_controller_url.rstrip('/') + '/workers',
                data=json.dumps({'count': count}).encode() if count is not None else None,
                headers={'X-Worker-Control-Token': settings.runner_token, 'Content-Type': 'application/json'})
            try:
                with urlopen(request, timeout=260) as response:
                    return json.load(response)
            except HTTPError as error:
                try: message = json.loads(error.read()).get('error', 'Worker controller rejected the change.')
                except ValueError: message = 'Worker controller rejected the change.'
                raise PoolError(message) from error
            except OSError as error:
                raise PoolError('Docker worker controller is unavailable. Please retry.') from error
        return await asyncio.to_thread(send)

async def initialize_pool(reset_phase=False):
    async with engine.begin() as connection:
        saved = await connection.scalar(select(db.user_state.c.value).where(
            db.user_state.c.key == 'vahanRunSettingsV1').order_by(db.user_state.c.updated_at.desc()).limit(1))
        saved = decode_user_state(saved) if saved else {}
        count = saved.get('workerCount', 10) if isinstance(saved, dict) else 10
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 10: count = 10
        await connection.execute(pg_insert(db.app_settings).values(key=KEY,
            value={'desiredCount': count, 'phase': 'ready'}).on_conflict_do_nothing())
        if reset_phase:
            current = await connection.scalar(select(db.app_settings.c.value).where(db.app_settings.c.key == KEY))
            await connection.execute(update(db.app_settings).where(db.app_settings.c.key == KEY).values(
                value={**current, 'phase': 'ready'}))

async def pool_value(connection, lock=False):
    query = select(db.app_settings.c.value).where(db.app_settings.c.key == KEY)
    if lock: query = query.with_for_update(read=True)
    return await connection.scalar(query) or {'desiredCount': 10, 'phase': 'ready'}

async def assignment_allowed(connection, runner_id):
    return (await assignment_status(connection, runner_id))[0] == 'ready'

async def assignment_status(connection, runner_id):
    if not settings.worker_controller_url: return 'ready', None
    pool = await pool_value(connection, lock=True)
    number = re.fullmatch(r'playwright-(\d+)', runner_id)
    if pool['phase'] != 'ready': return 'updating', pool['desiredCount']
    if number and int(number[1]) > pool['desiredCount']: return 'disabled', pool['desiredCount']
    return 'ready', pool['desiredCount']

async def forget_stopped_workers(state):
    stopped = [f"playwright-{worker['number']}" for worker in state['workers'] if not worker['running']]
    async with engine.begin() as connection:
        for row in (await connection.execute(select(db.runners).where(db.runners.c.id.in_(stopped))
            .with_for_update())).mappings():
            if row['current_job_id']: continue
            payload = {**row['payload'], 'socket_id': None, 'status': 'RECONNECTING'}
            await connection.execute(update(db.runners).where(db.runners.c.id == row['id']).values(
                connected=False, socket_id=None, payload=payload))

async def pool_status(client=None):
    if not settings.worker_controller_url and client is None:
        return {'enabled': False, 'desiredCount': None, 'runningCount': None, 'phase': 'ready', 'workers': []}
    async with engine.connect() as connection:
        pool = await pool_value(connection)
    state = await (client or ControllerClient()).request()
    return {'enabled': True, **state, **pool}

async def apply_pool(count, client=None, reconcile=False):
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10:
        raise PoolError('Choose between 1 and 10 workers.')
    if not settings.worker_controller_url and client is None:
        return await pool_status()
    client = client or ControllerClient()
    async with _lock:
        await initialize_pool()
        if reconcile:
            async with engine.connect() as connection:
                count = (await pool_value(connection))['desiredCount']
        state = await client.request()
        async with engine.begin() as connection:
            previous = await connection.scalar(select(db.app_settings.c.value).where(
                db.app_settings.c.key == KEY).with_for_update())
            if previous['phase'] != 'ready':
                raise PoolError('Docker worker count is being changed. Please retry shortly.')
            actual = {w['number'] for w in state['workers'] if w['running']}
            if previous['phase'] == 'ready' and previous['desiredCount'] == count and actual == set(range(1, count + 1)):
                # The request can be repeated safely while this pool is busy.
                return {'enabled': True, **state, **previous}
            active = list(await connection.scalars(select(db.runners.c.id).where(db.runners.c.current_job_id.is_not(None))))
            # Growing the pool does not stop existing cases. A reduction is
            # blocked only when it would shut down an active browser.
            forbidden = [runner for runner in active if re.fullmatch(r'playwright-(\d+)', runner)
                and int(runner.split('-')[-1]) > count]
            if forbidden:
                raise PoolError('Stop the current run before changing Docker worker count.')
            await connection.execute(update(db.app_settings).where(db.app_settings.c.key == KEY).values(
                value={'desiredCount': count, 'phase': 'applying'}))
        # Docker and readiness waits happen outside SQL transactions.
        try:
            state = await client.request(count)
            await forget_stopped_workers(state)
            deadline = asyncio.get_running_loop().time() + 30
            expected = {f'playwright-{number}' for number in range(1, count + 1)}
            while asyncio.get_running_loop().time() < deadline:
                async with engine.connect() as connection:
                    connected = set(await connection.scalars(select(db.runners.c.id).where(db.runners.c.connected.is_(True))))
                if expected <= connected: break
                await asyncio.sleep(.25)
            else: raise PoolError('Docker workers started but have not connected to the API. Please retry.')
        except Exception:
            async with engine.begin() as connection:
                await connection.execute(update(db.app_settings).where(db.app_settings.c.key == KEY).values(
                    value={**previous, 'phase': 'ready'}))
            raise
        async with engine.begin() as connection:
            await connection.execute(update(db.batch_queue_sessions).where(
                db.batch_queue_sessions.c.status == 'RUNNING').values(
                    max_workers=func.least(db.batch_queue_sessions.c.max_workers, count)))
            await connection.execute(update(db.app_settings).where(db.app_settings.c.key == KEY).values(
                value={'desiredCount': count, 'phase': 'ready'}))
        return {'enabled': True, **state, 'desiredCount': count, 'phase': 'ready'}

async def reconcile_pool():
    """Trim unwanted containers after Docker Desktop or Compose starts them again."""
    if not settings.worker_controller_url: return
    while True:
        try:
            async with engine.connect() as connection:
                desired = (await pool_value(connection))['desiredCount']
            await apply_pool(desired, reconcile=True)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning('Worker pool reconciliation deferred: %s', error)
        await asyncio.sleep(10)
