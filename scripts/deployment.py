"""Drain accepted work before changing API/runner images; never cancel jobs."""
import json
import subprocess
import time


def sql(command, statement):
    result=subprocess.run([*command,'exec','-T','postgres','psql','-X','-U','vahan','-d','vahan','-At',
                           '-v','ON_ERROR_STOP=1'],input=statement,capture_output=True,text=True,check=True)
    return result.stdout.strip()


def running(command, service):
    result=subprocess.run([*command,'ps','--status','running','-q',service],capture_output=True,text=True,check=True)
    return bool(result.stdout.strip())


def drain(command, timeout=300):
    if not running(command,'api'):return False
    changed=sql(command,"UPDATE app_settings SET value=jsonb_set(value::jsonb,'{phase}','\"updating\"'::jsonb) WHERE key='docker-worker-pool' AND value::jsonb->>'phase'='ready' RETURNING value")
    if not any(line.startswith('{') for line in changed.splitlines()):
        raise RuntimeError('Worker pool is already changing; deployment refused.')
    print('New assignments are paused while existing work finishes.',flush=True)
    deadline=time.monotonic()+timeout
    try:
        while time.monotonic()<deadline:
            raw=sql(command,"""BEGIN READ ONLY;
SELECT json_build_object('jobs',(SELECT count(*) FROM jobs WHERE status NOT IN
 ('COMPLETED','NO_DATA','FAILED','CANCELLED')),'leases',(SELECT count(*) FROM runner_planning_leases WHERE expires_at>now()));
ROLLBACK;""")
            counts=next(json.loads(line) for line in raw.splitlines() if line.startswith('{'))
            if not counts['jobs'] and not counts['leases']:return True
            time.sleep(2)
        raise RuntimeError('Accepted work is still active; no restart was performed.')
    except BaseException:
        resume(command);raise


def resume(command):
    sql(command,"UPDATE app_settings SET value=jsonb_set(value::jsonb,'{phase}','\"ready\"'::jsonb) WHERE key='docker-worker-pool'")
