"""Verify legacy upgrades and audit preservation on a disposable database."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import unittest

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

url = make_url(os.environ.get('DATABASE_URL', 'postgresql://localhost/'))
if url.database != 'vahan_remove_soc_test':
    raise RuntimeError('Use the disposable vahan_remove_soc_test database.')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def migrate(revision, direction='upgrade'):
    subprocess.run([sys.executable, '-m', 'alembic', direction, revision],
                   cwd=ROOT, check=True, capture_output=True)


class RemovalMigrationTests(unittest.TestCase):
    def test_upgrade_removes_only_delivery_queue_and_keeps_audit(self):
        migrate('0014_merge_capacity_soc')

        async def seed():
            engine = create_async_engine(url)
            try:
                async with engine.begin() as connection:
                    await connection.execute(text("""INSERT INTO soc_outbox
                        (id,payload,created_at,delivered,attempts,next_attempt_at)
                        VALUES ('queued-event','{}',now(),false,0,now())"""))
                    await connection.execute(text("""INSERT INTO audit_events
                        (id,actor,event,payload,created_at)
                        VALUES ('retained-audit','admin','fixture','{}',now())"""))
            finally:
                await engine.dispose()

        async def check(expected_revision, queue_exists):
            engine = create_async_engine(url)
            try:
                async with engine.connect() as connection:
                    self.assertEqual(await connection.scalar(text(
                        'SELECT version_num FROM alembic_version')), expected_revision)
                    self.assertEqual(bool(await connection.scalar(text(
                        "SELECT to_regclass('public.soc_outbox')"))), queue_exists)
                    self.assertEqual(await connection.scalar(text(
                        "SELECT count(*) FROM audit_events WHERE id='retained-audit'")), 1)
                    for table in ('users', 'auth_sessions', 'user_mfa', 'main_reports', 'jobs'):
                        self.assertIsNotNone(await connection.scalar(text(
                            'SELECT to_regclass(:table)'), {'table': 'public.' + table}))
            finally:
                await engine.dispose()

        asyncio.run(seed())
        migrate('head')
        asyncio.run(check('0016_remove_soc', False))
        migrate('0014_merge_capacity_soc', 'downgrade')
        asyncio.run(check('0014_merge_capacity_soc', True))
        migrate('head')
        asyncio.run(check('0016_remove_soc', False))
