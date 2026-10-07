"""Physical-pool coordination against a guarded disposable database; Docker is mocked."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
import test_report_results as fixture
from sqlalchemy import delete, select, update
from app.db import engine, schema as db
from app.models.job import Job
from app.services import services
from app.worker_pool import apply_pool, assignment_allowed, initialize_pool, pool_value, PoolError, KEY

class FakeController:
    def __init__(self): self.count = 10; self.changes = []
    async def request(self, count=None):
        if count is not None:
            self.count = count; self.changes.append(count)
            for number in range(1, count + 1):
                await services.runners.register(runner_id=f'playwright-{number}', name='Fixture', socket_id=f'fixture-{number}')
        return {'runningCount': self.count, 'workers': [{'number': number,
            'service': 'runner' if number == 1 else f'runner-{number}', 'running': number <= self.count}
            for number in range(1, 11)]}

class PoolTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        self.patcher = patch('app.worker_pool.settings', SimpleNamespace(worker_controller_url='mock', runner_token='mock'))
        self.patcher.start()
        async with engine.begin() as connection:
            await connection.execute(delete(db.runners))
            await connection.execute(delete(db.jobs))
            await connection.execute(delete(db.app_settings).where(db.app_settings.c.key == KEY))
        await initialize_pool()
        for number in range(1, 11):
            await services.runners.register(runner_id=f'playwright-{number}', name='Fixture', socket_id=f'fixture-{number}')
        self.client = FakeController()
    async def asyncTearDown(self):
        self.patcher.stop(); await engine.dispose()
    async def test_shrink_grow_registry_and_assignment_gate(self):
        result = await apply_pool(5, self.client)
        self.assertEqual(result['runningCount'], 5)
        self.assertEqual(len(await services.runners.list()), 5)
        async with engine.connect() as connection:
            self.assertTrue(await assignment_allowed(connection, 'playwright-5'))
            self.assertFalse(await assignment_allowed(connection, 'playwright-6'))
        self.assertEqual((await apply_pool(8, self.client))['runningCount'], 8)
        self.assertEqual(len(await services.runners.list()), 8)
    async def test_busy_run_is_not_stopped(self):
        await services.jobs.assign(Job(runnerId='playwright-8', sessionId=uuid4(), filters={'states': ['State'], 'rtos': ['Office']}))
        with self.assertRaises(PoolError): await apply_pool(5, self.client)
        self.assertEqual(self.client.changes, [])
        self.assertEqual(len(await services.runners.list()), 10)
    async def test_failed_controller_restores_assignment_policy(self):
        original = self.client.request
        async def failed(count=None):
            if count is not None: raise PoolError('Fixture failure')
            return await original()
        self.client.request = failed
        with self.assertRaises(PoolError): await apply_pool(5, self.client)
        async with engine.connect() as connection:
            self.assertEqual((await pool_value(connection))['desiredCount'], 10)
            self.assertTrue(await assignment_allowed(connection, 'playwright-10'))
    async def test_reconciler_does_not_restore_an_old_selected_count(self):
        await apply_pool(5, self.client)
        result = await apply_pool(10, self.client, reconcile=True)
        self.assertEqual(result['runningCount'], 5)
        self.assertEqual(self.client.changes, [5])
    async def test_another_pool_update_blocks_assignment_and_resizing(self):
        async with engine.begin() as connection:
            await connection.execute(update(db.app_settings).where(db.app_settings.c.key == KEY).values(
                value={'desiredCount': 7, 'phase': 'applying'}))
        with self.assertRaises(PoolError): await apply_pool(5, self.client)
        self.assertEqual(self.client.changes, [])
        async with engine.connect() as connection:
            self.assertFalse(await assignment_allowed(connection, 'playwright-1'))

if __name__ == '__main__': unittest.main(verbosity=2)
