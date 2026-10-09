"""Read-only, owner-scoped diagnostics built from the dynamic worker registry."""
from datetime import datetime

from sqlalchemy import select

from app.db import engine, schema as db
from app.repositories.run_schedules import now


def age(value):
    if not value:
        return None
    try:
        return max(0, int((now() - datetime.fromisoformat(value)).total_seconds()))
    except (ValueError, TypeError):
        return None


async def attach_diagnostics(records):
    active = [value for value in records if value.get('sessionId') and value['status'] in
              {'PREPARING', 'RESUMING', 'RUNNING', 'PAUSING'}]
    if not active:
        return records
    async with engine.connect() as connection:
        runners = {row['id']: row for row in (await connection.execute(
            select(db.runners).order_by(db.runners.c.id))).mappings()}
        jobs = {row['id']: row for row in (await connection.execute(select(db.jobs).where(
            db.jobs.c.session_id.in_([value['sessionId'] for value in active]),
            db.jobs.c.status.not_in(['COMPLETED', 'NO_DATA', 'FAILED', 'CANCELLED'])))).mappings()}
    active_runner_ids = {job['runner_id'] for job in jobs.values()}
    runners = {runner_id: runner for runner_id, runner in runners.items()
        if runner.get('connected') or runner_id in active_runner_ids}
    for value in active:
        workers = []
        for runner_id, runner in runners.items():
            payload = runner.get('payload') or {}
            job = jobs.get(runner.get('current_job_id'))
            selected = bool(runner.get('connected') or job)
            workers.append({'id': runner_id, 'selected': selected,
                'connected': runner.get('connected', False), 'browserReady': runner.get('connected', False),
                'heartbeatAgeSeconds': age(payload.get('lastSeenAt') or payload.get('last_seen_at')),
                'reachable': runner.get('connected', False), 'jobId': job['id'] if job else None,
                'status': job['status'] if job else 'IDLE',
                'case': (job['payload'].get('scenarioName') or job['payload'].get('scenario_name')) if job else None,
                'error': job['payload'].get('error') if job else None,
                'jobAgeSeconds': age(job['updated_at'].isoformat()) if job else None})
        operation = value.get('operation') or {}
        heartbeat_age = age(operation.get('heartbeatAt') or value.get('updatedAt'))
        stage_age = age(operation.get('startedAt') or value.get('updatedAt'))
        stalled_workers = [worker['id'] for worker in workers if worker['jobId']
            and worker.get('jobAgeSeconds') is not None and worker['jobAgeSeconds'] >= 300]
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
