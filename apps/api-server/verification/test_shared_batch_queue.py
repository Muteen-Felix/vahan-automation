"""Integration smoke test; run only against a dedicated *_test PostgreSQL database."""
import asyncio
import os
import time
from uuid import uuid4

base_url = os.environ['DATABASE_URL']
assert base_url.rsplit('/', 1)[-1].endswith('_test'), 'Refusing to touch a non-test database.'

from sqlalchemy import insert, select, update

from app.db import engine, schema as db
from app.api.batch_queue import QueueTaskInput
from app.models.job import Job, JobStatus
from app.models.runner import Runner
from app.repositories.batch_queue import BatchQueueRepository
from app.repositories.postgres import PostgresJobRepository, job_document, release_runner, runner_document, now


async def finish(job_id: str, status: JobStatus):
    async with engine.begin() as connection:
        payload = await connection.scalar(select(db.jobs.c.payload).where(db.jobs.c.id == job_id))
        job = Job.model_validate(payload)
        job.status = status
        job.error = 'test failure' if status == JobStatus.FAILED else None
        job.touch()
        await connection.execute(update(db.jobs).where(db.jobs.c.id == job_id).values(
            status=status.value, payload=job_document(job), updated_at=now()))
        await release_runner(connection, job.runner_id, job.id)


async def main():
    async with engine.begin() as connection:
        await connection.run_sync(db.metadata.create_all)
        await connection.execute(insert(db.users).values(username='queue-test', password_hash='test',
            role='admin', active=True, profile={}, created_at=now()))
        for number in range(11):
            runner = Runner(id=f'queue-runner-{number}', name=f'Worker {number}', socketId=f'socket-{number}')
            await connection.execute(insert(db.runners).values(id=runner.id, socket_id=runner.socket_id,
                connected=True, current_job_id=None, payload=runner_document(runner)))
    queue = BatchQueueRepository()
    session = uuid4()
    tasks = [QueueTaskInput(name=f'Office {number}', filters={'states': ['State'],
        'rtos': [f'RTO {number}']}) for number in range(20)]
    await queue.start(session, 'queue-test', tasks)
    await queue.start(session, 'queue-test', tasks)  # Retry after a lost start response.
    first = await asyncio.gather(*(queue.claim(session, 'queue-test', f'queue-runner-{number}')
        for number in range(10)))
    assert all(item['type'] == 'assigned' for item in first)
    assert sorted(item['task']['position'] for item in first) == list(range(10))
    assert len({item['jobId'] for item in first}) == 10
    assert (await queue.claim(session, 'queue-test', 'queue-runner-10'))['type'] == 'waiting', \
        'The backend must cap a session at ten concurrent tasks even with an eleventh runner.'
    repeated = await queue.claim(session, 'queue-test', 'queue-runner-0')
    assert repeated['jobId'] == first[0]['jobId'] and repeated['recovered']

    await finish(first[0]['jobId'], JobStatus.COMPLETED)
    settled = await queue.settle(session, 'queue-test', first[0]['task']['position'])
    assert settled['status'] == 'COMPLETED'
    next_task = await queue.claim(session, 'queue-test', 'queue-runner-0')
    assert next_task['task']['position'] == 10, 'A free worker must take the next common-queue task.'

    await finish(first[1]['jobId'], JobStatus.FAILED)
    failed = await queue.settle(session, 'queue-test', first[1]['task']['position'])
    assert failed['status'] == 'PENDING' and failed['failures'] == 1
    same_worker_claim = await queue.claim(session, 'queue-test', 'queue-runner-1')
    assert same_worker_claim['task']['position'] == 11, \
        'A worker must not immediately consume its own retry while other workers are busy.'
    await finish(next_task['jobId'], JobStatus.COMPLETED)
    assert (await queue.settle(session, 'queue-test', next_task['task']['position']))['status'] == 'COMPLETED'
    retry = await queue.claim(session, 'queue-test', 'queue-runner-0')
    assert retry['task']['position'] == first[1]['task']['position']
    assert retry['task']['attempts'] == 2
    assert retry['task']['runnerId'] == 'queue-runner-0', 'The retry must be reassigned to a different worker.'
    async with engine.connect() as connection:
        retry_payload = await connection.scalar(select(db.jobs.c.payload).where(db.jobs.c.id == retry['jobId']))
    retry_job = Job.model_validate(retry_payload)
    assert str(retry_job.retry_of_job_id) == first[1]['jobId']
    assert str(retry_job.case_id) == first[1]['jobId']
    await finish(retry['jobId'], JobStatus.FAILED)
    exhausted = await queue.settle(session, 'queue-test', retry['task']['position'])
    assert exhausted['status'] == 'FAILED' and exhausted['failures'] == 2
    assert (await queue.snapshot(session, 'queue-test'))['tasks'][retry['task']['position']]['status'] == 'FAILED'
    retry_case = tasks[first[1]['task']['position']]
    manual_retry = Job(runnerId='queue-runner-1', sessionId=session, filters=retry_case.filters,
        scenarioName=retry_case.name, status=JobStatus.COMPLETED, ownerUsername='queue-test',
        retryOfJobId=retry['jobId'], caseId=first[1]['jobId'])
    async with engine.begin() as connection:
        await PostgresJobRepository()._insert(connection, manual_retry)
    recovered_task = (await queue.snapshot(session, 'queue-test'))['tasks'][retry['task']['position']]
    assert recovered_task['status'] == 'COMPLETED' and recovered_task['jobId'] == str(manual_retry.id)
    assert recovered_task['attempts'] == 3 and recovered_task['failures'] == 2
    await finish(first[2]['jobId'], JobStatus.NO_DATA)
    empty = await queue.settle(session, 'queue-test', first[2]['task']['position'])
    assert empty['status'] == 'NO_DATA' and empty['failures'] == 0, \
        'A confirmed no-data case is complete and must never enter the retry queue.'
    orphan_session = uuid4()
    await queue.start(orphan_session, 'queue-test', [QueueTaskInput(name='Orphan case',
        filters={'states': ['Other State'], 'rtos': ['RTO']})])
    orphan = await queue.claim(orphan_session, 'queue-test', 'queue-runner-0')
    await finish(orphan['jobId'], JobStatus.FAILED)
    recovered = await queue.claim(orphan_session, 'queue-test', 'queue-runner-10')
    assert recovered['type'] == 'assigned' and recovered['task']['attempts'] == 2, \
        'Another worker must recover a finished job after its coordinator disappears.'
    await queue.set_status(orphan_session, 'queue-test', 'PAUSED')
    assert (await queue.claim(orphan_session, 'queue-test', 'queue-runner-2'))['type'] == 'paused'
    large_session = uuid4()
    large_tasks = [QueueTaskInput(name=f'Load office {number}', filters={
        'states': ['Load State'], 'rtos': [f'RTO {number}']}) for number in range(1600)]
    async with engine.begin() as connection:
        for number in range(10):
            runner = Runner(id=f'load-runner-{number}', name=f'Load worker {number}',
                socketId=f'load-socket-{number}')
            await connection.execute(insert(db.runners).values(id=runner.id, socket_id=runner.socket_id,
                connected=True, current_job_id=None, payload=runner_document(runner)))
    await queue.start(large_session, 'queue-test', large_tasks)
    started = time.monotonic()
    claimed_positions = set()
    counts = [0] * 10

    async def consume(number):
        while True:
            item = await queue.claim(large_session, 'queue-test', f'load-runner-{number}')
            if item['type'] == 'done':
                return
            if item['type'] == 'waiting':
                await asyncio.sleep(.002)
                continue
            assert item['type'] == 'assigned'
            position = item['task']['position']
            assert position not in claimed_positions, f'Duplicate position {position}'
            claimed_positions.add(position)
            counts[number] += 1
            await asyncio.sleep(.05 if number == 9 else .002)
            await finish(item['jobId'], JobStatus.COMPLETED)
            assert (await queue.settle(large_session, 'queue-test', position))['status'] == 'COMPLETED'

    await asyncio.gather(*(consume(number) for number in range(10)))
    assert len(claimed_positions) == 1600
    large_snapshot = await queue.snapshot(large_session, 'queue-test')
    assert all(item['status'] == 'COMPLETED' and item['attempts'] == 1 for item in large_snapshot['tasks'])
    assert counts[9] < max(counts[:9]), 'A slower worker must receive fewer tasks from the shared queue.'
    print('Shared queue: 1,600 unique tasks, ten workers, dynamic load balance and complete SQL state passed '
          f'in {time.monotonic() - started:.1f}s; claims per worker: {counts}.')
    await engine.dispose()


asyncio.run(main())
