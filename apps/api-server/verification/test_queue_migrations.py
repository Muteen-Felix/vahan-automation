"""Real populated PostgreSQL upgrades/downgrades across 0012, 0013 and 0014."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4

from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
target = os.environ.get('VAHAN_QUEUE_MIGRATION_TEST_DATABASE', '')
if not target.startswith('vahan_migration_') or not target.endswith('_test'):
    raise RuntimeError('Use a disposable vahan_migration_*_test database.')
os.environ['DATABASE_URL'] = make_url(os.environ['DATABASE_URL']).set(database=target).render_as_string(hide_password=False)

from sqlalchemy import insert, text, update
from app.db import engine, schema as db
from app.repositories.postgres import now


async def migrate(direction, revision):
    await engine.dispose()
    result = await asyncio.to_thread(subprocess.run,
        [sys.executable, '-m', 'alembic', direction, revision], cwd=root,
        capture_output=True, text=True, env=os.environ.copy())
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)


async def query(sql):
    async with engine.connect() as connection:
        return [tuple(row) for row in await connection.execute(text(sql))]


class QueueMigrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        async with engine.begin() as connection:
            await connection.execute(text('DROP SCHEMA public CASCADE'))
            await connection.execute(text('CREATE SCHEMA public'))
        await migrate('upgrade', '0012_auth_session_limits')

    async def asyncTearDown(self):
        await engine.dispose()

    async def test_empty_database_round_trip_schema_and_default(self):
        for direction, revision, outbox in [
            ('upgrade', '0013_redis_stream_queue', True),
            ('upgrade', '0014_postgresql_task_claims', False),
            ('downgrade', '0013_redis_stream_queue', True),
            ('downgrade', '0012_auth_session_limits', False),
            ('upgrade', '0014_postgresql_task_claims', False),
        ]:
            await migrate(direction, revision)
            self.assertEqual(await query('SELECT version_num FROM alembic_version'), [(revision,)])
            self.assertEqual(bool((await query("SELECT to_regclass('public.queue_outbox')"))[0][0]), outbox)
            self.assertEqual(await query('SELECT count(*) FROM batch_queue_tasks'), [(0,)])
            columns = await query("SELECT column_name FROM information_schema.columns WHERE table_name='auth_sessions'")
            self.assertIn(('expires_at',), columns); self.assertIn(('last_activity_at',), columns)

    async def test_populated_up_down_retains_tasks_attempts_jobs_auth_and_rebuilds_outbox(self):
        stamp = now()
        sessions = [str(uuid4()), str(uuid4())]
        async with engine.begin() as connection:
            await connection.execute(insert(db.users).values(username='migration-owner', password_hash='fixture',
                role='admin', active=True, profile={}, created_at=stamp))
            await connection.execute(insert(db.auth_sessions).values(id='fixture-session', username='migration-owner',
                revoked=False, expires_at=stamp, last_activity_at=stamp, created_at=stamp))
            for sid, status in zip(sessions, ['RUNNING', 'PAUSED']):
                await connection.execute(insert(db.report_sessions).values(id=sid, owner_username='migration-owner', created_at=stamp))
                await connection.execute(insert(db.batch_queue_sessions).values(session_id=sid, owner_username='migration-owner',
                    status=status, total=5, max_workers=3, created_at=stamp, updated_at=stamp))
                for position, state in enumerate(['PENDING', 'PROCESSING', 'COMPLETED', 'NO_DATA', 'FAILED']):
                    job_id = str(uuid4()) if position else None
                    if job_id:
                        await connection.execute(insert(db.jobs).values(id=job_id, owner_username='migration-owner', session_id=sid,
                            runner_id='fixture-runner', status='ASSIGNED' if state == 'PROCESSING' else state,
                            filters={'states': ['State'], 'rtos': [str(position)]}, payload={'migrationFixture': position},
                            created_at=stamp, updated_at=stamp))
                    await connection.execute(insert(db.batch_queue_tasks).values(session_id=sid, position=position, scenario_name=f'Office {position}',
                        filters={'states': ['State'], 'rtos': [str(position)]}, status=state, attempts=position, failures=position // 2,
                        runner_id='fixture-runner' if job_id else None, job_id=job_id, error='fixture failure' if state == 'FAILED' else None, updated_at=stamp))
            await connection.execute(insert(db.app_settings).values(key='automatic-report-schedule:legacy',
                value={'workerCount': 9999, 'sessionId': sessions[0]}))
        tracked = ['users', 'auth_sessions', 'report_sessions', 'batch_queue_tasks', 'jobs', 'app_settings']
        original = {table: await query(f'SELECT * FROM {table} ORDER BY 1,2') for table in tracked}
        expected_outbox = [(sessions[0], 0), (sessions[0], 1)]
        await migrate('upgrade', '0013_redis_stream_queue')
        self.assertEqual(await query('SELECT session_id,position FROM queue_outbox ORDER BY position'), expected_outbox)
        async with engine.begin() as connection:
            await connection.execute(update(db.batch_queue_sessions).values(max_workers=27))
        await migrate('upgrade', '0014_postgresql_task_claims')
        self.assertEqual(await query("SELECT to_regclass('public.queue_outbox')"), [(None,)])
        await migrate('downgrade', '0013_redis_stream_queue')
        self.assertEqual(await query('SELECT session_id,position FROM queue_outbox ORDER BY position'), expected_outbox)
        await migrate('downgrade', '0012_auth_session_limits')
        self.assertEqual(await query('SELECT max_workers FROM batch_queue_sessions ORDER BY session_id'), [(10,), (10,)])
        self.assertEqual(await query("SELECT to_regclass('public.queue_outbox')"), [(None,)])
        constraint = (await query("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_batch_queue_worker_count'"))[0][0]
        self.assertIn('10', constraint)
        default = (await query("SELECT column_default FROM information_schema.columns WHERE table_name='batch_queue_sessions' AND column_name='max_workers'"))[0][0]
        self.assertEqual(default, '10')
        for table in tracked:
            self.assertEqual(await query(f'SELECT * FROM {table} ORDER BY 1,2'), original[table], table)
        await migrate('upgrade', '0014_postgresql_task_claims')
        for table in tracked:
            self.assertEqual(await query(f'SELECT * FROM {table} ORDER BY 1,2'), original[table], table)


if __name__ == '__main__':
    unittest.main(verbosity=2)
