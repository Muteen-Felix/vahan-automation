"""Saved Daily schedules and migrations 0014a (guard) / 0015 (delete) (PLAN D-35, T15b, Q1 = A, strict).

0014a aborts the upgrade, before anything is written, when a Daily schedule still owns a report session
(any non-empty ``sessionId``, whatever its ``status``). 0015 then deletes the remaining Daily schedules and
nothing else. Runs against a disposable ``vahan_migration_*_test`` database; the schema is dropped on every test.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from uuid import uuid4

from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.path.insert(0, str(root.parents[1] / 'scripts'))
target = os.environ.get('VAHAN_DAILY_MIGRATION_TEST_DATABASE', '')
if not target.startswith('vahan_migration_') or not target.endswith('_test'):
    raise RuntimeError('Use a disposable vahan_migration_*_test database.')
os.environ['DATABASE_URL'] = make_url(os.environ['DATABASE_URL']).set(database=target).render_as_string(hide_password=False)

from sqlalchemy import insert, text
from app.db import engine, schema as db
from app.repositories.postgres import now
from app.repositories.run_history import list_runs
from app.repositories.run_schedules import PREFIX
import deployment_guard

AUDIT_KEY = 'migration-audit:0015_remove_daily_schedules'
PREVIOUS = '0014_postgresql_task_claims'
TARGET = '0015_remove_daily_schedules'
MISSING = object()  # the key is absent from the stored JSON document
GUARD_FILE = root / 'migrations' / 'versions' / '0014a_daily_schedule_guard.py'


async def alembic(direction, revision):
    await engine.dispose()
    return await asyncio.to_thread(subprocess.run, [sys.executable, '-m', 'alembic', direction, revision],
        cwd=root, capture_output=True, text=True, env=os.environ.copy())


async def migrate(direction, revision):
    result = await alembic(direction, revision)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout + result.stderr


async def rows(sql):
    async with engine.connect() as connection:
        return [tuple(row) for row in await connection.execute(text(sql))]


async def state_digest():
    """SHA-256 of the full content of every public table (including alembic_version), per table."""
    digest = {}
    for (table,) in await rows("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1"):
        content = await rows(f'SELECT x FROM (SELECT row_to_json(t)::text AS x FROM "{table}" t) s ORDER BY x')
        digest[table] = hashlib.sha256(json.dumps(content).encode()).hexdigest()
    return digest


def schedule(repeat, name, *, status='WAITING', session_id=None, last_session_id=None, drop=(), **extra):
    value = {'version': 1, 'id': str(uuid4()), 'owner': 'migration-owner', 'profileId': str(uuid4()), 'profileName': name,
            'profileRevision': 1, 'definition': {'secret-ish': 'filter definition must not be copied'}, 'year': 2026,
            'startsAt': '2026-10-14T02:30:00+00:00', 'nextRunAt': '2026-10-14T02:30:00+00:00',
            'timeZone': 'Asia/Ho_Chi_Minh', 'repeat': repeat, 'enabled': True, 'status': status,
            'sessionId': session_id, 'lastSessionId': last_session_id, 'total': 4, 'done': 2, 'withData': 1,
            'noData': 1, 'failed': 0, 'updatedAt': '2026-10-13T08:00:00+00:00', 'lastFinishedAt': None, **extra}
    for key in drop:
        value.pop(key)
    return value


class DailyScheduleRemovalTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        async with engine.begin() as connection:
            await connection.execute(text('DROP SCHEMA public CASCADE'))
            await connection.execute(text('CREATE SCHEMA public'))
        await migrate('upgrade', PREVIOUS)

    async def asyncTearDown(self):
        await engine.dispose()

    async def put(self, *documents):
        async with engine.begin() as connection:
            for value in documents:
                await connection.execute(insert(db.app_settings).values(key=PREFIX + value['id'], value=value))

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
        await self.put(*values.values())
        async with engine.begin() as connection:
            await connection.execute(insert(db.app_settings).values(key=PREFIX + 'odd-non-object', value=[]))
            await connection.execute(insert(db.app_settings).values(key='batch-retry-policy:' + sessions['once'],
                value={'phase': 'DONE'}))
            await connection.execute(insert(db.app_settings).values(key='report-run-history:' + sessions['once'],
                value={'profileId': values['once']['profileId'], 'filterName': 'Existing history name',
                       'startedAt': stamp.isoformat()}))
        return sessions, values

    async def blocked_matrix(self):
        """Daily schedules with a session whatever their status; each must stop the upgrade."""
        statuses = ['PREPARING', 'RUNNING', 'PAUSING', 'RESUMING', 'PAUSED', 'ERROR', 'WAITING', 'STOPPED', 'COMPLETED',
                    'COMPLETED_WITH_ERRORS', 'ARCHIVED', 'running', '', None, MISSING]
        cases = {}
        for status in statuses:
            label = f'status={status!r}' if status is not MISSING else 'status missing'
            cases[label] = schedule('daily', f'blocked {label}', session_id=str(uuid4()),
                                    **({'status': status} if status is not MISSING else {}),
                                    drop=('status',) if status is MISSING else ())
        for odd in (' ', 0, False, [], 'x'):
            cases[f'sessionId={odd!r}'] = schedule('daily', f'blocked session {odd!r}', status='RUNNING', session_id=odd)
        await self.put(*cases.values())
        return cases

    # ------------------------------------------------------------------ abort (Q1 = A, strict)
    async def test_daily_schedules_that_own_a_session_abort_the_upgrade_and_change_nothing(self):
        sessions, values = await self.seed()
        matrix = await self.blocked_matrix()
        blocked = {values['daily-paused']['id'], values['daily-running']['id']} | {v['id'] for v in matrix.values()}
        before = await state_digest()
        history_before = await rows("SELECT key FROM app_settings WHERE key LIKE 'report-run-history:%' ORDER BY key")

        result = await alembic('upgrade', TARGET)
        output = result.stdout + result.stderr

        self.assertNotEqual(result.returncode, 0, 'the upgrade must stop')
        self.assertIn('0014a_daily_schedule_guard', output)
        for identifier in blocked:
            self.assertIn(identifier, output)
        self.assertNotIn(values['daily-done']['id'], output, 'a Daily schedule without a session is not blocking')
        self.assertNotIn('filter definition must not be copied', output)
        self.assertEqual(await state_digest(), before, 'no table may change when the upgrade stops')
        self.assertEqual(await rows('SELECT version_num FROM alembic_version'), [(PREVIOUS,)])
        self.assertEqual(await rows(f"SELECT count(*) FROM app_settings WHERE key = '{AUDIT_KEY}'"), [(0,)])
        self.assertEqual(await rows("SELECT key FROM app_settings WHERE key LIKE 'report-run-history:%' ORDER BY key"),
                         history_before)
        # All or nothing: the terminal Daily schedule without a session was not deleted either.
        self.assertEqual(await rows("SELECT count(*) FROM app_settings WHERE value->>'repeat' = 'daily'"),
                         [(2 + 1 + len(matrix),)])
        self.assertEqual(await rows(f"SELECT count(*) FROM app_settings WHERE key = '{PREFIX}{values['daily-done']['id']}'"),
                         [(1,)])

    async def test_release_guard_sql_and_migration_block_exactly_the_same_schedules(self):
        sessions, values = await self.seed()
        matrix = await self.blocked_matrix()
        expected = {values['daily-paused']['id'], values['daily-running']['id']} | {v['id'] for v in matrix.values()}
        # The same fixture also holds schedules that must NOT block: no session (missing/null/empty), once, monthly.
        await self.put(
            schedule('daily', 'no session null', status='RUNNING', session_id=None),
            schedule('daily', 'no session empty', status='PAUSED', session_id=''),
            schedule('daily', 'no session missing', status=None, drop=('sessionId', 'status')),
            schedule('once', 'once with session', status='RUNNING', session_id=str(uuid4())),
            schedule('monthly', 'monthly with session', status='PAUSED', session_id=str(uuid4())))

        keys = await rows(f"SELECT key FROM app_settings WHERE key LIKE 'automatic-report-schedule:%' "
                          f"AND {deployment_guard.DAILY_BLOCKING_SQL}")
        guard_ids = {key.removeprefix(PREFIX) for (key,) in keys}
        evidence = (await rows(deployment_guard.QUERY))[0][0]
        evidence = evidence if isinstance(evidence, dict) else json.loads(evidence)
        output = (await alembic('upgrade', TARGET))
        migration_ids = set(re.findall(r'\bid=(\S+)', output.stdout + output.stderr))

        self.assertEqual(guard_ids, expected)
        self.assertEqual(evidence['blockingDailySchedules'], len(expected))
        self.assertEqual(migration_ids, expected)
        self.assertNotEqual(output.returncode, 0)
        self.assertIn(deployment_guard.DAILY_BLOCKING_SQL, GUARD_FILE.read_text(encoding='utf-8'),
                      'migration and --check-release must use the same SQL text')

    async def test_operator_remediation_then_upgrade_succeeds(self):
        sessions, values = await self.seed()
        first = await alembic('upgrade', TARGET)
        self.assertNotEqual(first.returncode, 0)
        queue_before = await state_digest()
        # What Stop does on the old version: status STOPPED, sessionId cleared.
        async with engine.begin() as connection:
            await connection.execute(text(
                "UPDATE app_settings SET value = CAST(value AS jsonb) || CAST(:patch AS jsonb) WHERE key = ANY(:keys)"),
                {'patch': json.dumps({'status': 'STOPPED', 'sessionId': None}),
                 'keys': [PREFIX + values['daily-paused']['id'], PREFIX + values['daily-running']['id']]})
        output = await migrate('upgrade', TARGET)
        self.assertIn('deleted 3 Daily schedule(s)', output)
        self.assertEqual(await rows('SELECT version_num FROM alembic_version'), [(TARGET,)])
        after = await state_digest()
        for table in ('users', 'report_sessions', 'batch_queue_sessions', 'batch_queue_tasks', 'jobs'):
            self.assertEqual(after[table], queue_before[table], f'{table} must not change')
        self.assertEqual(await rows("SELECT count(*) FROM app_settings WHERE value->>'repeat' = 'daily'"), [(0,)])

    # ------------------------------------------------------------------ delete (schedules without a session)
    async def test_daily_schedules_without_a_session_are_deleted_in_every_status(self):
        sessions, values = await self.seed()
        async with engine.begin() as connection:
            for name in ('daily-paused', 'daily-running'):
                await connection.execute(text('DELETE FROM app_settings WHERE key = :key'),
                                         {'key': PREFIX + values[name]['id']})
        removable = {}
        for status in ('STOPPED', 'COMPLETED', 'COMPLETED_WITH_ERRORS', 'WAITING', 'PAUSED', 'RUNNING', 'ERROR', 'WEIRD', None):
            for label, extra in (('null', {'session_id': None}), ('empty', {'session_id': ''}),
                                 ('missing', {'drop': ('sessionId',)})):
                removable[(status, label)] = schedule('daily', f'removable {status} {label}', status=status, **extra)
        await self.put(*removable.values())
        keep_keys = [PREFIX + values['once']['id'], PREFIX + values['monthly']['id'], PREFIX + 'odd-non-object',
                     'batch-retry-policy:' + sessions['once'], 'report-run-history:' + sessions['once']]
        keep_sql = ("SELECT key, value::text FROM app_settings WHERE key IN ("
                    + ','.join(f"'{k}'" for k in keep_keys) + ') ORDER BY key')
        keep_before = await rows(keep_sql)
        tables_before = await state_digest()
        names_before = {run['sessionId']: run['filterName'] for run in (await list_runs(limit=100))['runs']}
        self.assertEqual(names_before[sessions['daily-done']], 'Daily finished')

        output = await migrate('upgrade', TARGET)

        expected_count = 1 + len(removable)
        self.assertIn(f'deleted {expected_count} Daily schedule(s)', output)
        self.assertEqual(await rows('SELECT version_num FROM alembic_version'), [(TARGET,)])
        remaining = [r[0] for r in await rows(f"SELECT value->>'repeat' FROM app_settings WHERE key LIKE '{PREFIX}%' "
                                              "AND value->>'repeat' IS NOT NULL ORDER BY 1")]
        self.assertEqual(remaining, ['monthly', 'once'])
        self.assertEqual(await rows(keep_sql), keep_before, 'Once/Monthly and unrelated rows are byte-identical')
        tables_after = await state_digest()
        for table in ('users', 'report_sessions', 'batch_queue_sessions', 'batch_queue_tasks', 'jobs'):
            self.assertEqual(tables_after[table], tables_before[table], f'{table} must not change')
        names_after = {run['sessionId']: run['filterName'] for run in (await list_runs(limit=100))['runs']}
        self.assertEqual(names_after[sessions['daily-done']], 'Daily finished')
        self.assertEqual(names_after[sessions['once']], 'Existing history name')
        audit = json.loads((await rows(f"SELECT value::text FROM app_settings WHERE key = '{AUDIT_KEY}'"))[0][0])
        self.assertEqual(audit['count'], expected_count)
        self.assertEqual({item['hadActiveSession'] for item in audit['removed']}, {False})
        self.assertNotIn('filter definition must not be copied', json.dumps(audit))
        history = json.loads((await rows(
            f"SELECT value::text FROM app_settings WHERE key = 'report-run-history:{sessions['daily-done']}'"))[0][0])
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
        async with engine.begin() as connection:
            for name in ('daily-paused', 'daily-running'):
                await connection.execute(text('DELETE FROM app_settings WHERE key = :key'),
                                         {'key': PREFIX + values[name]['id']})
        await migrate('upgrade', TARGET)
        first = json.loads((await rows(f"SELECT value::text FROM app_settings WHERE key = '{AUDIT_KEY}'"))[0][0])
        self.assertEqual(first['count'], 1)
        again = await migrate('upgrade', 'head')
        self.assertNotIn('deleted', again)
        await migrate('downgrade', PREVIOUS)
        self.assertEqual(await rows(f"SELECT count(*) FROM app_settings WHERE key = '{AUDIT_KEY}'"), [(1,)],
                         'downgrade must not restore schedules nor remove the audit record')
        extra = schedule('daily', 'Daily restored from an old backup', last_session_id=sessions['once'])
        await self.put(extra)
        await migrate('upgrade', TARGET)
        second = json.loads((await rows(f"SELECT value::text FROM app_settings WHERE key = '{AUDIT_KEY}'"))[0][0])
        self.assertEqual(second['count'], first['count'] + 1)
        self.assertEqual(await rows("SELECT count(*) FROM app_settings WHERE value->>'repeat' = 'daily'"), [(0,)])


if __name__ == '__main__':
    unittest.main()
