"""Read-only release check. Never interrupt jobs or change queue state."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ['docker', 'compose', '--env-file', '.docker.env']
# A saved Daily schedule that still owns a report session blocks migration 0014a/0015 (PLAN D-35, Q1 = A). The text
# must stay identical to DAILY_BLOCKING_SQL in apps/api-server/migrations/versions/0014a_daily_schedule_guard.py.
# `status` is intentionally not part of the condition: a missing/NULL status would be skipped by `status IN (...)`.
DAILY_BLOCKING_SQL = "value->>'repeat' = 'daily' AND COALESCE(value->>'sessionId', '') <> ''"
RESULT_KEYS = {'activeJobs', 'planningLeases', 'runningQueues', 'activeSchedules', 'blockingDailySchedules'}
QUERY = f"""SELECT json_build_object(
 'activeJobs', (SELECT count(*) FROM jobs WHERE status NOT IN ('COMPLETED','NO_DATA','FAILED','CANCELLED')),
 'planningLeases', (SELECT count(*) FROM runner_planning_leases WHERE expires_at > now()),
 'runningQueues', (SELECT count(*) FROM batch_queue_sessions WHERE status = 'RUNNING'),
 'activeSchedules', (SELECT count(*) FROM app_settings WHERE key LIKE 'automatic-report-schedule:%'
   AND value->>'status' IN ('PREPARING','RESUMING','RUNNING','PAUSING')),
 'blockingDailySchedules', (SELECT count(*) FROM app_settings WHERE key LIKE 'automatic-report-schedule:%'
   AND {DAILY_BLOCKING_SQL}));"""


def capture(arguments):
    try:
        return subprocess.run([*COMPOSE, *arguments], cwd=ROOT, check=True,
            capture_output=True, text=True, timeout=30).stdout.strip()
    except (subprocess.SubprocessError, OSError) as error:
        raise RuntimeError('Cannot verify deployment safety. Check Docker and PostgreSQL before retrying.') from error


def check_release():
    postgres = capture(['ps', '--status', 'running', '-q', 'postgres'])
    if not postgres:
        if capture(['ps', '-a', '-q']):
            raise RuntimeError('Existing stack has no running PostgreSQL. Restore database access before deploying.')
        return {'freshInstall': True}
    # A new, empty database is safe; partially initialized existing schemas fail closed.
    initialized = capture(['exec', '-T', 'postgres', 'psql', '-U', 'vahan', '-d', 'vahan',
        '-XAt', '-v', 'ON_ERROR_STOP=1', '-c', "SELECT to_regclass('public.jobs') IS NOT NULL"])
    if initialized == 'f':
        return {'freshInstall': True}
    try:
        result = json.loads(capture(['exec', '-T', 'postgres', 'psql', '-U', 'vahan', '-d', 'vahan',
            '-XAt', '-v', 'ON_ERROR_STOP=1', '-c', QUERY]))
        if set(result) != RESULT_KEYS or any(
            type(value) is not int or value < 0 for value in result.values()):
            raise ValueError('Invalid deployment check.')
    except (ValueError, TypeError) as error:
        raise RuntimeError('Cannot verify deployment safety: invalid database evidence.') from error
    if any(result.values()):
        advice = ('. Let active jobs finish and pause running queues/schedules before deploying. Saved data is preserved.')
        if result['blockingDailySchedules']:
            advice += (' blockingDailySchedules counts saved Daily schedules that still own a report session, including'
                ' PAUSED ones: migration 0015 would stop on them. On the OLD version let the run finish (preferred),'
                ' or Stop or Delete the schedule, then deploy (docs/release/INSTALL.md section 7).')
        raise RuntimeError('Deployment blocked: '+', '.join(f'{key}={value}' for key,value in result.items())+advice)
    return result
