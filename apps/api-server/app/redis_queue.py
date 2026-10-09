"""Redis Streams publisher backed by the PostgreSQL task outbox."""
import asyncio
import logging

from redis.asyncio import Redis
from sqlalchemy import delete, exists, insert, select

from app.config import settings
from app.db import engine, schema as db
from app.repositories.batch_queue import now

logger = logging.getLogger(__name__)
STREAM = 'vahan:report-tasks'
GROUP = 'vahan:browser-workers'


class RedisTaskQueue:
    def __init__(self):
        self.client = Redis.from_url(settings.redis_url, decode_responses=True)

    async def start(self):
        await self.client.ping()
        try:
            await self.client.xgroup_create(STREAM, GROUP, id='0', mkstream=True)
        except Exception as error:
            if 'BUSYGROUP' not in str(error):
                raise

    async def recover_empty_stream(self):
        if await self.client.xlen(STREAM):
            return 0
        tasks = db.batch_queue_tasks
        sessions = db.batch_queue_sessions
        unpublished = exists(select(db.queue_outbox.c.id).where(
            db.queue_outbox.c.session_id == tasks.c.session_id,
            db.queue_outbox.c.position == tasks.c.position,
            db.queue_outbox.c.published_at.is_(None)))
        async with engine.begin() as connection:
            rows = (await connection.execute(select(tasks.c.session_id, tasks.c.position).join(
                sessions, sessions.c.session_id == tasks.c.session_id).where(
                sessions.c.status == 'RUNNING', tasks.c.status.in_(['PENDING', 'PROCESSING']),
                ~unpublished))).all()
            if not rows:
                return 0
            await connection.execute(insert(db.queue_outbox), [{
                'session_id': row.session_id, 'position': row.position,
                'created_at': now(), 'published_at': None,
            } for row in rows])
            return len(rows)

    async def close(self):
        await self.client.aclose()

    async def worker_has_live_task(self, worker_id):
        try:
            pending = await self.client.xpending_range(
                STREAM, GROUP, '-', '+', 100, consumername=worker_id)
        except Exception:
            # Redis outages must not cause the API to duplicate a browser action.
            return True
        return any(row['consumer'] == worker_id
            and int(row['time_since_delivered']) < settings.redis_reclaim_ms for row in pending)

    async def publish_outbox(self, limit=100):
        async with engine.begin() as connection:
            rows = (await connection.execute(select(db.queue_outbox).where(
                db.queue_outbox.c.published_at.is_(None)).order_by(db.queue_outbox.c.id).limit(limit)
                .with_for_update(skip_locked=True))).mappings().all()
            for row in rows:
                await self.client.xadd(STREAM, {
                    'outboxId': str(row['id']),
                    'sessionId': row['session_id'],
                    'position': str(row['position']),
                })
                await connection.execute(delete(db.queue_outbox).where(db.queue_outbox.c.id == row['id']))
            return len(rows)

    async def publish_forever(self):
        while True:
            try:
                await self.recover_empty_stream()
                published = await self.publish_outbox()
                if not published:
                    await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('Could not publish the report task outbox to Redis Streams.')
                await asyncio.sleep(2)


queue_stream = RedisTaskQueue()
