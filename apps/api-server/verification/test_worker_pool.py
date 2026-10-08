"""Logical worker limits against a guarded disposable PostgreSQL database."""
import asyncio
import unittest
from uuid import uuid4
import test_report_results as fixture
from sqlalchemy import select, update
from app.db import engine, schema as db
from app.models.job import Job, JobStatus
from app.services import services
from app.repositories.batch_queue import BatchQueueRepository
from app.api.batch_queue import QueueTaskInput
from app.repositories.filter_profiles import reserve_options_runner, reserve_preflight_runners, PreflightUnavailable
from app.worker_pool import apply_pool, assignment_allowed, initialize_pool, pool_status, PoolError, KEY


class PoolTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        async with engine.begin() as connection:
            await connection.run_sync(db.metadata.drop_all)
            await connection.run_sync(db.metadata.create_all)
        await services.users.create('worker-test', 'Worker test password')
        await initialize_pool()
        for number in range(1, 11):
            await services.runners.register(runner_id=f'playwright-{number}', name='Fixture', socket_id=f'fixture-{number}')

    async def asyncTearDown(self):
        await engine.dispose()

    def job(self, runner):
        return Job(runnerId=runner, sessionId=uuid4(), filters={'states': ['State'], 'rtos': ['Office']})

    async def test_limits_one_five_ten_keep_containers_connected(self):
        for count in (1, 5, 10):
            state = await apply_pool(count)
            self.assertEqual(state['mode'], 'logical')
            self.assertEqual(state['runningCount'], 10)
            self.assertEqual(len(await services.runners.list()), count)
            async with engine.begin() as connection:
                self.assertTrue(await assignment_allowed(connection, f'playwright-{count}'))
                self.assertFalse(await assignment_allowed(connection, 'playwright-11'))
                if count < 10:
                    self.assertFalse(await assignment_allowed(connection, f'playwright-{count + 1}'))
        for value in (0, 11, True, 1.5, '2'):
            with self.assertRaises(PoolError):
                await apply_pool(value)

    async def test_shrink_preserves_busy_job_and_can_grow(self):
        assigned = await services.jobs.assign(self.job('playwright-8'))
        with self.assertRaises(PoolError):
            await apply_pool(5)
        self.assertEqual((await pool_status())['desiredCount'], 10)
        self.assertEqual((await services.jobs.get(assigned.id)).status, JobStatus.QUEUED)
        await services.jobs.transition_status(assigned.id, JobStatus.CANCELLED)
        await services.runners.release_job('playwright-8', str(assigned.id))
        await apply_pool(5)
        self.assertEqual((await apply_pool(8))['desiredCount'], 8)

    async def test_parallel_direct_jobs_cannot_bypass_global_limit_with_custom_ids(self):
        await apply_pool(1)
        ids = [f'external-{number}' for number in range(8)]
        for runner in ids:
            await services.runners.register(runner_id=runner, name='Fixture', socket_id=runner)
        results = await asyncio.wait_for(asyncio.gather(*(services.jobs.assign(self.job(runner)) for runner in ids)), 15)
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual((await pool_status())['activeCount'], 1)

    async def test_parallel_queues_share_capacity_and_claim_only_once(self):
        await apply_pool(1)
        queue = BatchQueueRepository()
        sessions = [uuid4(), uuid4()]
        for runner in ('external-a', 'external-b'):
            await services.runners.register(runner_id=runner, name='Fixture', socket_id=runner)
        task = QueueTaskInput(name='Office', filters={'states': ['State'], 'rtos': ['Office']})
        for session in sessions:
            await queue.start(session, 'worker-test', [task], 1)
        results = await asyncio.wait_for(asyncio.gather(
            queue.claim(sessions[0], 'worker-test', 'external-a'),
            queue.claim(sessions[1], 'worker-test', 'external-b')), 15)
        self.assertEqual(sum(result['type'] == 'assigned' for result in results), 1)
        self.assertEqual((await pool_status())['activeCount'], 1)

    async def test_disabled_worker_and_planning_reservations_obey_limit(self):
        await apply_pool(1)
        with self.assertRaises(ValueError):
            await services.jobs.assign(self.job('playwright-2'))
        with self.assertRaises(PreflightUnavailable):
            async with reserve_options_runner('playwright-2', 'worker-test'):
                self.fail('Disabled worker reserved')
        await services.runners.register(runner_id='external', name='Fixture', socket_id='external')
        async with reserve_options_runner('playwright-1', 'worker-test'):
            self.assertIsNone(await services.jobs.assign(self.job('external')))
        self.assertIsNotNone(await services.jobs.assign(self.job('external')))

    async def test_preflight_reservation_blocks_unsafe_shrink(self):
        async with reserve_preflight_runners(['playwright-8'], 'worker-test'):
            with self.assertRaises(PoolError):
                await apply_pool(5)
        self.assertEqual((await apply_pool(5))['desiredCount'], 5)

    async def test_restart_keeps_selected_count_and_queue_cap(self):
        await apply_pool(5)
        await initialize_pool(reset_phase=True)
        self.assertEqual((await pool_status())['desiredCount'], 5)
        async with engine.begin() as connection:
            await connection.execute(update(db.app_settings).where(db.app_settings.c.key == KEY).values(
                value={'desiredCount': 5, 'phase': 'applying'}))
        async with engine.begin() as connection:
            self.assertFalse(await assignment_allowed(connection, 'playwright-1'))
        with self.assertRaises(PoolError):
            await apply_pool(6)


if __name__ == '__main__':
    unittest.main(verbosity=2)
