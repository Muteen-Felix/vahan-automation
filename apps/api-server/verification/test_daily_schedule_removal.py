"""Migration 0015 removes saved Daily schedules and nothing else (PLAN D-35, T15b).

Runs against a disposable ``vahan_migration_*_test`` database; the schema is dropped on every test.
"""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4

from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
target = os.environ.get('VAHAN_DAILY_MIGRATION_TEST_DATABASE', '')
if not target.startswith('vahan_migration_') or not target.endswith('_test'):
    raise RuntimeError('Use a disposable vahan_migration_*_test database.')
os.environ['DATABASE_URL'] = make_url(os.environ['DATABASE_URL']).set(database=target).render_as_string(hide_password=False)

from sqlalchemy import insert, select, text
from app.db import engine, schema as db
from app.repositories.postgres import now
from app.repositories.run_history import list_runs
from app.repositories.run_schedules import PREFIX

AUDIT_KEY = 'migration-audit:0015_remove_daily_schedules'
PREVIOUS = '0014_postgresql_task_claims'
TARGET = '0015_remove_daily_schedules'


async def migrate(direction, revision):
    await engine.dispose()
    result = await asyncio.to_thread(subprocess.run, [sys.executable, '-m', 'alembic', direction, revision],
        cwd=root, capture_output=True, text=True, env=os.environ.copy())
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout + result.stderr


async def rows(sql):
    async with engine.connect() as connection:
        return [tuple(row) for row in await connection.execute(text(sql))]


def schedule(repeat, name, *, status='WAITING', session_id=None, last_session_id=None, **extra):
    return {'version': 1, 'id': str(uuid4()), 'owner': 'migration-owner', 'profileId': str(uuid4()), 'profileName': name,
            'profileRevision': 1, 'definition': {'secret-ish': 'filter definition must not be copied'}, 'year': 2026,
            'startsAt': '2026-10-14T02:30:00+00:00', 'nextRunAt': '2026-10-14T02:30:00+00:00',
            'timeZone': 'Asia/Ho_Chi_Minh', 'repeat': repeat, 'enabled': True, 'status': status,
            'sessionId': session_id, 'lastSessionId': last_session_id, 'total': 4, 'done': 2, 'withData': 1,
            'noData': 1, 'failed': 0, 'updatedAt': '2026-10-13T08:00:00+00:00', 'lastFinishedAt': None, **extra}


class DailyScheduleRemovalTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        async with engine.begin() as connection:
            await connection.execute(text('DROP SCHEMA public CASCADE'))
            await connection.execute(text('CREATE SCHEMA public'))
        await migrate('upgrade', PREVIOUS)

    async def asyncTearDown(self):
        await engine.dispose()

    async def seed(self):
        stamp = now()
        sessions = {name: str(uuid4()) for name in ('daily-done', 'daily-paused', 'daily-running', 'once', 'monthly')}
        async with engine.begin() as connection:
            await connection.execute(insert(db.users).values(username='migration-owner', password_hash='fixture',
                role='admin', active=True, profile={}, created_at=stamp))
            for name, sid in sessions.items():
                await connection.execute(insert(db.report_sessions).values(id=sid, owner_username='migration-owner', created_at=stamp))
                await connection.execute(insert(db.batch_queue_sessions).values(session_id=sid, owner_username='migration-owner',
                    status='RUNNING' if name == 'daily-running' else 'PAUSED', total=4, max_workers=2,
                    created_at=stamp, updated_at=stamp))
                for position, state in enumerate(['COMPLETED', 'NO_DATA', 'PENDING', 'PROCESSING']):
                    job_id = str(uuid4())
                    await connection.execute(insert(db.jobs).values(id=job_id, owner_username='migration-owner', session_id=sid,
                        runner_id='fixture-runner', status='ASSIGNED' if state == 'PROCESSING' else state,
                        filters={'states': ['State'], 'rtos': [str(position)]}, payload={'fixture': position},
                        created_at=stamp, updated_at=stamp))
                    await connection.execute(insert(db.batch_queue_tasks).values(session_id=sid, position=position,
                        scenario_name=f'Office {position}', filters={'states': ['State'], 'rtos': [str(position)]},
                        status=state, attempts=position, failures=0, runner_id='fixture-runner', job_id=job_id, updated_at=stamp))
        values = {
            'daily-done': schedule('daily', 'Daily finished', status='COMPLETED', last_session_id=sessions['daily-done']),
            'daily-paused': schedule('daily', 'Daily paused', status='PAUSED', session_id=sessions['daily-paused']),
            'daily-running': schedule('daily', 'Daily running', status='RUNNING', session_id=sessions['daily-running']),
            'once': schedule('once', 'Once schedule', status='COMPLETED', last_session_id=sessions['once'], nextRunAt=None),
            'monthly': schedule('monthly', 'Monthly schedule', session_id=None, last_session_id=sessions['monthly'],
                                annualSeriesId='series-fixture'),
        }
        async with engine.begin() as connection:
            for value in values.values():
                await connection.execute(insert(db.app_settings).values(key=PREFIX + value['id'], value=value))
            await connection.execute(insert(db.app_settings).values(key=PREFIX + 'odd-non-object', value=[]))
            await connection.execute(insert(db.app_settings).values(key='batch-retry-policy:' + sessions['once'],
                value={'phase': 'DONE'}))
            await connection.execute(insert(db.app_settings).values(key='report-run-history:' + sessions['once'],
                value={'profileId': values['once']['profileId'], 'filterName': 'Existing history name',
                       'startedAt': stamp.isoformat()}))
        return sessions, values

    async def snapshot(self):
        tables = ['users', 'report_sessions', 'batch_queue_sessions', 'batch_queue_tasks', 'jobs']
        return {table: await rows(f'SELECT * FROM {table} ORDER BY 1,2') for table in tables}

    async def test_only_daily_rows_are_deleted_and_history_names_survive(self):
        sessions, values = await self.seed()
        before_tables = await self.snapshot()
        keep_keys = [PREFIX + values['once']['id'], PREFIX + values['monthly']['id'], PREFIX + 'odd-non-object',
                     'batch-retry-policy:' + sessions['once'], 'report-run-history:' + sessions['once']]
        keep_before = await rows("SELECT key, value::text FROM app_settings WHERE key IN ("
            + ','.join(f"'{k}'" for k in keep_keys) + ') ORDER BY key')
        names_before = {run['sessionId']: run['filterName'] for run in (await list_runs(limit=100))['runs']}
        self.assertEqual(names_before[sessions['daily-done']], 'Daily finished')

        output = await migrate('upgrade', TARGET)

        self.assertEqual(await rows('SELECT version_num FROM alembic_version'), [(TARGET,)])
        self.assertIn('deleted 3 Daily schedule(s)', output)
        daily_ids = {values[n]['id'] for n in ('daily-done', 'daily-paused', 'daily-running')}
        for identifier in daily_ids:
            self.assertIn(identifier, output)
        remaining = [r[0] for r in await rows(f"SELECT value->>'repeat' FROM app_settings WHERE key LIKE '{PREFIX}%' "
                                              "AND value->>'repeat' IS NOT NULL ORDER BY 1")]
        self.assertEqual(remaining, ['monthly', 'once'])
        self.assertEqual(await rows("SELECT key, value::text FROM app_settings WHERE key IN ("
            + ','.join(f"'{k}'" for k in keep_keys) + ') ORDER BY key'), keep_before)
        self.assertEqual(await self.snapshot(), before_tables, 'reports, jobs, sessions and attempts must be untouched')
        names_after = {run['sessionId']: run['filterName'] for run in (await list_runs(limit=100))['runs']}
        self.assertEqual({sid: names_after[sid] for sid in (sessions['daily-done'], sessions['daily-paused'],
                                                            sessions['daily-running'])},
                         {sessions['daily-done']: 'Daily finished', sessions['daily-paused']: 'Daily paused',
                          sessions['daily-running']: 'Daily running'})
        self.assertEqual(names_after[sessions['once']], 'Existing history name')
        audit = json.loads((await rows(f"SELECT value::text FROM app_settings WHERE key = '{AUDIT_KEY}'"))[0][0])
        self.assertEqual(audit['count'], 3)
        self.assertEqual({item['id'] for item in audit['removed']}, daily_ids)
        self.assertEqual(audit['keptNonDailySchedules'], 3)  # once, monthly and the non-object fixture row
        self.assertEqual({item['hadActiveSession'] for item in audit['removed']}, {True, False})
        self.assertNotIn('filter definition must not be copied', json.dumps(audit))
        history = json.loads((await rows(f"SELECT value::text FROM app_settings WHERE key = 'report-run-history:{sessions['daily-done']}'"))[0][0])
        self.assertNotIn('definition', history)

    async def test_empty_and_once_monthly_only_databases_are_untouched(self):
        output = await migrate('upgrade', TARGET)
        self.assertIn('deleted 0 Daily schedule(s)', output)
        self.assertEqual(await rows(f"SELECT count(*) FROM app_settings WHERE key = '{AUDIT_KEY}'"), [(0,)])
        await migrate('downgrade', PREVIOUS)
        sessions, values = await self.seed()
        async with engine.begin() as connection:
            for name in ('daily-done', 'daily-paused', 'daily-running'):
                await connection.execute(text('DELETE FROM app_settings WHERE key = :key'), {'key': PREFIX + values[name]['id']})
        before = await rows('SELECT key, value::text FROM app_settings ORDER BY key')
        await migrate('upgrade', TARGET)
        self.assertEqual(await rows('SELECT key, value::text FROM app_settings ORDER BY key'), before)

    async def test_rerun_after_downgrade_merges_audit_and_upgrade_head_is_idempotent(self):
        sessions, values = await self.seed()
        await migrate('upgrade', TARGET)
        first = json.loads((await rows(f"SELECT value::text FROM app_settings WHERE key = '{AUDIT_KEY}'"))[0][0])
        again = await migrate('upgrade', 'head')
        self.assertNotIn('deleted', again)
        await migrate('downgrade', PREVIOUS)
        self.assertEqual(await rows(f"SELECT count(*) FROM app_settings WHERE key = '{AUDIT_KEY}'"), [(1,)],
                         'downgrade must not restore schedules nor remove the audit record')
        extra = schedule('daily', 'Daily restored from an old backup', last_session_id=sessions['once'])
        async with engine.begin() as connection:
            await connection.execute(insert(db.app_settings).values(key=PREFIX + extra['id'], value=extra))
        await migrate('upgrade', TARGET)
        second = json.loads((await rows(f"SELECT value::text FROM app_settings WHERE key = '{AUDIT_KEY}'"))[0][0])
        self.assertEqual(second['count'], first['count'] + 1)
        self.assertEqual(await rows(f"SELECT count(*) FROM app_settings WHERE value->>'repeat' = 'daily'"), [(0,)])


if __name__ == '__main__':
    unittest.main()
