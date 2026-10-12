"""Verify run history only in an explicitly named disposable test database."""
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4

from sqlalchemy.engine import make_url

test_database = os.environ.get('VAHAN_HISTORY_TEST_DATABASE', '')
if not test_database.startswith('vahan_history_') or not test_database.endswith('_test'):
    raise RuntimeError('Use a disposable vahan_history_*_test database.')
os.environ['DATABASE_URL'] = make_url(os.environ['DATABASE_URL']).set(database=test_database).render_as_string(hide_password=False)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
subprocess.run([sys.executable, '-m', 'app.migrate'], check=True)

from sqlalchemy import delete, insert, update
from app.api.batch_queue import QueueTaskInput
from app.db import engine, schema as db
from app.main import fastapi_app
from app.repositories.batch_queue import BatchQueueRepository
from app.repositories.run_history import list_runs
from app.repositories.run_schedules import PREFIX as SCHEDULE_PREFIX, RunScheduleRepository
from app.security import issue_access_token
from app.services import services


async def get(path, headers=None):
    path, _, query = path.partition('?')
    messages, delivered = [], False
    scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.3'},
        'http_version': '1.1', 'method': 'GET', 'scheme': 'http', 'path': path,
        'raw_path': path.encode(), 'query_string': query.encode(), 'root_path': '',
        'server': ('test', 80), 'client': ('127.0.0.1', 1234),
        'headers': [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]}
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {'type': 'http.request', 'body': b'', 'more_body': False}
        await asyncio.Event().wait()
    async def send(message):
        messages.append(message)
    await asyncio.wait_for(fastapi_app(scope, receive, send), 5)
    status = next(message['status'] for message in messages if message['type'] == 'http.response.start')
    return status, json.loads(b''.join(message.get('body', b'') for message in messages if message['type'] == 'http.response.body'))


class RunHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        async with engine.begin() as connection:
            for table in (db.batch_queue_tasks, db.batch_queue_sessions, db.report_sessions, db.app_settings):
                await connection.execute(delete(table))
        self.owner = 'history-' + str(uuid4())
        await services.users.bootstrap(self.owner, 'history-test-password-long')
        self.queue = BatchQueueRepository()
        self.tasks = [QueueTaskInput(name='Office ' + str(index), filters={
            'states': ['State A'], 'rtos': ['Office ' + str(index)],
            'fromYear': '2026', 'toYear': '2026'}) for index in (1, 2)]

    async def asyncTearDown(self):
        await engine.dispose()

    async def start(self, profile=None, name=None):
        session_id = uuid4()
        await self.queue.start(session_id, self.owner, self.tasks, 2,
                               profile_id=profile, filter_name=name)
        return session_id

    async def test_counts_sessions_and_keeps_original_names_across_retries_and_deletion(self):
        profile = uuid4()
        first = await self.start(profile, 'Original filter')
        await self.queue.start(first, self.owner, self.tasks, 2,
                               profile_id=profile, filter_name='Renamed filter')
        second = await self.start(profile, 'Renamed filter')
        other = await self.start(uuid4(), 'Original filter')
        result = await list_runs(0, 1)
        self.assertEqual(result['total'], 3)
        self.assertEqual(result['runs'][0]['sessionId'], str(other))
        self.assertEqual(result['runs'][0]['runNumber'], 1)
        page = await list_runs(1, 1)
        self.assertEqual(page['runs'][0]['sessionId'], str(second))
        self.assertEqual((page['runs'][0]['runNumber'], page['runs'][0]['totalRuns']), (2, 2))
        async with engine.begin() as connection:
            await connection.execute(delete(db.batch_queue_sessions).where(db.batch_queue_sessions.c.session_id == str(first)))
        rows = (await list_runs())['runs']
        original = next(row for row in rows if row['sessionId'] == str(first))
        self.assertEqual(original['filterName'], 'Original filter')
        self.assertEqual(original['status'], 'UNKNOWN')
        self.assertIsNone(original['totalCases'], 'Do not invent counts for queues removed before progress was archived')
        self.assertEqual((original['runNumber'], original['totalRuns']), (1, 2))
        self.assertEqual(len(rows), 3)

    async def test_legacy_schedule_name_survives_schedule_deletion(self):
        session_id = await self.start()
        profile, schedule_id = uuid4(), uuid4()
        async with engine.begin() as connection:
            await connection.execute(update(db.batch_queue_tasks).where(
                db.batch_queue_tasks.c.session_id == str(session_id), db.batch_queue_tasks.c.position == 0
            ).values(status='COMPLETED', attempts=3))
            await connection.execute(update(db.batch_queue_sessions).where(
                db.batch_queue_sessions.c.session_id == str(session_id)).values(status='PAUSED'))
            await connection.execute(insert(db.app_settings).values(key=SCHEDULE_PREFIX + str(schedule_id), value={
                'owner': self.owner, 'profileId': str(profile), 'profileName': 'Legacy saved filter',
                'status': 'STOPPED', 'sessionId': None, 'lastSessionId': str(session_id)}))
        self.assertEqual((await list_runs())['runs'][0]['filterName'], 'Legacy saved filter')
        await RunScheduleRepository().delete(schedule_id, self.owner)
        result = await list_runs()
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['runs'][0]['filterName'], 'Legacy saved filter')
        row = result['runs'][0]
        self.assertEqual((row['processed'], row['totalCases'], row['withData'], row['pending']), (1, 2, 1, 1))
        self.assertEqual(row['status'], 'STOPPED')

    async def test_live_progress_status_and_counts_do_not_count_retry_attempts(self):
        profile = uuid4()
        session_id = await self.start(profile, 'Same day filter')
        second = await self.start(profile, 'Same day filter')
        async with engine.begin() as connection:
            await connection.execute(update(db.batch_queue_tasks).where(
                db.batch_queue_tasks.c.session_id == str(session_id), db.batch_queue_tasks.c.position == 0
            ).values(status='NO_DATA', attempts=4))
            await connection.execute(update(db.batch_queue_tasks).where(
                db.batch_queue_tasks.c.session_id == str(session_id), db.batch_queue_tasks.c.position == 1
            ).values(status='PROCESSING', attempts=3))
        rows = (await list_runs())['runs']
        self.assertEqual(len(rows), 2, 'Two runs on one day stay separate')
        row = next(row for row in rows if row['sessionId'] == str(session_id))
        self.assertEqual((row['processed'], row['totalCases'], row['noData'], row['running']), (1, 2, 1, 1))
        self.assertEqual(row['status'], 'RUNNING')
        self.assertIsNone(row['finishedAt'])
        async with engine.begin() as connection:
            await connection.execute(update(db.batch_queue_tasks).where(
                db.batch_queue_tasks.c.session_id == str(session_id), db.batch_queue_tasks.c.position == 1
            ).values(status='FAILED'))
            await connection.execute(update(db.app_settings).where(
                db.app_settings.c.key == 'batch-retry-policy:' + str(session_id)
            ).values(value={'phase':'DONE'}))
            await connection.execute(update(db.batch_queue_tasks).where(
                db.batch_queue_tasks.c.session_id == str(second)
            ).values(status='COMPLETED'))
        rows = (await list_runs())['runs']
        row = next(row for row in rows if row['sessionId'] == str(session_id))
        self.assertEqual((row['processed'], row['failed'], row['pending'], row['running']), (2, 1, 0, 0))
        self.assertEqual(row['status'], 'COMPLETED_WITH_ERRORS')
        self.assertIsNotNone(row['finishedAt'])
        self.assertEqual(next(row for row in rows if row['sessionId'] == str(second))['status'], 'COMPLETED')

    async def test_failed_cases_pending_recovery_do_not_mark_run_complete(self):
        session_id = await self.start(uuid4(), 'Recovery filter')
        async with engine.begin() as connection:
            await connection.execute(update(db.batch_queue_tasks).where(
                db.batch_queue_tasks.c.session_id == str(session_id)).values(status='FAILED'))
        row = (await list_runs())['runs'][0]
        self.assertEqual(row['status'], 'RUNNING')
        self.assertIsNone(row['finishedAt'])

    async def test_unknown_old_run_is_not_given_an_invented_filter_name(self):
        session_id = await self.start()
        async with engine.begin() as connection:
            await connection.execute(update(db.batch_queue_sessions).where(
                db.batch_queue_sessions.c.session_id == str(session_id)).values(
                    created_at=datetime(2026, 10, 12, 2, 30, tzinfo=timezone.utc)))
        row = (await list_runs())['runs'][0]
        self.assertEqual(row['filterName'], 'Unnamed filter')
        self.assertEqual(row['startedAt'], '2026-10-12T02:30:00+00:00')

    async def test_repeating_schedule_preserves_previous_legacy_run(self):
        previous = await self.start()
        profile, schedule_id = uuid4(), uuid4()
        async with engine.begin() as connection:
            await connection.execute(insert(db.app_settings).values(key=SCHEDULE_PREFIX + str(schedule_id), value={
                'id': str(schedule_id), 'owner': self.owner, 'profileId': str(profile),
                'profileName': 'Repeating filter', 'enabled': True, 'sessionId': None,
                'lastSessionId': str(previous), 'status': 'COMPLETED',
                'nextRunAt': '2026-01-01T00:00:00+00:00'}))
        scheduled = await RunScheduleRepository().begin_run(schedule_id)
        await self.queue.start(scheduled['sessionId'], self.owner, self.tasks, 2,
                               profile_id=profile, filter_name='Repeating filter')
        async with engine.begin() as connection:
            await connection.execute(delete(db.app_settings).where(db.app_settings.c.key == SCHEDULE_PREFIX + str(schedule_id)))
        result = await list_runs()
        self.assertEqual(result['total'], 2)
        self.assertEqual([row['runNumber'] for row in result['runs']], [2, 1])
        self.assertTrue(all(row['filterName'] == 'Repeating filter' for row in result['runs']))

    async def test_api_requires_admin_and_validates_pagination(self):
        await self.start(uuid4(), 'Electric two-wheelers')
        session = await services.users.create_session(self.owner)
        token = issue_access_token(self.owner, session)
        headers = {'Authorization': 'Bearer ' + token}
        self.assertEqual((await get('/api/annual-reports/run-history'))[0], 401)
        status, body = await get('/api/annual-reports/run-history', headers)
        self.assertEqual(status, 200)
        self.assertEqual(body['runs'][0]['filterName'], 'Electric two-wheelers')
        self.assertEqual((await get('/api/annual-reports/run-history?limit=101', headers))[0], 422)
        async with engine.begin() as connection:
            await connection.execute(update(db.users).where(db.users.c.username == self.owner).values(role='user'))
        self.assertEqual((await get('/api/annual-reports/run-history', headers))[0], 403)


if __name__ == '__main__':
    unittest.main()
