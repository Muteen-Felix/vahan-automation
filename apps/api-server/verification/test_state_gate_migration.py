"""Migration 0016: runner-state revision, preflight gate generation, check sequence (PLAN_STATE_VAHAN MG1-MG3).

Runs against a disposable ``vahan_migration_*_test`` database; the schema is dropped on every test.
VAHAN_STATE_MIGRATION_TEST_DATABASE=vahan_migration_state_test python -m pytest verification/test_state_gate_migration.py
"""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import unittest

from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
target = os.environ.get('VAHAN_STATE_MIGRATION_TEST_DATABASE', '')
if not target.startswith('vahan_migration_') or not target.endswith('_test'):
    raise RuntimeError('Use a disposable vahan_migration_*_test database.')
os.environ['DATABASE_URL'] = make_url(os.environ['DATABASE_URL']).set(database=target).render_as_string(hide_password=False)

from sqlalchemy import insert, text
from app.db import engine, schema as db
from app.repositories.postgres import now

PREVIOUS = '0015_remove_daily_schedules'
TARGET = '0016_state_revision_gate_gen'
LEGACY = '0012_auth_session_limits'


async def migrate(direction, revision):
    await engine.dispose()
    result = await asyncio.to_thread(subprocess.run, [sys.executable, '-m', 'alembic', direction, revision],
        cwd=root, capture_output=True, text=True, env=os.environ.copy())
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)


async def scalar(sql):
    async with engine.connect() as connection:
        return await connection.scalar(text(sql))


async def has_revision_column():
    return bool(await scalar("SELECT count(*) FROM information_schema.columns WHERE table_name='browser_states' AND column_name='revision'"))


async def has_sequence():
    return bool(await scalar("SELECT count(*) FROM pg_class WHERE relkind='S' AND relname='ui_health_check_seq'"))


class StateGateMigrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        async with engine.begin() as connection:
            await connection.execute(text('DROP SCHEMA public CASCADE'))
            await connection.execute(text('CREATE SCHEMA public'))

    async def asyncTearDown(self):
        await engine.dispose()

    async def seed_state(self):
        async with engine.begin() as connection:
            await connection.execute(insert(db.users).values(username='migration-owner', password_hash='fixture',
                role='admin', active=True, profile={}, created_at=now()))
            await connection.execute(text(
                "INSERT INTO browser_states (runner_id, encrypted_state, updated_at) VALUES ('legacy-runner', :blob, now())"),
                {'blob': b'encrypted'})

    async def test_upgrade_from_previous_head_keeps_rows_at_revision_zero_and_adds_the_sequence(self):   # MG1/MG2
        await migrate('upgrade', PREVIOUS)
        self.assertFalse(await has_revision_column())
        self.assertFalse(await has_sequence())
        await self.seed_state()
        await migrate('upgrade', TARGET)
        self.assertTrue(await has_revision_column())
        self.assertTrue(await has_sequence())
        self.assertEqual(await scalar("SELECT revision FROM browser_states WHERE runner_id='legacy-runner'"), 0)
        first = await scalar("SELECT nextval('ui_health_check_seq')")
        second = await scalar("SELECT nextval('ui_health_check_seq')")
        self.assertGreater(second, first)
        self.assertTrue(await scalar(
            "SELECT count(*) FROM information_schema.columns WHERE table_name='ui_preflight_checks' AND column_name='gate_generation'"))
        self.assertEqual(await scalar("SELECT column_default FROM information_schema.columns "
            "WHERE table_name='ui_preflight_checks' AND column_name='gate_generation'"), '0')

    async def test_upgrade_from_the_first_release_head_and_repeating_it_is_safe(self):                  # MG2
        await migrate('upgrade', LEGACY)
        await self.seed_state()
        await migrate('upgrade', 'head')
        self.assertEqual(await scalar("SELECT revision FROM browser_states WHERE runner_id='legacy-runner'"), 0)
        await migrate('upgrade', 'head')                       # nothing to do, nothing breaks
        self.assertEqual(await scalar('SELECT version_num FROM alembic_version'), TARGET)

    async def test_downgrade_is_available_but_not_needed_for_application_rollback(self):                # MG3
        await migrate('upgrade', TARGET)
        await migrate('downgrade', PREVIOUS)
        self.assertFalse(await has_revision_column())
        self.assertFalse(await has_sequence())
        await migrate('upgrade', TARGET)
        self.assertTrue(await has_revision_column())


if __name__ == '__main__':
    unittest.main(verbosity=2)
