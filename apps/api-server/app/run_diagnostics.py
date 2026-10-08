"""Read-only, owner-scoped operational diagnostics; never alter running work."""
import asyncio
import json
from urllib.request import urlopen
from datetime import datetime
from sqlalchemy import select
from app.config import settings
from app.db import engine, schema as db
from app.repositories.run_schedules import now


def age(value):
    if not value:
        return None
    try:
        return max(0, int((now() - datetime.fromisoformat(value)).total_seconds()))
    except (ValueError, TypeError):
        return None


async def read_health(number):
    def read():
        try:
            service = 'runner' if number == 1 else f'runner-{number}'
            with urlopen(f'http://{service}:3001/health', timeout=1) as response:
                value = json.load(response)
            return {key: value.get(key) for key in ('connected', 'browserReady', 'optionsBusy')}
        except Exception:
            return {'reachable': False}
    return await asyncio.to_thread(read)


async def attach_diagnostics(records):
    active = [value for value in records if value.get('sessionId') and value['status'] in {'PREPARING','RESUMING','RUNNING','PAUSING'}]
    if not active:
        return records
    async with engine.connect() as connection:
        runners = {row['id']: row for row in (await connection.execute(select(db.runners))).mappings()}
        pool = await connection.scalar(select(db.app_settings.c.value).where(db.app_settings.c.key == 'docker-worker-pool')) or {}
        # A schedule owner sees only jobs belonging to their own session.
        jobs = {row['id']: row for row in (await connection.execute(select(db.jobs).where(
            db.jobs.c.session_id.in_([value['sessionId'] for value in active]),
            db.jobs.c.status.not_in(['COMPLETED', 'NO_DATA', 'FAILED', 'CANCELLED'])))).mappings()}
    count = max([value['workerCount'] for value in active] + [pool.get('desiredCount', 0)])
    health = await asyncio.gather(*(read_health(number) for number in range(1, count + 1))) if settings.runner_health_checks else [{}] * count
    for value in active:
        workers = []
        for number in range(1, count + 1):
            runner_id = f'playwright-{number}'
            runner = runners.get(runner_id) or {}
            payload = runner.get('payload') or {}
            job = jobs.get(runner.get('current_job_id'))
            workers.append({'id': runner_id, 'selected': number <= value['workerCount'],
                'connected': runner.get('connected', False), 'heartbeatAgeSeconds': age(payload.get('lastSeenAt') or payload.get('last_seen_at')),
                **health[number-1], 'jobId': job['id'] if job else None,
                'status': job['status'] if job else 'IDLE',
                'case': (job['payload'].get('scenarioName') or job['payload'].get('scenario_name')) if job else None,
                'error': (job['payload'].get('error')) if job else None,
                'jobAgeSeconds': age(job['updated_at'].isoformat()) if job else None})
        operation = value.get('operation') or {}
        heartbeat_age = age(operation.get('heartbeatAt') or value.get('updatedAt'))
        stage_age = age(operation.get('startedAt') or value.get('updatedAt'))
        stalled_workers = [worker['id'] for worker in workers if worker['selected'] and worker.get('jobAgeSeconds', 0) is not None and worker.get('jobAgeSeconds', 0) >= 300]
        warning = None
        if heartbeat_age is not None and heartbeat_age >= 360:
            warning = 'The scheduler has not reported for over 6 minutes. Check the API / scheduler.'
        elif value['status'] in {'PREPARING', 'RESUMING'} and stage_age is not None and stage_age >= 300:
            warning = 'Preparation has remained at this step for over 5 minutes. Check the error and worker states below.'
        elif stalled_workers:
            warning = 'No new job status for over 5 minutes: ' + ', '.join(stalled_workers) + '. This is a possible delay, not a confirmed hang.'
        value['diagnostics'] = {'checkedAt': now().isoformat(), 'heartbeatAgeSeconds': heartbeat_age,
            'stageAgeSeconds': stage_age, 'warning': warning, 'workers': workers}
    return records
