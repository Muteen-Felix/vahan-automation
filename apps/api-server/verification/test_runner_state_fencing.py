"""PLAN_STATE_VAHAN WP-S: runner-state revision fencing (compare-and-swap); disposable DB only.

VAHAN_RESULT_TEST_DATABASE=vahan_results_<name>_test python -m pytest verification/test_runner_state_fencing.py
"""
import asyncio
import json
import unittest
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, insert, select
from starlette.requests import Request

import test_report_results as fixture  # noqa: F401  (guards the database and runs migrations)
from app.api.data import RunnerStateValue, get_browser_state, put_browser_state
from app.config import settings
from app.db import engine, schema as db
from app.repositories.postgres import now
from app.services import services
from cryptography.fernet import Fernet


class RunnerStateFencingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        self.runner = 'state-' + str(uuid4())
        await services.runners.register(runner_id=self.runner, name='Fixture', socket_id=self.runner)
        async with engine.begin() as c:
            await c.execute(delete(db.browser_states).where(db.browser_states.c.runner_id == self.runner))

    async def asyncTearDown(self):
        await engine.dispose()

    def request(self):
        request = Request({'type': 'http', 'headers': []})
        request.state.authenticated_runner = True
        return request

    async def put(self, value, expected=None, runner=None):
        runner = runner or self.runner
        return await put_browser_state(runner, RunnerStateValue(value=value, expectedRevision=expected),
            self.request(), runner)

    async def get(self):
        return await get_browser_state(self.runner, self.request(), self.runner)

    async def stored(self):
        async with engine.connect() as c:
            row = (await c.execute(select(db.browser_states.c.encrypted_state, db.browser_states.c.revision)
                .where(db.browser_states.c.runner_id == self.runner))).first()
        cipher = Fernet(settings.browser_state_key.encode())
        return (json.loads(cipher.decrypt(row[0])), int(row[1])) if row else (None, 0)

    # SA1/SA2
    async def test_get_reports_revision_and_put_advances_it(self):
        self.assertEqual(await self.get(), {'state': None, 'revision': 0})
        self.assertEqual((await self.put({'cookies': ['a']}, expected=0))['revision'], 1)
        self.assertEqual((await self.put({'cookies': ['b']}, expected=1))['revision'], 2)
        self.assertEqual(await self.get(), {'state': {'cookies': ['b']}, 'revision': 2})

    # SA3: two writers holding the same revision; exactly one commits.
    async def test_concurrent_writers_with_same_revision_only_one_commits(self):
        await self.put({'n': 0}, expected=0)
        results = await asyncio.gather(self.put({'n': 'A'}, expected=1), self.put({'n': 'B'}, expected=1),
            return_exceptions=True)
        wins = [r for r in results if isinstance(r, dict)]
        losses = [r for r in results if isinstance(r, HTTPException)]
        self.assertEqual((len(wins), len(losses)), (1, 1))
        self.assertEqual(losses[0].status_code, 409)
        self.assertEqual(losses[0].detail['code'], 'STATE_REVISION_CONFLICT')
        self.assertEqual(losses[0].detail['currentRevision'], 2)
        state, revision = await self.stored()
        self.assertEqual(revision, 2)
        self.assertIn(state, ({'n': 'A'}, {'n': 'B'}))

    # SA4 / T2: the old write is sent first, the new write commits and is acknowledged, the old
    # write commits last. The database must not go back to the old content.
    async def test_late_old_write_cannot_overwrite_newer_state(self):
        await self.put({'v': 'stale-S'}, expected=0)          # revision 1 (what both writers read)
        recovery = await self.put({'v': 'recovered-C'}, expected=1)  # acked: revision 2
        self.assertEqual(recovery['revision'], 2)
        with self.assertRaises(HTTPException) as late:           # heartbeat built from revision 1
            await self.put({'v': 'heartbeat-S'}, expected=1)
        self.assertEqual(late.exception.status_code, 409)
        self.assertEqual(late.exception.detail['currentRevision'], 2)
        self.assertEqual(await self.stored(), ({'v': 'recovered-C'}, 2))

    # SA5
    async def test_missing_row_accepts_only_revision_zero(self):
        with self.assertRaises(HTTPException) as error:
            await self.put({'x': 1}, expected=3)
        self.assertEqual(error.exception.detail['currentRevision'], 0)
        self.assertEqual(await self.stored(), (None, 0))
        self.assertEqual((await self.put({'x': 1}, expected=0))['revision'], 1)

    # SA6: a client that predates fencing still works, but advances the revision.
    async def test_unconditional_write_advances_revision_and_fences_old_reader(self):
        await self.put({'v': 1}, expected=0)
        legacy = await self.put({'v': 'legacy'})
        self.assertEqual(legacy['revision'], 2)
        with self.assertRaises(HTTPException) as error:
            await self.put({'v': 'fenced-writer'}, expected=1)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual((await self.stored())[0], {'v': 'legacy'})

    # A row written before the migration has revision 0 (column default) and must be writable.
    async def test_pre_migration_row_with_revision_zero_is_writable(self):
        cipher = Fernet(settings.browser_state_key.encode())
        async with engine.begin() as c:
            await c.execute(insert(db.browser_states).values(runner_id=self.runner,
                encrypted_state=cipher.encrypt(json.dumps({'old': True}).encode()), updated_at=now()))
        self.assertEqual(await self.get(), {'state': {'old': True}, 'revision': 0})
        self.assertEqual((await self.put({'new': True}, expected=0))['revision'], 1)

    # SA7: existing guards are unchanged.
    async def test_access_and_size_guards_are_unchanged(self):
        with self.assertRaises(HTTPException) as error:
            await put_browser_state('unregistered-' + str(uuid4()), RunnerStateValue(value={}), self.request(),
                'unregistered-' + str(uuid4()))
        self.assertEqual(error.exception.status_code, 403)
        with self.assertRaises(HTTPException) as large:
            await self.put({'blob': 'x' * (5 * 1024 * 1024 + 1)}, expected=0)
        self.assertEqual(large.exception.status_code, 413)
        self.assertEqual(await self.stored(), (None, 0))
        wrong = Request({'type': 'http', 'headers': []})
        wrong.state.authenticated_runner = True
        with self.assertRaises(HTTPException) as mismatch:
            await put_browser_state(self.runner, RunnerStateValue(value={}), wrong, 'someone-else')
        self.assertEqual(mismatch.exception.status_code, 403)


if __name__ == '__main__':
    unittest.main(verbosity=2)
