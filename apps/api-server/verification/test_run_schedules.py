"""Exercise unattended orchestration only against a named disposable PostgreSQL DB."""
import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from sqlalchemy.engine import make_url

test_database = os.environ.get('VAHAN_SCHEDULE_TEST_DATABASE', '')
if not test_database.startswith('vahan_schedule_') or not test_database.endswith('_test'):
    raise RuntimeError('Use a disposable vahan_schedule_*_test database.')
os.environ['DATABASE_URL'] = make_url(os.environ['DATABASE_URL']).set(database=test_database).render_as_string(hide_password=False)
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError
from sqlalchemy import insert, select, text, update
from starlette.requests import Request
from app.api.batch_queue import QueueTaskInput
from app.api.run_schedules import current_captchas
from app.db import engine, schema as db
from app.models.filter_profile import ProfileWrite
from app.models.job import Job, JobStatus
from app.models.run_schedule import RunScheduleCreate, RunScheduleResume
from app.repositories.filter_profiles import FilterProfileRepository
from app.repositories.postgres import job_document, release_runner
from app.repositories.run_schedules import RunScheduleRepository, next_daily_run, now
from app.repositories import ui_contract
from app.run_scheduler import automatic_preflight, scheduler_tick, stop_scheduled_run, still_current, checkpoint, queue, LEADER_LOCK
from app.services import services


async def finish(job_id, status):
    async with engine.begin() as connection:
        job = Job.model_validate(await connection.scalar(select(db.jobs.c.payload).where(db.jobs.c.id == job_id)))
        job.status = status
        job.error = 'Fixture failure' if status == JobStatus.FAILED else None
        job.touch()
        await connection.execute(update(db.jobs).where(db.jobs.c.id == job_id).values(
            status=status.value, payload=job_document(job), updated_at=now()))
        await release_runner(connection, job.runner_id, job.id)


class RunScheduleTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        async with engine.begin() as connection:
            await connection.run_sync(db.metadata.drop_all)
            await connection.run_sync(db.metadata.create_all)
            for owner in ['schedule-test', 'another-user']:
                await connection.execute(insert(db.users).values(username=owner, password_hash='fixture',
                    role='user', active=True, profile={}, created_at=now()))
        for number in range(1, 4):
            await services.runners.register(runner_id=f'playwright-{number}', name=f'Worker {number}', socket_id=f'socket-{number}')
        self.repo = RunScheduleRepository()
        self.profile = await FilterProfileRepository().save('schedule-test', ProfileWrite.model_validate({
            'name': 'EV report', 'definition': {'report': {'year': now().year}, 'fields': {
                'delhiNcr': {'values': ['ALL STATES']}, 'states': {'values': ['State']},
                'rtos': {'values': ['Office']}, 'archivedFlags': {'values': ['ACTIVE']}}}}))
        self.tasks = [{'name': f'Office {i}', 'filters': {'states': ['State'], 'rtos': [f'Office {i}'],
            'fromYear': str(now().year), 'toYear': str(now().year), 'autoApply': True}} for i in range(3)]
        self.planner = AsyncMock(return_value={'scenarios': self.tasks})
        self.pool = AsyncMock(return_value={'enabled': False})
        self.events = AsyncMock()
        observed = [{**seed, 'tag': 'button' if seed['tag'] == 'action' else seed['tag'],
            'found': True, 'count': 1, 'inputType': 'text', 'optionsHash': 'fixture'} for seed in ui_contract.SEEDS]
        self.validation = await ui_contract.evaluate({'status': 'PASS', 'observedControls': observed}, 'playwright-1')
        self.gate_id = str(uuid4())
        async with engine.begin() as connection:
            await connection.execute(insert(db.ui_preflight_checks).values(id=self.gate_id,
                owner_username='schedule-test', runner_ids=[f'playwright-{i}' for i in range(1, 4)],
                version_id=self.validation['versionId'], status='PASS', reports=[self.validation], created_at=now()))
        self.preflight = AsyncMock(return_value=self.gate_id)
        self.patches = [patch('app.api.filter_profiles.compile_profile_plan', self.planner),
            patch('app.run_scheduler.apply_pool', self.pool), patch('app.run_scheduler.sio.emit', self.events),
            patch('app.run_scheduler.automatic_preflight', self.preflight)]
        for item in self.patches: item.start()

    async def asyncTearDown(self):
        for item in self.patches: item.stop()
        await engine.dispose()

    async def schedule(self, repeat='once', due=True):
        command = RunScheduleCreate(profileId=self.profile['id'], startsAt=now()+timedelta(hours=1),
            workerCount=2, year=now().year, repeat=repeat)
        saved = await self.repo.create('schedule-test', command)
        if due:
            saved = await self.repo.patch(saved['id'], {'nextRunAt': (now()-timedelta(minutes=1)).isoformat()})
        return saved

    async def test_network_outage_requeues_interrupted_case_without_failure_and_resumes(self):
        from app.network_guard import record
        saved=await self.start()
        jobs=sorted(await self.jobs(),key=lambda job:job.scenario_name)
        await finish(str(jobs[0].id),JobStatus.COMPLETED)
        await record(False,'Fixture connection lost')
        saved=await self.repo.get(saved['id'])
        self.assertTrue(saved['networkPaused']);self.assertEqual(saved['status'],'PAUSING')
        self.assertEqual((await services.jobs.get(jobs[1].id)).status,JobStatus.CANCELLED)
        await scheduler_tick()
        saved=await self.repo.get(saved['id']);self.assertEqual(saved['status'],'PAUSED')
        snapshot=await queue.snapshot(UUID(saved['sessionId']),saved['owner'])
        self.assertEqual(snapshot['tasks'][0]['status'],'COMPLETED')
        self.assertEqual(snapshot['tasks'][1]['status'],'PENDING')
        self.assertEqual(snapshot['tasks'][1]['failures'],0)
        self.assertIn((await queue.claim(UUID(saved['sessionId']),saved['owner'],'playwright-2'))['type'],{'paused','network_paused'})
        await record(True)
        await scheduler_tick();await scheduler_tick();await scheduler_tick()
        current=await self.repo.get(saved['id']);self.assertEqual(current['status'],'RUNNING')
        self.assertEqual(current['sessionId'],saved['sessionId'])
        retry=[job for job in await self.jobs() if job.retry_of_job_id==jobs[1].id][0]
        self.assertEqual(retry.filters,jobs[1].filters)
        self.assertEqual(len([job for job in await self.jobs() if job.scenario_name==jobs[0].scenario_name]),1)

    async def test_manual_pause_during_network_loss_is_not_auto_resumed(self):
        from app.network_guard import record
        saved=await self.start();await record(False);await scheduler_tick()
        await self.repo.pause(saved['id'],saved['owner'])
        await record(True);await scheduler_tick()
        current=await self.repo.get(saved['id'])
        self.assertEqual(current['status'],'PAUSED');self.assertFalse(current['networkPaused'])

    async def test_network_preparation_pause_prevents_maker_and_recovers_same_session(self):
        from app.network_guard import record
        saved=await self.schedule();await scheduler_tick();saved=await self.repo.get(saved['id'])
        await record(False);await scheduler_tick()
        self.assertEqual(self.planner.await_count,0)
        self.assertEqual((await self.repo.get(saved['id']))['status'],'PAUSED')
        await record(True);await scheduler_tick();await scheduler_tick()
        current=await self.repo.get(saved['id'])
        self.assertEqual(current['status'],'RUNNING');self.assertEqual(current['sessionId'],saved['sessionId'])

    async def test_probe_distinguishes_reachable_auth_from_transport_and_upstream_errors(self):
        from app.network_guard import probe
        from urllib.error import HTTPError,URLError
        with patch('app.network_guard.urlopen',side_effect=HTTPError('fixture',403,'Forbidden',{},None)):
            self.assertTrue((await probe())[0])
        with patch('app.network_guard.urlopen',side_effect=HTTPError('fixture',503,'Unavailable',{},None)):
            self.assertFalse((await probe())[0])
        with patch('app.network_guard.urlopen',side_effect=URLError('Fixture DNS error')):
            self.assertFalse((await probe())[0])

    async def test_network_monitor_requires_two_healthy_checks_before_recovery(self):
        from app.network_guard import monitor,status
        calls=0
        async def sleep(_seconds):
            nonlocal calls
            calls+=1
            if calls==2:self.assertFalse((await status())['online'])
            if calls>=3:raise asyncio.CancelledError()
        with patch('app.network_guard.probe',AsyncMock(side_effect=[(False,'Fixture outage'),(True,None),(True,None)])), patch('app.network_guard.asyncio.sleep',sleep):
            with self.assertRaises(asyncio.CancelledError):await monitor()
        self.assertTrue((await status())['online'])

    async def test_operational_diagnostics_preserve_step_age_and_original_error(self):
        saved = await self.schedule()
        saved = await self.repo.begin_run(saved['id'])
        first = await checkpoint(saved, {'stage': 'Docker worker pool', 'message': 'Preparing workers.'})
        repeated = await checkpoint(first, {'stage': 'Docker worker pool', 'message': 'Preparing workers.'})
        self.assertEqual(first['operation']['startedAt'], repeated['operation']['startedAt'])
        self.assertEqual(first['operation']['progressAt'], repeated['operation']['progressAt'])
        failed = await checkpoint(repeated, {'message': 'A worker is still busy.', 'operationError': 'A worker is still busy.'})
        self.assertEqual(failed['operation']['stage'], 'Docker worker pool')
        self.assertEqual(failed['operation']['error'], 'A worker is still busy.')
        self.assertEqual(first['operation']['startedAt'], failed['operation']['startedAt'])
        changed = await checkpoint(failed, {'stage': 'UI Health preflight', 'message': 'Checking DOM.'})
        self.assertIsNone(changed['operation']['error'])
        self.assertNotEqual(first['operation']['startedAt'], changed['operation']['startedAt'])

    async def test_diagnostics_show_stuck_step_and_busy_unselected_worker(self):
        from app.run_diagnostics import attach_diagnostics
        from app.repositories.run_schedules import public_schedule
        from types import SimpleNamespace
        saved = await self.start()
        timestamp = (now() - timedelta(minutes=8)).isoformat()
        saved = await self.repo.patch(saved['id'], {'status': 'PREPARING',
            'operation': {'stage': 'Docker worker pool', 'startedAt': timestamp,
                'heartbeatAt': now().isoformat(), 'progressAt': timestamp, 'error': 'Worker busy.'}})
        async with engine.begin() as connection:
            await connection.execute(update(db.app_settings).where(db.app_settings.c.key == 'docker-worker-pool')
                .values(value={'desiredCount': 3, 'phase': 'ready'}))
        health = AsyncMock(return_value={'connected': True, 'browserReady': True, 'optionsBusy': True})
        with patch('app.run_diagnostics.settings', SimpleNamespace(runner_health_checks=True)), patch('app.run_diagnostics.read_health', health):
            values = await attach_diagnostics([public_schedule(saved)])
        diagnostics = values[0]['diagnostics']
        self.assertIn('over 5 minutes', diagnostics['warning'])
        self.assertEqual(len(diagnostics['workers']), 3)
        self.assertFalse(diagnostics['workers'][2]['selected'])
        self.assertTrue(diagnostics['workers'][2]['optionsBusy'])
        self.assertEqual(len([worker for worker in diagnostics['workers'] if worker['jobId']]), 2)
        self.assertNotIn('definition', values[0])
        # Endpoint failures are diagnostic information, never a reason to stop work.
        with patch('app.run_diagnostics.settings', SimpleNamespace(runner_health_checks=True)), patch('app.run_diagnostics.read_health', AsyncMock(return_value={'reachable': False})):
            values = await attach_diagnostics([public_schedule(saved)])
        self.assertFalse(values[0]['diagnostics']['workers'][0]['reachable'])

    async def test_unexpected_dispatch_error_is_visible_and_queue_is_preserved(self):
        saved = await self.start()
        with patch('app.run_scheduler.dispatch_run', AsyncMock(side_effect=RuntimeError('fixture dispatch failure'))):
            await scheduler_tick()
        failed = await self.repo.get(saved['id'])
        self.assertEqual(failed['status'], 'RUNNING')
        self.assertEqual(failed['sessionId'], saved['sessionId'])
        self.assertEqual(failed['operation']['error'], 'fixture dispatch failure')
        self.assertIn('fixture dispatch failure', failed['message'])
        self.assertIsNotNone(failed['retryAfter'])

    async def start(self, repeat='once'):
        saved = await self.schedule(repeat)
        for _ in range(3): await scheduler_tick()
        saved = await self.repo.get(saved['id'])
        self.assertEqual(saved['status'], 'RUNNING')
        return saved

    async def jobs(self):
        return await services.jobs.list_all('schedule-test')

    async def test_expired_or_revoked_dashboard_session_does_not_stop_dispatch(self):
        from app.security import authenticate_access_token, issue_access_token
        from app.repositories.postgres import session_hash
        saved = await self.schedule()
        raw = await services.users.create_session('schedule-test')
        token = issue_access_token('schedule-test', raw)
        async with engine.begin() as connection:
            await connection.execute(update(db.auth_sessions).where(db.auth_sessions.c.id == session_hash(raw))
                .values(last_activity_at=now() - timedelta(hours=1)))
        self.assertIsNone(await authenticate_access_token(token))
        await services.users.revoke(raw)
        for _ in range(3):
            await scheduler_tick()
        current = await self.repo.get(saved['id'])
        self.assertEqual(current['status'], 'RUNNING')
        self.assertEqual(len(await self.jobs()), 2)
        self.assertTrue(all(job.status == JobStatus.ASSIGNED for job in await self.jobs()))

    async def test_dates_validation_and_daily_time_zone(self):
        future = now()+timedelta(days=1)
        command = RunScheduleCreate(profileId=self.profile['id'], startsAt=future,
            workerCount=8, year=now().year)
        self.assertEqual(command.starts_at.utcoffset(), timedelta(0))
        for starts_at, workers in [(future.replace(tzinfo=None), 8), (now()-timedelta(minutes=1), 8),
            (future, 0), (future, 11), (future, True)]:
            with self.assertRaises(ValidationError):
                RunScheduleCreate(profileId=self.profile['id'], startsAt=starts_at, workerCount=workers, year=now().year)
        next_run = next_daily_run('2026-10-07T09:30:00+07:00', datetime.fromisoformat('2026-10-10T18:00:00+07:00'))
        self.assertEqual(next_run, '2026-10-11T02:30:00+00:00')

    async def test_ownership_profile_snapshot_and_atomic_claim(self):
        saved = await self.schedule()
        with self.assertRaises(LookupError): await self.repo.get(saved['id'], 'another-user')
        with self.assertRaises(LookupError): await self.repo.toggle(saved['id'], 'another-user', False)
        self.assertEqual(await self.repo.list('another-user'), [])
        claims = await asyncio.gather(self.repo.begin_run(saved['id']), self.repo.begin_run(saved['id']))
        self.assertEqual(sum(value is not None for value in claims), 1)
        updated = await self.repo.get(saved['id'])
        self.assertEqual(updated['definition'], self.profile['definition'])
        future = await self.schedule(due=False)
        await self.repo.toggle(future['id'], 'schedule-test', False)
        self.assertIsNone(await self.repo.begin_run(future['id']))

    async def test_unattended_dispatch_worker_cap_completion_and_no_data(self):
        saved = await self.start()
        jobs = await self.jobs()
        self.assertEqual(len(jobs), 2)
        self.assertEqual({job.runner_id for job in jobs}, {'playwright-1', 'playwright-2'})
        await scheduler_tick()
        self.assertEqual(len(await self.jobs()), 2, 'Repeated ticks must not duplicate active assignments.')
        await finish(str(jobs[0].id), JobStatus.NO_DATA)
        await finish(str(jobs[1].id), JobStatus.COMPLETED)
        await scheduler_tick()
        jobs = await self.jobs()
        self.assertEqual(len(jobs), 3, 'Valid No data must not be retried.')
        active = next(job for job in jobs if job.status == JobStatus.ASSIGNED)
        await finish(str(active.id), JobStatus.COMPLETED)
        await scheduler_tick()
        final = await self.repo.get(saved['id'])
        self.assertEqual((final['status'], final['done'], final['withData'], final['noData'], final['failed']),
            ('COMPLETED', 3, 2, 1, 0))
        self.assertFalse(final['enabled'])
        self.assertIsNone(final['sessionId'])
        await scheduler_tick()
        self.assertEqual(len(await self.jobs()), 3)
        self.assertEqual(self.planner.await_count, 1)

    async def test_restart_after_queue_creation_reuses_same_session(self):
        saved = await self.schedule()
        await scheduler_tick()
        saved = await self.repo.get(saved['id'])
        await queue.start(UUID(saved['sessionId']), saved['owner'], [QueueTaskInput.model_validate(task) for task in self.tasks], 2)
        await scheduler_tick()
        self.assertEqual((await self.repo.get(saved['id']))['status'], 'RUNNING')
        self.assertEqual(self.planner.await_count, 0)
        await scheduler_tick()
        async with engine.connect() as connection:
            session_ids = list(await connection.scalars(select(db.report_sessions.c.id)))
        self.assertEqual(session_ids, [saved['sessionId']])

    async def test_committed_assignment_is_redelivered_after_socket_failure(self):
        saved = await self.schedule()
        await scheduler_tick(); await scheduler_tick()
        self.events.side_effect = RuntimeError('Fixture delivery failure')
        await scheduler_tick()
        self.assertEqual((await self.repo.get(saved['id']))['operation']['error'], 'Fixture delivery failure')
        first = (await self.jobs())[0]
        self.events.side_effect = None
        await self.repo.patch(saved['id'], {'retryAfter': None})
        await scheduler_tick()
        jobs = await self.jobs()
        self.assertEqual(len(jobs), 2)
        self.assertIn(first.id, [job.id for job in jobs])
        delivered = [call.args[1]['jobId'] for call in self.events.await_args_list if call.args[0] == 'job:assigned']
        self.assertGreaterEqual(delivered.count(str(first.id)), 2)

    async def test_stop_cancels_active_jobs_and_retains_history(self):
        saved = await self.start()
        await stop_scheduled_run(saved)
        final = await self.repo.get(saved['id'])
        self.assertEqual(final['status'], 'STOPPED')
        self.assertTrue(all(job.status == JobStatus.CANCELLED for job in await self.jobs()))
        snapshot = await queue.snapshot(UUID(saved['sessionId']), saved['owner'])
        self.assertEqual(snapshot['status'], 'PAUSED')
        await scheduler_tick()
        self.assertEqual(len(await self.jobs()), 2)
        self.assertIsNone(final['nextRunAt'])

    async def test_pause_drain_resize_up_and_down_preserves_same_cases(self):
        self.tasks = [{'name': f'Office {i}', 'filters': {'states': ['State'], 'rtos': [f'Office {i}'],
            'fromYear': str(now().year), 'toYear': str(now().year), 'autoApply': True}} for i in range(7)]
        self.planner.return_value = {'scenarios': self.tasks}
        saved = await self.start()
        original_session = saved['sessionId']
        original_start = saved['lastRunAt']
        first_jobs = await self.jobs()
        paused = await self.repo.pause(saved['id'], 'schedule-test')
        self.assertEqual(paused['status'], 'PAUSING')
        await scheduler_tick()
        self.assertEqual(len(await self.jobs()), 2, 'Pausing must not claim the next pending case.')
        self.assertTrue(all(job.status == JobStatus.ASSIGNED for job in await self.jobs()), 'Active cases drain; they are not cancelled.')
        with self.assertRaises(ValueError): await self.repo.resume(saved['id'], 'schedule-test', 3)
        await finish(str(first_jobs[0].id), JobStatus.COMPLETED)
        await finish(str(first_jobs[1].id), JobStatus.NO_DATA)
        await scheduler_tick()
        paused = await self.repo.get(saved['id'])
        self.assertEqual((paused['status'], paused['done']), ('PAUSED', 2))
        self.assertEqual(paused['sessionId'], original_session)
        clock = paused['activeElapsedMs']
        await scheduler_tick()
        self.assertEqual(len(await self.jobs()), 2, 'Reloaded/idle ticks do not resume paused work automatically.')
        self.assertEqual((await self.repo.get(saved['id']))['activeElapsedMs'], clock)
        await self.repo.resume(saved['id'], 'schedule-test', 3)
        await scheduler_tick(); await scheduler_tick()
        running = await self.repo.get(saved['id'])
        self.assertEqual(running['lastRunAt'], original_start)
        self.assertEqual(running['workerCount'], 3)
        self.assertEqual(running['sessionId'], original_session)
        active_jobs = [job for job in await self.jobs() if job.status == JobStatus.ASSIGNED]
        self.assertEqual({job.runner_id for job in active_jobs}, {'playwright-1','playwright-2','playwright-3'})
        await self.repo.pause(saved['id'], 'schedule-test')
        for job in active_jobs: await finish(str(job.id), JobStatus.COMPLETED)
        await scheduler_tick()
        await self.repo.resume(saved['id'], 'schedule-test', 1)
        await scheduler_tick(); await scheduler_tick()
        active_jobs = [job for job in await self.jobs() if job.status == JobStatus.ASSIGNED]
        self.assertEqual(len(active_jobs), 1)
        self.assertEqual(active_jobs[0].runner_id, 'playwright-1')
        await finish(str(active_jobs[0].id), JobStatus.NO_DATA)
        await scheduler_tick()
        last = next(job for job in await self.jobs() if job.status == JobStatus.ASSIGNED)
        await finish(str(last.id), JobStatus.COMPLETED)
        await scheduler_tick()
        self.assertEqual((await self.repo.get(saved['id']))['status'], 'COMPLETED')
        self.assertEqual(len(await self.jobs()), 7, 'Committed/no-data cases are never rerun after changing workers.')
        self.assertEqual(len({job.filters.rtos[0] for job in await self.jobs()}), 7)
        self.assertEqual(self.planner.await_count, 1, 'Resume uses the saved queue rather than recompiling a case plan.')
        async with engine.connect() as connection:
            self.assertEqual(list(await connection.scalars(select(db.report_sessions.c.id))), [original_session])

    async def test_delete_paused_run_discards_queue_and_retains_collected_data(self):
        saved = await self.start('daily')
        jobs = await self.jobs()
        await self.repo.pause(saved['id'], saved['owner'])
        await finish(str(jobs[0].id), JobStatus.COMPLETED)
        await finish(str(jobs[1].id), JobStatus.NO_DATA)
        await scheduler_tick()
        self.assertEqual((await self.repo.get(saved['id']))['status'], 'PAUSED')
        async with engine.begin() as connection:
            await connection.execute(insert(db.stored_files).values(id='saved-file', owner_username=saved['owner'],
                job_id=str(jobs[0].id), kind='excel', name='saved.xlsx', mime_type='application/octet-stream',
                size=7, sha256='fixture', content=b'fixture', metadata={}, created_at=now()))
            await connection.execute(insert(db.main_reports).values(id='saved-row', scope_key='fixture',
                scope_label='Fixture', filters={}, year=now().year, state='State', rto='Office', rto_code='1',
                maker='Saved Maker', jan=123, month_sources={}, created_at=now(), updated_at=now()))
        await self.repo.delete(saved['id'], saved['owner'])
        with self.assertRaises(LookupError): await self.repo.get(saved['id'])
        with self.assertRaises(LookupError): await queue.snapshot(UUID(saved['sessionId']), saved['owner'])
        self.assertEqual({str(job.id): job.status for job in await self.jobs()},
            {str(jobs[0].id): JobStatus.COMPLETED, str(jobs[1].id): JobStatus.NO_DATA})
        async with engine.connect() as connection:
            self.assertEqual(await connection.scalar(select(db.report_sessions.c.id)), saved['sessionId'])
            self.assertEqual(await connection.scalar(select(db.stored_files.c.content)), b'fixture')
            self.assertEqual(await connection.scalar(select(db.main_reports.c.jan)), 123)
            self.assertEqual(list(await connection.scalars(select(db.batch_queue_tasks.c.position))), [])
        self.assertFalse(await still_current(saved))
        self.assertIsNone(await checkpoint(saved, {'status': 'RUNNING'}))
        await scheduler_tick()
        self.assertEqual(len(await self.jobs()), 2, 'Deleted daily schedules cannot publish more work.')

    async def test_delete_rejects_active_draining_and_resuming_runs(self):
        saved = await self.start()
        with self.assertRaises(ValueError): await self.repo.delete(saved['id'], saved['owner'])
        await self.repo.pause(saved['id'], saved['owner'])
        with self.assertRaises(ValueError): await self.repo.delete(saved['id'], saved['owner'])
        for job in await self.jobs(): await finish(str(job.id), JobStatus.NO_DATA)
        await scheduler_tick()
        await self.repo.resume(saved['id'], saved['owner'], 1)
        with self.assertRaises(ValueError): await self.repo.delete(saved['id'], saved['owner'])
        self.assertEqual((await self.repo.get(saved['id']))['status'], 'RESUMING')

    async def test_delete_checks_ownership_and_active_jobs_even_if_status_is_paused(self):
        saved = await self.start()
        with self.assertRaises(LookupError): await self.repo.delete(saved['id'], 'another-user')
        await self.repo.pause(saved['id'], saved['owner'])
        await self.repo.patch(saved['id'], {'status': 'PAUSED'})
        with self.assertRaisesRegex(ValueError, 'finish saving'):
            await self.repo.delete(saved['id'], saved['owner'])
        self.assertEqual(len(await self.jobs()), 2)
        self.assertEqual((await self.repo.get(saved['id']))['status'], 'PAUSED')

    async def test_delete_legacy_stopped_run_keeps_cancelled_job_history(self):
        saved = await self.start()
        await stop_scheduled_run(saved)
        await self.repo.delete(saved['id'], saved['owner'])
        self.assertTrue(all(job.status == JobStatus.CANCELLED for job in await self.jobs()))
        with self.assertRaises(LookupError): await queue.snapshot(UUID(saved['sessionId']), saved['owner'])

    async def test_delete_racing_resume_has_only_one_winner(self):
        saved = await self.start()
        await self.repo.pause(saved['id'], saved['owner'])
        for job in await self.jobs(): await finish(str(job.id), JobStatus.NO_DATA)
        await scheduler_tick()
        outcomes = await asyncio.gather(self.repo.delete(saved['id'], saved['owner']),
            self.repo.resume(saved['id'], saved['owner'], 1), return_exceptions=True)
        self.assertEqual(sum(isinstance(value, Exception) for value in outcomes), 1)
        if outcomes[0] is None:
            with self.assertRaises(LookupError): await self.repo.get(saved['id'])
            with self.assertRaises(LookupError): await queue.snapshot(UUID(saved['sessionId']), saved['owner'])
        else:
            self.assertEqual((await self.repo.get(saved['id']))['status'], 'RESUMING')

    async def test_delete_paused_preparation_without_queue_fences_old_plan(self):
        saved = await self.schedule()
        await scheduler_tick()
        active = await self.repo.get(saved['id'])
        await self.repo.pause(saved['id'], saved['owner'])
        await scheduler_tick()
        self.assertEqual((await self.repo.get(saved['id']))['status'], 'PAUSED')
        await self.repo.delete(saved['id'], saved['owner'])
        self.assertFalse(await still_current(active))
        self.assertIsNone(await checkpoint(active, {'tasks': self.tasks, 'status': 'RUNNING'}))
        async with engine.connect() as connection:
            self.assertEqual(list(await connection.scalars(select(db.batch_queue_sessions.c.session_id))), [])

    async def test_headless_checkpoints_final_sweep_and_resume_recover_all_failures(self):
        self.tasks=[{'name':f'Office {i}','filters':{'states':['State'],'rtos':[f'Office {i}'],
            'fromYear':str(now().year),'toYear':str(now().year),'autoApply':True}} for i in range(23)]
        self.planner.return_value={'scenarios':self.tasks}
        saved=await self.start();session=saved['sessionId'];attempts={};paused=False
        for tick in range(100):
            current=await self.repo.get(saved['id'])
            if current['status'] in {'COMPLETED','COMPLETED_WITH_ERRORS'}:break
            active=[job for job in await self.jobs() if job.status==JobStatus.ASSIGNED]
            final=current.get('retryProgress',{}).get('phase')=='FINAL'
            if final and not paused:
                await self.repo.pause(saved['id'],'schedule-test');paused=True
            for job in active:
                position=int(job.scenario_name.split()[-1]);attempts[position]=attempts.get(position,0)+1
                if position==10:self.assertEqual(attempts[1],2,'checkpoint 1 finishes before case 11')
                if position==20:self.assertEqual(attempts[11],2,'checkpoint 2 finishes before case 21')
                if attempts[position]==3:self.assertTrue(all(attempts.get(i,0)>=1 for i in range(23)))
                status=JobStatus.NO_DATA if position in {2,22} else JobStatus.FAILED if position==21 or position in {1,11} and attempts[position]<3 else JobStatus.COMPLETED
                await finish(str(job.id),status)
            await scheduler_tick()
            current=await self.repo.get(saved['id'])
            if current['status']=='PAUSED':
                self.assertEqual(current['sessionId'],session)
                await self.repo.resume(saved['id'],'schedule-test',3)
        else:self.fail('Automatic recovery did not finish')
        current=await self.repo.get(saved['id'])
        self.assertTrue(paused);self.assertEqual(current['status'],'COMPLETED_WITH_ERRORS')
        self.assertEqual(current['done'],23);self.assertEqual(current['failed'],1)
        self.assertEqual(current['noData'],2);self.assertEqual(current['withData'],20)
        self.assertTrue(current['retryProgress']['complete']);self.assertEqual(current['retryProgress']['phase'],'DONE')
        self.assertEqual([attempts[i] for i in (1,11,21)],[3,3,3])
        self.assertEqual(attempts[2],1);self.assertEqual(attempts[22],1)

    async def test_pause_during_preparation_fences_old_plan(self):
        saved = await self.schedule()
        await scheduler_tick()
        original_session = (await self.repo.get(saved['id']))['sessionId']
        async def paused_plan(*args):
            await self.repo.pause(saved['id'], 'schedule-test')
            return {'scenarios': self.tasks}
        self.planner.side_effect = paused_plan
        await scheduler_tick(); await scheduler_tick()
        paused = await self.repo.get(saved['id'])
        self.assertEqual(paused['status'], 'PAUSED')
        async with engine.connect() as connection:
            self.assertEqual(list(await connection.scalars(select(db.batch_queue_sessions.c.session_id))), [])
        self.planner.side_effect = None
        await self.repo.resume(saved['id'], 'schedule-test', 3)
        await scheduler_tick(); await scheduler_tick()
        resumed = await self.repo.get(saved['id'])
        self.assertEqual(resumed['sessionId'], original_session)
        self.assertEqual(resumed['status'], 'RUNNING')
        self.assertEqual(len(await self.jobs()), 3)

    async def test_pause_epoch_ownership_and_worker_validation(self):
        saved = await self.start()
        with self.assertRaises(LookupError): await self.repo.pause(saved['id'], 'another-user')
        values = await asyncio.gather(self.repo.pause(saved['id'], 'schedule-test'), self.repo.pause(saved['id'], 'schedule-test'))
        self.assertEqual(values[0]['executionEpoch'], values[1]['executionEpoch'])
        stale = await self.repo.patch(saved['id'], {'status':'RUNNING'}, session_id=saved['sessionId'], execution_epoch=saved['executionEpoch'])
        self.assertIsNone(stale, 'Old dispatch callbacks cannot overwrite a pause.')
        for job in await self.jobs(): await finish(str(job.id), JobStatus.NO_DATA)
        await scheduler_tick()
        with self.assertRaises(LookupError): await self.repo.resume(saved['id'], 'another-user', 2)
        for count in [0,11,True,1.5]:
            with self.assertRaises(ValueError): await self.repo.resume(saved['id'], 'schedule-test', count)
            with self.assertRaises(ValidationError): RunScheduleResume(workerCount=count)

    async def test_legacy_stopped_run_can_continue_saved_queue(self):
        saved = await self.start()
        await stop_scheduled_run(saved)
        await self.repo.resume(saved['id'], 'schedule-test', 1)
        await scheduler_tick(); await scheduler_tick()
        resumed = await self.repo.get(saved['id'])
        self.assertEqual(resumed['sessionId'], saved['sessionId'])
        self.assertEqual(resumed['status'], 'RUNNING')
        self.assertFalse(resumed['enabled'], 'Continue does not re-enable future runs that were explicitly disabled.')
        self.assertEqual(self.planner.await_count, 1)
        self.assertEqual(len([job for job in await self.jobs() if job.status == JobStatus.ASSIGNED]), 1)

    async def test_future_toggle_and_resume_do_not_overwrite_execution_state(self):
        saved = await self.start('daily')
        await stop_scheduled_run(saved)
        await asyncio.gather(self.repo.resume(saved['id'], 'schedule-test', 1),
            self.repo.toggle(saved['id'], 'schedule-test', True))
        current = await self.repo.get(saved['id'])
        self.assertEqual(current['status'], 'RESUMING')
        self.assertEqual(current['sessionId'], saved['sessionId'])
        self.assertTrue(current['enabled'])

    async def test_resume_check_failure_keeps_session_paused(self):
        saved = await self.start()
        await self.repo.pause(saved['id'], 'schedule-test')
        for job in await self.jobs(): await finish(str(job.id), JobStatus.NO_DATA)
        await scheduler_tick()
        await self.repo.resume(saved['id'], 'schedule-test', 3)
        self.preflight.side_effect = ValueError('Fixture resumed preflight failed')
        for _ in range(3):
            await self.repo.patch(saved['id'], {'retryAfter':None})
            await scheduler_tick()
        final = await self.repo.get(saved['id'])
        self.assertEqual(final['status'], 'PAUSED')
        self.assertEqual(final['sessionId'], saved['sessionId'])
        self.assertEqual(final['done'], 2)
        self.assertEqual(len(await self.jobs()), 2)

    async def test_stop_during_planning_does_not_create_orphan_queue(self):
        saved = await self.schedule()
        await scheduler_tick()
        async def stop_during_compile(*args):
            await stop_scheduled_run(await self.repo.get(saved['id']))
            return {'scenarios': self.tasks}
        self.planner.side_effect = stop_during_compile
        await scheduler_tick()
        self.assertEqual((await self.repo.get(saved['id']))['status'], 'STOPPED')
        async with engine.connect() as connection:
            sessions = list(await connection.scalars(select(db.batch_queue_sessions.c.session_id)))
        self.assertEqual(sessions, [])

    async def test_waits_for_manual_queue_and_offline_workers(self):
        manual = uuid4()
        await queue.start(manual, 'schedule-test', [QueueTaskInput.model_validate(self.tasks[0])], 2)
        saved = await self.schedule()
        await scheduler_tick(); await scheduler_tick()
        self.assertIn('current run', (await self.repo.get(saved['id']))['message'])
        self.assertEqual(self.pool.await_count, 0)
        await queue.set_status(manual, 'schedule-test', 'PAUSED')
        async with engine.begin() as connection:
            await connection.execute(update(db.runners).values(connected=False))
        await scheduler_tick()
        self.assertIn('connect', (await self.repo.get(saved['id']))['message'])
        self.assertEqual(await self.jobs(), [])

    async def test_daily_run_finishes_with_next_future_slot(self):
        saved = await self.start('daily')
        for job in await self.jobs(): await finish(str(job.id), JobStatus.NO_DATA)
        await scheduler_tick()
        for job in await self.jobs():
            if job.status == JobStatus.ASSIGNED: await finish(str(job.id), JobStatus.COMPLETED)
        await scheduler_tick()
        saved = await self.repo.get(saved['id'])
        self.assertTrue(saved['enabled'])
        self.assertGreater(datetime.fromisoformat(saved['nextRunAt']), now())
        self.assertEqual(saved['status'], 'COMPLETED')

    async def test_captcha_visibility_is_owner_scoped_and_only_current(self):
        for owner in ['schedule-test', 'another-user']:
            await services.jobs.create(Job(runnerId='playwright-1', ownerUsername=owner,
                status=JobStatus.WAITING_CAPTCHA, captchaId=str(uuid4()),
                captchaImageDataUrl='data:image/png;base64,aW1hZ2U=', filters={'states': ['State'], 'rtos': [owner]}))
        request = Request({'type': 'http'})
        request.state.authenticated_user = 'schedule-test'
        request.state.authenticated_role = 'user'
        current=await current_captchas(request)
        self.assertEqual(len(current), 1)
        self.assertNotIn('imageDataUrl',current[0])
        async with engine.connect() as connection:
            payloads=list(await connection.scalars(select(db.jobs.c.payload)))
        self.assertTrue(all('captcha_image_data_url' not in payload for payload in payloads))
        request.state.authenticated_role = 'admin'
        self.assertEqual(len(await current_captchas(request)), 2)
        for job in await services.jobs.list_all(): await finish(str(job.id), JobStatus.CANCELLED)
        self.assertEqual(await current_captchas(request), [])

    async def test_postgres_leader_lock_excludes_second_api_process(self):
        async with engine.connect() as first, engine.connect() as second:
            self.assertTrue(await first.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': LEADER_LOCK}))
            self.assertFalse(await second.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': LEADER_LOCK}))
            await first.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': LEADER_LOCK})
            self.assertTrue(await second.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': LEADER_LOCK}))
            await second.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': LEADER_LOCK})

    async def test_automatic_preflight_records_all_selected_workers_without_ui(self):
        value = await self.schedule()
        async def inspected(_event, payload, **kwargs):
            async with engine.connect() as connection:
                runner_id=await connection.scalar(select(db.runners.c.id).where(db.runners.c.socket_id==kwargs['to']))
            current=await ui_contract.current()
            observed=[{**control,'found':True,'count':1,'matchedBy':'selector'} for control in current['controls']]
            validation=await ui_contract.evaluate({'status':'PASS','observedControls':observed},runner_id)
            saved=await services.ui_health_logs.append({'status':'PASS','checkId':payload['requestId'],'checkedAt':now().isoformat(),'trigger':'preflight','observedControls':observed,'contractValidation':validation})
            return {**saved,'validation':validation}
        with patch('app.api.ui_health.sio.call', side_effect=inspected) as calls:
            gate = await automatic_preflight(value, ['playwright-1', 'playwright-2'])
        self.assertEqual(calls.await_count, 2)
        async with engine.connect() as connection:
            record = (await connection.execute(select(db.ui_preflight_checks).where(db.ui_preflight_checks.c.id == gate))).mappings().one()
        self.assertEqual(record['runner_ids'], ['playwright-1', 'playwright-2'])
        self.assertEqual(record['owner_username'], 'schedule-test')
        self.assertEqual(record['status'], 'PASS')

    async def test_ui_health_block_prevents_any_new_assignment(self):
        saved = await self.start()
        for job in await self.jobs(): await finish(str(job.id), JobStatus.NO_DATA)
        async with engine.begin() as connection:
            await connection.execute(update(db.app_settings).where(db.app_settings.c.key == ui_contract.ACTIVE_KEY)
                .values(value={'versionId': self.validation['versionId'], 'blocked': True, 'lastError': 'Fixture DOM drift'}))
        self.preflight.side_effect = ValueError('Fixture preflight blocked')
        await scheduler_tick()
        self.assertEqual(len(await self.jobs()), 2)
        self.assertIn('successful UI health check', (await self.repo.get(saved['id']))['message'])


if __name__ == '__main__': unittest.main(verbosity=2)
