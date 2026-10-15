"""Durable attempts under competing claims, expired heartbeats and late writes."""
import asyncio
import os
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update

from app.api.batch_queue import QueueTaskInput
from app.db import engine, schema as db
from app.models.job import JobStatus
from app.models.report_result import ReportResultRequest
from app.repositories.batch_queue import BatchQueueRepository
from app.repositories.postgres import now, runner_document
from app.repositories.report_results import commit_report_result
from app.services import services
from app.worker_pool import apply_pool


async def setup_queue(count=3, total=27):
    workers = [f'recovery-{i}' for i in range(count)]
    for worker in workers:
        await services.runners.register(runner_id=worker, name=worker, socket_id=worker)
    await apply_pool(count)
    session = uuid4()
    queue = BatchQueueRepository()
    await queue.start(session, 'test-admin', [QueueTaskInput(name=f'Office {i}', filters={
        'states': ['Recovery State'], 'rtos': [f'Office {i}'], 'fromYear': '2024', 'toYear': '2024'})
        for i in range(total)], count, automatic_workers=True)
    return queue, session, workers


async def waiting_result(job_id):
    for status in [JobStatus.OPENING_VAHAN, JobStatus.FILLING_FILTERS,
                   JobStatus.SUBMITTING, JobStatus.WAITING_RESULT]:
        assert await services.jobs.transition_status(UUID(job_id), status)
    return ReportResultRequest(result='NO_RECORD', message='No record found',
        observedAt=now(), pageUrl='https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en')


async def expire(worker, connected=True):
    runner = await services.runners.get(worker)
    runner.last_seen_at = now() - timedelta(minutes=2)
    async with engine.begin() as connection:
        await connection.execute(update(db.runners).where(db.runners.c.id == worker).values(
            connected=connected, payload=runner_document(runner)))


async def test_competing_workers_commit_all_cases_once_and_duplicate_delivery_is_idempotent(admin_token):
    queue, session, workers = await setup_queue()
    claimed, peaks = set(), []
    for _ in range(12):
        for worker in workers:
            await services.runners.heartbeat(worker)
        # Several overlapping polls from each worker must recover its current
        # attempt, never allocate two jobs to one browser or one case twice.
        responses = await asyncio.wait_for(asyncio.gather(*(
            BatchQueueRepository().claim(session, 'test-admin', worker)
            for worker in workers for _ in range(4))), timeout=20)
        assignments = {result['jobId']: result for result in responses if result['type'] == 'assigned'}
        assert len(assignments) <= 3
        peaks.append(len(assignments))
        jobs = [await services.jobs.get(UUID(job_id)) for job_id in assignments]
        assert len({job.runner_id for job in jobs}) == len(jobs)
        assert len({job.case_id for job in jobs}) == len(jobs)
        for job_id, assignment in assignments.items():
            position = assignment['task']['position']
            assert position not in claimed
            claimed.add(position)
            command = await waiting_result(job_id)
            worker = (await services.jobs.get(UUID(job_id))).runner_id
            results = await asyncio.gather(*(commit_report_result(UUID(job_id), worker, command) for _ in range(3)))
            assert all(job.status == JobStatus.NO_DATA for job in results)
        if (await queue.snapshot(session, 'test-admin'))['retry']['complete']:
            break
    assert max(peaks) == 3
    assert claimed == set(range(27))
    snapshot = await queue.snapshot(session, 'test-admin')
    assert all(task['status'] == 'NO_DATA' and task['attempts'] == 1 for task in snapshot['tasks'])
    async with engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(db.jobs)) == 27
        assert await connection.scalar(select(func.count()).select_from(db.report_update_history)) == 27


@pytest.mark.parametrize('connected', [False, True])
async def test_expired_lease_reclaimed_and_late_result_cannot_overwrite_new_attempt(admin_token, connected):
    queue, session, workers = await setup_queue(total=1)
    old = await queue.claim(session, 'test-admin', workers[0])
    command = await waiting_result(old['jobId'])
    await expire(workers[0], connected)
    retry = await queue.claim(session, 'test-admin', workers[1])
    assert retry['type'] == 'assigned' and retry['jobId'] != old['jobId']
    original = await services.jobs.get(UUID(old['jobId']))
    replacement = await services.jobs.get(UUID(retry['jobId']))
    assert original.status == JobStatus.FAILED
    assert replacement.case_id == original.case_id and replacement.filters == original.filters
    assert replacement.retry_of_job_id == original.id
    with pytest.raises(ValueError, match='not waiting'):
        await commit_report_result(original.id, workers[0], command)
    from httpx import ASGITransport, AsyncClient
    from app.config import settings
    from app.main import application
    from app.repositories.file_store import PostgresFileStore
    from io import BytesIO
    from openpyxl import Workbook
    async with AsyncClient(transport=ASGITransport(app=application), base_url='http://test') as client:
        response = await client.post(f'/api/jobs/{original.id}/report-result', headers={
            'X-VAHAN-RUNNER-TOKEN': settings.runner_token, 'X-VAHAN-RUNNER-ID': workers[0]},
            json=command.model_dump(mode='json', by_alias=True))
        assert response.status_code == 409
    book = Workbook()
    book.active.append(['Maker', 'JAN', 'TOTAL']); book.active.append(['Late Maker', 7, 7])
    content = BytesIO(); book.save(content); book.close()
    with pytest.raises(ValueError, match='not waiting'):
        await PostgresFileStore().commit_excel(original.id, 'late.xlsx', content.getvalue(), runner_id=workers[0])
    assert await services.jobs.transition_status(original.id, JobStatus.NO_DATA) is None
    fresh = await waiting_result(retry['jobId'])
    await commit_report_result(replacement.id, workers[1], fresh)
    task = (await queue.snapshot(session, 'test-admin'))['tasks'][0]
    assert (task['status'], task['attempts'], task['failures'], task['jobId']) == ('NO_DATA', 2, 1, retry['jobId'])
    async with engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(db.report_update_history)) == 1


async def test_committed_result_wins_race_with_expiration_without_retry_or_deadlock(admin_token):
    queue, session, workers = await setup_queue(total=1)
    assigned = await queue.claim(session, 'test-admin', workers[0])
    command = await waiting_result(assigned['jobId'])
    # Hold the same row lock as a result transaction. The expiry reader must
    # re-read the committed terminal payload after waiting for that lock.
    async with engine.begin() as connection:
        await connection.execute(select(db.jobs.c.id).where(db.jobs.c.id == assigned['jobId']).with_for_update())
        result_task = asyncio.create_task(commit_report_result(UUID(assigned['jobId']), workers[0], command))
        await asyncio.sleep(.05)
        await expire(workers[0])
        settle_task = asyncio.create_task(queue.snapshot(session, 'test-admin'))
        await asyncio.sleep(.05)
    saved, snapshot = await asyncio.wait_for(asyncio.gather(result_task, settle_task), timeout=20)
    assert saved.status == JobStatus.NO_DATA
    assert snapshot['tasks'][0]['status'] == 'NO_DATA'
    assert snapshot['tasks'][0]['attempts'] == 1
    assert (await queue.claim(session, 'test-admin', workers[1]))['type'] == 'done'


async def test_api_restart_in_another_process_keeps_completed_and_recovers_live_attempt(admin_token):
    import sys
    queue, session, workers = await setup_queue(total=2)
    done = await queue.claim(session, 'test-admin', workers[0])
    command = await waiting_result(done['jobId'])
    await commit_report_result(UUID(done['jobId']), workers[0], command)
    live = await queue.claim(session, 'test-admin', workers[1])
    # A real new Python process executes the same recovery function used by
    # API lifespan; no module state from this test survives that restart.
    process = await asyncio.create_subprocess_exec(sys.executable, '-c',
        'import asyncio\nfrom app.repositories.postgres import recover_after_restart\n'
        'from app.db import engine\nasync def main():\n'
        '    await recover_after_restart()\n    await engine.dispose()\nasyncio.run(main())',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=os.environ.copy())
    _, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    assert process.returncode == 0, stderr.decode()
    assert (await services.jobs.get(UUID(live['jobId']))).status == JobStatus.ASSIGNED
    await services.runners.register(runner_id=workers[1], name='Reconnected', socket_id='after-restart')
    recovered = await queue.claim(session, 'test-admin', workers[1])
    assert recovered['recovered'] and recovered['jobId'] == live['jobId']
    command = await waiting_result(live['jobId'])
    await commit_report_result(UUID(live['jobId']), workers[1], command)
    snapshot = await queue.snapshot(session, 'test-admin')
    assert all(task['status'] == 'NO_DATA' and task['attempts'] == 1 for task in snapshot['tasks'])
    assert len(await services.jobs.list_all()) == 2


async def test_late_terminal_ack_does_not_lock_runner_or_release_its_new_case(admin_token):
    queue, session, workers = await setup_queue(total=2)
    old = await queue.claim(session, 'test-admin', workers[0])
    assert await services.jobs.transition_status(UUID(old['jobId']), JobStatus.FAILED)
    newer = await queue.claim(session, 'test-admin', workers[0])
    assert newer['type'] == 'assigned' and newer['jobId'] != old['jobId']
    async with engine.begin() as connection:
        await connection.execute(select(db.runners.c.id).where(db.runners.c.id == workers[0]).with_for_update())
        acknowledged = await asyncio.wait_for(services.jobs.transition_status(UUID(old['jobId']), JobStatus.FAILED), timeout=10)
        assert acknowledged.status == JobStatus.FAILED
        assert await connection.scalar(select(db.runners.c.current_job_id).where(db.runners.c.id == workers[0])) == newer['jobId']
    assert (await services.jobs.get(UUID(newer['jobId']))).status == JobStatus.ASSIGNED


async def test_real_retry_keeps_one_run_and_one_case_in_admin_history(admin_token):
    from app.repositories.run_history import list_runs
    queue, session, workers = await setup_queue(count=1, total=1)
    original = await queue.claim(session, 'test-admin', workers[0])
    assert await services.jobs.transition_status(UUID(original['jobId']), JobStatus.FAILED)
    retry = await queue.claim(session, 'test-admin', workers[0])
    assert retry['type'] == 'assigned' and retry['jobId'] != original['jobId']
    during = (await list_runs())['runs']
    assert len(during) == 1 and during[0]['totalCases'] == 1 and during[0]['running'] == 1
    command = await waiting_result(retry['jobId'])
    await commit_report_result(UUID(retry['jobId']), workers[0], command)
    await queue.snapshot(session, 'test-admin')  # Settle the canonical case, as the scheduler does.
    final = (await list_runs())['runs']
    assert len(final) == 1 and final[0]['totalRuns'] == 1
    assert (final[0]['totalCases'], final[0]['processed'], final[0]['noData'], final[0]['failed']) == (1, 1, 1, 0)
    jobs = await services.jobs.list_all()
    assert len(jobs) == 2 and len({job.case_id or job.id for job in jobs}) == 1
    task = (await queue.snapshot(session, 'test-admin'))['tasks'][0]
    assert task['attempts'] == 2 and task['status'] == 'NO_DATA'
