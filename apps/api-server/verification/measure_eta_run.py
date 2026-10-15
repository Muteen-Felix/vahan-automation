"""Measure UI ETA on 100 durable cases over at least 30 real minutes.

Three real HTTP/Socket.IO protocol clients use synthetic NO_RECORD results.
Case durations are deliberately paced; this is not a VAHAN browser benchmark.
Never runs against a production database. No clock or elapsed time is mocked.
"""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import socket
import sys
import tempfile
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_worker_lifecycle import WorkerLifecycleTest, QueueTaskInput, BatchQueueRepository
from test_worker_lifecycle import engine, db, ui_contract, apply_pool, now, insert, services
from test_worker_lifecycle import httpx, socketio, settings, ReportResultRequest
from sqlalchemy import select, func

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path(os.environ.get('VAHAN_ETA_OUTPUT_DIR', str(ROOT / 'diagnostics/eta-measurement')))


async def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fixture = WorkerLifecycleTest()
    resumed = '--resume' in sys.argv
    if resumed:
        fixture.owner = settings.ui_auth_username
        fixture.workers = [f'lifecycle-{i}' for i in range(3)]
        fixture.sockets = []; fixture.process = None
        fixture.log = tempfile.TemporaryFile(mode='w+b')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); fixture.port = listener.getsockname()[1]
        fixture.origin = f'http://127.0.0.1:{fixture.port}'
        fixture.http = httpx.AsyncClient(base_url=fixture.origin, timeout=30)
        await fixture.start_api()
        # Automatic reconnect is required for a sustained measurement rather
        # than the short restart test's deliberately disconnected clients.
        for worker in fixture.workers:
            client = socketio.AsyncClient(reconnection=True)
            await client.connect(fixture.origin, transports=['websocket'], namespaces=['/runner'], auth={
                'runnerId':worker,'runnerName':worker,'engine':'playwright','source':'new','token':settings.runner_token})
            fixture.sockets.append(client)
    else:
        await fixture.asyncSetUp()
    estimator = None
    heartbeat_task = None
    samples = []
    assigned = set()
    completed = set()
    peak = 0
    processing = set()
    interruptions = []
    socket_locks = [asyncio.Lock() for _ in fixture.workers]
    try:
        queue, session, profile = BatchQueueRepository(), uuid4(), uuid4()
        if resumed:
            from uuid import UUID
            progress = json.loads((OUTPUT / 'eta-progress.json').read_text(encoding='utf-8'))
            session = UUID(progress['sessionId'])
            started = datetime.fromisoformat(progress['startedAt'])
            old_jobs = await services.jobs.list_all()
            assigned.update(str(job.id) for job in old_jobs)
            completed.update(str(job.id) for job in old_jobs if job.status.value == 'NO_DATA')
            peak = progress['peakConcurrent']
            samples = [json.loads(line) for line in (OUTPUT / 'eta-observations.jsonl').read_text(encoding='utf-8').splitlines()]
            interruptions.append(dict(type='measurement-process-restart', observedAt=now().isoformat(),
                completedBeforeRestart=len(completed)))
        else:
            started = None
        observed = [{**seed, 'found': True, 'count': 1, 'inputType': 'text', 'matchedBy': 'selector'}
                    for seed in ui_contract.SEEDS]
        validation = await ui_contract.evaluate({'status': 'PASS', 'observedControls': observed}, fixture.workers[0])
        gate = str(uuid4())
        async with engine.begin() as connection:
            await connection.execute(insert(db.ui_preflight_checks).values(id=gate, owner_username=fixture.owner,
                runner_ids=fixture.workers, version_id=validation['versionId'], status='PASS',
                reports=[validation], created_at=now()))
        await apply_pool(3)
        if not resumed:
            await queue.start(session, fixture.owner, [QueueTaskInput(name=f'SYNTHETIC ETA office {i:03}', filters={
                'states': ['SYNTHETIC ETA State'], 'rtos': [f'SYNTHETIC ETA office {i:03}'],
                'fromYear': '2026', 'toYear': '2026'}) for i in range(100)], 3,
                automatic_workers=True, profile_id=profile, filter_name='SYNTHETIC ETA measurement — 100 cases')
        await ui_contract.bind_gate(session, gate)
        started = started or datetime.now(timezone.utc)
        elapsed_before = (datetime.now(timezone.utc)-started).total_seconds()
        start_clock = time.monotonic()-elapsed_before
        estimator = await asyncio.create_subprocess_exec('node',
            str(ROOT / 'apps/web-ui/scripts/measure-schedule-eta.mjs'),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        def schedule_snapshot(done):
            return dict(sessionId=str(session), lastRunAt=started.isoformat(), activeElapsedMs=0,
                activeSegmentStartedAt=started.isoformat(), executionEpoch=0, total=100, done=done, status='RUNNING')
        for sample in samples:
            estimator.stdin.write((json.dumps(dict(schedule=schedule_snapshot(sample['done']),
                now=datetime.fromisoformat(sample['observedAt']).timestamp()*1000))+'\n').encode())
            await estimator.stdin.drain()
            await estimator.stdout.readline()
        async def acknowledge(index, event, payload):
            async with socket_locks[index]:
                return await fixture.sockets[index].call(event, payload, namespace='/runner', timeout=15)
        async def heartbeat():
            while True:
                replies = await asyncio.gather(*(acknowledge(i, 'runner:heartbeat', {})
                    for i, client in enumerate(fixture.sockets) if client.connected), return_exceptions=True)
                for reply in replies:
                    if isinstance(reply, Exception) or not reply.get('ok'):
                        interruptions.append(dict(type='heartbeat', observedAt=now().isoformat(), detail=str(reply)))
                await asyncio.sleep(5)
        heartbeat_task = asyncio.create_task(heartbeat())
        async def poll_estimate():
            while len(completed) < 100:
                if heartbeat_task.done():
                    heartbeat_task.result()
                snapshot = await queue.snapshot(session, fixture.owner)
                done = sum(task['status'] in {'COMPLETED', 'NO_DATA'} for task in snapshot['tasks'])
                stamp = datetime.now(timezone.utc)
                schedule = schedule_snapshot(done)
                estimator.stdin.write((json.dumps(dict(schedule=schedule, now=stamp.timestamp()*1000))+'\n').encode())
                await estimator.stdin.drain()
                estimate = json.loads(await asyncio.wait_for(estimator.stdout.readline(), 10))
                sample = dict(observedAt=stamp.isoformat(), elapsedSeconds=time.monotonic()-start_clock,
                    done=done, **estimate)
                samples.append(sample)
                with (OUTPUT / 'eta-observations.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(sample)+'\n')
                (OUTPUT / 'eta-progress.json').write_text(json.dumps(dict(sessionId=str(session),
                    startedAt=started.isoformat(), assigned=len(assigned), completed=len(completed),
                    peakConcurrent=peak, latest=sample), indent=2), encoding='utf-8')
                if samples:
                    print(f'ETA run: {done}/100 cases; elapsed={sample["elapsedSeconds"]:.1f}s; '
                          f'forecast={estimate["remainingMs"]}; peak={peak}', flush=True)
                await asyncio.sleep(60)
        async def worker(index):
            nonlocal peak
            await asyncio.sleep(index*18)
            while len(completed) < 100:
                item = await fixture.claim(fixture.workers[index], session)
                while item['type'] in {'waiting', 'runner_unavailable'}:
                    if item['type'] == 'runner_unavailable':
                        interruptions.append(dict(type='claim-waiting-for-runner', runner=fixture.workers[index], observedAt=now().isoformat()))
                        if fixture.sockets[index].connected:
                            await acknowledge(index, 'runner:heartbeat', {})
                    await asyncio.sleep(1)
                    item = await fixture.claim(fixture.workers[index], session)
                if item['type'] == 'done':
                    return
                assert item['type'] == 'assigned', item
                assert item['jobId'] not in assigned, item
                assigned.add(item['jobId']); processing.add(item['jobId'])
                peak = max(peak, len(processing))
                # Fifty-four seconds per case, three workers staggered 18s.
                # Total elapsed is at least 1836s (30m36s), with 100 real commits.
                await asyncio.sleep(54)
                for status in ['OPENING_VAHAN', 'FILLING_FILTERS', 'SUBMITTING', 'WAITING_RESULT']:
                    reply = await acknowledge(index, 'job:status', {'jobId':item['jobId'], 'status':status})
                    assert reply['ok'], reply
                command = ReportResultRequest(result='NO_RECORD', message='No record found', observedAt=now(),
                    pageUrl='https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en')
                response = await fixture.http.post(f"/api/jobs/{item['jobId']}/report-result", headers={
                    'X-VAHAN-RUNNER-TOKEN':settings.runner_token,'X-VAHAN-RUNNER-ID':fixture.workers[index]},
                    json=command.model_dump(mode='json',by_alias=True))
                assert response.status_code == 200, response.text
                processing.remove(item['jobId']); completed.add(item['jobId'])
        observer = asyncio.create_task(poll_estimate())
        await asyncio.gather(*(worker(i) for i in range(3)))
        finished = datetime.now(timezone.utc)
        duration = time.monotonic()-start_clock
        await observer
        snapshot = await queue.snapshot(session, fixture.owner)
        assert len(snapshot['tasks']) == 100
        assert all(task['status'] == 'NO_DATA' for task in snapshot['tasks'])
        assert len(completed) == 100 and peak == 3 and duration >= 1800
        jobs = await services.jobs.list_all()
        assert len({job.case_id or job.id for job in jobs}) == 100
        assert len({job.case_id or job.id for job in jobs if job.status.value == 'NO_DATA'}) == 100
        async with engine.connect() as connection:
            assert await connection.scalar(select(func.count()).select_from(db.jobs)) == len(assigned)
            assert await connection.scalar(select(func.count()).select_from(db.report_update_history)) == 100
        forecasts = []
        for sample in samples:
            if sample['finishesAt'] and 0 < sample['done'] < 100:
                expected = datetime.fromisoformat(sample['finishesAt'].replace('Z', '+00:00'))
                error = (expected-finished).total_seconds()
                remaining = (finished-datetime.fromisoformat(sample['observedAt'])).total_seconds()
                forecasts.append(dict(done=sample['done'], observedAt=sample['observedAt'],
                    predictedFinish=sample['finishesAt'], signedErrorSeconds=error,
                    absoluteErrorSeconds=abs(error), remainingErrorPercent=abs(error)/remaining*100,
                    totalDurationErrorPercent=abs(error)/duration*100))
        def metrics(values):
            if not values:
                return dict(samples=0, medianRemainingErrorPercent=None, maxRemainingErrorPercent=None)
            errors = sorted(v['absoluteErrorSeconds'] for v in values)
            return dict(samples=len(values), medianAbsoluteSeconds=statistics.median(errors),
                medianRemainingErrorPercent=statistics.median(v['remainingErrorPercent'] for v in values),
                maxRemainingErrorPercent=max(v['remainingErrorPercent'] for v in values),
                meanAbsoluteSeconds=statistics.mean(errors), maxAbsoluteSeconds=max(errors),
                p90AbsoluteSeconds=errors[min(len(errors)-1, int(len(errors)*.9))])
        bands={f'{lo}-{hi}%':metrics([v for v in forecasts if lo <= v['done'] < hi])
               for lo,hi in [(0,25),(25,50),(50,75),(75,100)]}
        # D-28 / T15(1): a run only counts when nothing paused, restarted or lost a worker or the
        # network between its first and last case.
        ineligible = []
        if resumed:
            ineligible.append('run was resumed from a previous process (--resume)')
        ineligible += [f"interruption: {item['type']} at {item['observedAt']}" for item in interruptions]
        if len(completed) != 100 or len(assigned) != 100 or len(jobs) != 100:
            ineligible.append(f'attempts/assigned/completed = {len(jobs)}/{len(assigned)}/{len(completed)}, expected 100/100/100')
        if duration < 1800:
            ineligible.append(f'duration {duration:.0f}s is below 1800s')
        for key in ('25-50%', '50-75%', '75-100%'):
            if bands[key]['samples'] == 0:
                ineligible.append(f'no ETA samples in {key}')
        thresholds = {'50-75%': 25, '75-100%': 15}
        met = {key: bands[key]['samples'] > 0 and bands[key]['medianRemainingErrorPercent'] <= limit
               for key, limit in thresholds.items()}
        status = 'INVALID' if ineligible else ('PASS' if all(met.values()) else 'FAIL')
        passed = status == 'PASS'
        gaps = sorted(b['elapsedSeconds']-a['elapsedSeconds'] for a, b in zip(samples, samples[1:]))
        result = dict(status=status, ineligibleReasons=ineligible, thresholdsMet=met,
            sampleIntervalSeconds=60, medianObservedIntervalSeconds=statistics.median(gaps) if gaps else None,
            etaNullSamples=sum(sample['remainingMs'] is None for sample in samples), totalSamples=len(samples),
            progressBands=bands, thresholds=thresholds,
            workload='SYNTHETIC protocol workers, real wall clock/HTTP/Socket.IO/SQL',
            sessionId=str(session), startedAt=started.isoformat(), finishedAt=finished.isoformat(),
            elapsedSeconds=duration, uniqueAssigned=len(assigned), uniqueCompleted=len(completed),
            peakConcurrent=peak, cases=100, attempts=len(jobs), interruptions=interruptions,
            allForecasts=metrics(forecasts),
            after20Completed=metrics([v for v in forecasts if v['done'] >= 20]), predictions=forecasts)
        (OUTPUT / 'eta-measurement.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k!='predictions'}), flush=True)
        assert passed, f'ETA measurement {status}: {ineligible or "median error above D-28 thresholds"}'
    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        if estimator and estimator.returncode is None:
            estimator.stdin.close()
            await estimator.wait()
        await fixture.asyncTearDown()


if __name__ == '__main__':
    asyncio.run(main())
