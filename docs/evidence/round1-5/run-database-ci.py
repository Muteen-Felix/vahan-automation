import ast
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import time
import sys

import asyncpg
import asyncio
import yaml

root = Path.cwd()
job = yaml.safe_load((root / '.github/workflows/platform.yml').read_text())['jobs']['database-integration']
name = 'vahan-round4-ci-' + secrets.token_hex(5)
password = secrets.token_urlsafe(24)
image = job['services']['postgres']['image']
results = []
env = {**os.environ, **job['env']}

def run(command, **kwargs):
    return subprocess.run(command, encoding='utf-8', errors='replace', **kwargs)

try:
    run(['docker','run','-d','--name',name,'-e','POSTGRES_USER=vahan','-e','POSTGRES_PASSWORD='+password,
         '-e','POSTGRES_DB=vahan','-p','127.0.0.1::5432',image],check=True,stdout=subprocess.DEVNULL)
    for attempt in range(90):
        if run(['docker','exec',name,'pg_isready','-U','vahan','-d','vahan'],capture_output=True).returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError('Test DB not ready')
    port = json.loads(run(['docker','inspect',name],check=True,stdout=subprocess.PIPE).stdout)[0]['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']
    env['DATABASE_URL'] = f'postgresql+asyncpg://vahan:{password}@127.0.0.1:{port}/vahan_api_test'
    create_step = next(s['run'] for s in job['steps'] if s.get('name') == 'Create isolated verification databases')
    names = ast.literal_eval(re.search(r'names = (\[.*?\])',create_step,re.S).group(1))
    async def create():
        connection = await asyncpg.connect(f'postgresql://vahan:{password}@127.0.0.1:{port}/vahan')
        try:
            for database in names:
                await connection.execute(f'CREATE DATABASE "{database}"')
        finally:
            await connection.close()
    asyncio.run(create())
    run(['python','-m','app.migrate'],cwd=root/'apps/api-server',env=env,check=True)
    script = next(s['run'] for s in job['steps'] if s.get('name') == 'Run database-backed verification in isolated processes')
    for index,line in enumerate(script.splitlines()):
        if not line.strip(): continue
        if len(sys.argv) > 1 and not re.search(sys.argv[1],line): continue
        line = line.replace('${{ job.services.postgres.id }}',name)
        line = line.replace('postgresql+asyncpg://vahan:platform-test-password@127.0.0.1:5432/',f'postgresql+asyncpg://vahan:{password}@127.0.0.1:{port}/')
        parts = shlex.split(line)
        child_env = env.copy()
        while parts and '=' in parts[0]:
            key,value = parts.pop(0).split('=',1)
            child_env[key] = value
        result = run(parts,cwd=root/'apps/api-server',env=child_env,capture_output=True,timeout=1200)
        output = result.stdout + result.stderr
        (root / f'diagnostics/round1-5-audit/db-{"rerun-" if len(sys.argv)>1 else ""}{index:02d}.log').write_text(output.replace(password,'[redacted]'),encoding='utf-8')
        label = ' '.join(parts)
        results.append({'command':label,'exitCode':result.returncode})
        print(label, 'PASS' if result.returncode == 0 else 'FAIL', flush=True)
        if result.returncode: print(output[-3500:].replace(password,'[redacted]'),flush=True)
finally:
    run(['docker','rm','-fv',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    (root/('diagnostics/round1-5-audit/db-rerun-results.json' if len(sys.argv)>1 else 'diagnostics/round1-5-audit/db-results.json')).write_text(json.dumps(results,indent=2),encoding='utf-8')
if any(result['exitCode'] for result in results): raise SystemExit(1)
