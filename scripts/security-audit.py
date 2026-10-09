#!/usr/bin/env python3
"""Collect a redacted security snapshot without changing services or application data.

Run: python3 scripts/security-audit.py --output /tmp/vahan-security.json
Only Docker metadata, GET requests, file hashes and read-only SQL are collected.
No environment values, cookies, tokens, report contents or user names are emitted.
This is evidence collection, not a vulnerability scanner or a production gate.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = [
    'app/config.py', 'app/main.py', 'app/security.py',
    'app/repositories/postgres.py', 'app/api/data.py', 'app/worker_pool.py',
]
HEADERS = [
    'server', 'content-type', 'cache-control', 'content-security-policy',
    'strict-transport-security', 'x-content-type-options', 'x-frame-options',
    'referrer-policy', 'permissions-policy', 'access-control-allow-origin',
    'access-control-allow-credentials', 'www-authenticate',
]


def command(args, *, stdin=None, timeout=30):
    result = subprocess.run(args, input=stdin, capture_output=True, text=True,
                            cwd=ROOT, timeout=timeout, check=False)
    if result.returncode:
        # Child output can contain connection strings. Never put it in evidence.
        raise RuntimeError(f'{args[0]} command failed (exit {result.returncode})')
    return result.stdout.strip()


def probe(port, path, *, invalid_token=False):
    headers = {'Origin': 'https://security-audit.invalid'}
    if invalid_token:
        headers['Authorization'] = 'Bearer security-audit-invalid-token'
    request = urllib.request.Request(f'http://127.0.0.1:{port}{path}', headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        try:
            response = opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            result = {'port': port, 'path': path, 'invalidToken': invalid_token,
                      'status': response.status,
                      'headers': {name: response.headers.get(name) for name in HEADERS}}
            # Capture only public health/auth metadata, never API response data.
            if path in {'/api/health', '/api/ready', '/api/auth/status'} and response.status == 200:
                result['publicBody'] = json.loads(response.read(8192))
            return result
    except (OSError, ValueError):
        return {'port': port, 'path': path, 'error': 'Probe unavailable'}


def collect():
    result = {
        'collectedAtUtc': datetime.now(timezone.utc).isoformat(),
        'scope': str(ROOT), 'mode': 'read-only', 'errors': [],
        'git': {'head': command(['git', 'rev-parse', 'HEAD']),
                'branch': command(['git', 'branch', '--show-current']),
                'status': command(['git', 'status', '--short']).splitlines()},
        'secretFileMetadata': [],
    }
    for relative in ['.docker.env', 'apps/api-server/.env', 'apps/web-ui/.env']:
        path = ROOT / relative
        if path.exists():
            tracked = bool(command(['git', 'ls-files', '--', relative]))
            result['secretFileMetadata'].append({
                'path': relative, 'posixMode': oct(stat.S_IMODE(path.stat().st_mode)),
                'tracked': tracked,
            })
    result['localBackups'] = [{'directory': path.parent.name,
        'bytes': path.stat().st_size, 'posixMode': oct(stat.S_IMODE(path.stat().st_mode)),
        'includesEnvironmentFile': (path.parent / '.docker.env').exists()}
        for path in sorted((ROOT / 'backups').glob('*/database.dump'))]
    try:
        ids = command(['docker', 'ps', '-aq', '--filter',
                       'label=com.docker.compose.project=vahan-automation']).split()
        containers = json.loads(command(['docker', 'inspect', *ids])) if ids else []
        result['containers'] = []
        for container in containers:
            host = container['HostConfig']
            security = host.get('SecurityOpt') or []
            result['containers'].append({
                'service': container['Config']['Labels'].get('com.docker.compose.service'),
                'name': container['Name'].lstrip('/'), 'imageId': container['Image'],
                'state': container['State']['Status'],
                'health': container['State'].get('Health', {}).get('Status'),
                'user': container['Config']['User'] or '(image default)',
                'privileged': host['Privileged'], 'readOnly': host['ReadonlyRootfs'],
                'noNewPrivileges': 'no-new-privileges:true' in security,
                'customSeccomp': any(item.startswith('seccomp=') for item in security),
                'capDrop': host['CapDrop'], 'memoryBytes': host['Memory'],
                'nanoCpus': host['NanoCpus'], 'pidsLimit': host.get('PidsLimit'),
                'logConfig': host['LogConfig'],
                'networks': list(container['NetworkSettings']['Networks']),
                'ports': container['NetworkSettings']['Ports'],
                'mounts': [{'destination': mount['Destination'], 'writable': mount['RW'],
                            'type': mount['Type']} for mount in container['Mounts']],
            })
        api = next((c['name'] for c in result['containers']
                    if c['service'] == 'api' and c['state'] == 'running'), None)
        if api:
            code = (
                "import hashlib,json,importlib.metadata,pathlib; files=" + repr(SOURCE_FILES) + "; "
                "print(json.dumps({'files':{p:hashlib.sha256(pathlib.Path('/app',p).read_bytes()).hexdigest() "
                "for p in files}, 'packages':{n:importlib.metadata.version(n) for n in "
                "['fastapi','starlette','python-multipart','cryptography','uvicorn',"
                "'python-socketio','sqlalchemy','asyncpg']}, 'databaseUser':"
                "__import__('sqlalchemy').engine.make_url(__import__('os').environ['DATABASE_URL']).username}))"
            )
            running = json.loads(command(['docker', 'exec', api, 'python', '-c', code]))
            running['files'] = {name: {'runtimeSha256': digest,
                'workspaceSha256': hashlib.sha256((ROOT / 'apps/api-server' / name).read_bytes()).hexdigest(),
                'matchesWorkspace': digest == hashlib.sha256((ROOT / 'apps/api-server' / name).read_bytes()).hexdigest()}
                for name, digest in running['files'].items()}
            result['runtimeApi'] = running
            state_code = (
                "import json,os,urllib.request,urllib.error; results=[]\n"
                "for n in [1,2]:\n"
                " identity=f'playwright-{n}'\n"
                " q=urllib.request.Request('http://127.0.0.1:8000/api/runner-state/'+identity,"
                "headers={'X-VAHAN-RUNNER-TOKEN':os.environ.get('VAHAN_API_RUNNER_TOKEN',''),"
                "'X-VAHAN-RUNNER-ID':identity})\n"
                " try:\n"
                "  with urllib.request.urlopen(q,timeout=5) as r: status=r.status\n"
                " except urllib.error.HTTPError as e: status=e.code\n"
                " results.append({'claimedIdentity':identity,'status':status})\n"
                "print(json.dumps(results))"
            )
            try:
                result['runnerStateSharedCredentialProbes'] = json.loads(
                    command(['docker', 'exec', api, 'python', '-c', state_code]))
            except (RuntimeError, subprocess.TimeoutExpired):
                result['runnerStateSharedCredentialProbes'] = {'unavailable': True}
            # A GET to the legacy controller proves credential reuse without
            # starting/stopping a worker or exposing the shared credential.
            controller_code = (
                "import json,os,urllib.request,urllib.error; "
                "q=urllib.request.Request('http://worker-control:3002/workers',"
                "headers={'X-Worker-Control-Token':os.environ.get('VAHAN_API_RUNNER_TOKEN','')}); "
                "r=urllib.request.urlopen(q,timeout=5); d=json.load(r); "
                "print(json.dumps({'status':r.status,'runningCount':d.get('runningCount')}))"
            )
            try:
                result['legacyControllerRunnerCredentialProbe'] = json.loads(
                    command(['docker', 'exec', api, 'python', '-c', controller_code]))
            except (RuntimeError, subprocess.TimeoutExpired):
                result['legacyControllerRunnerCredentialProbe'] = {'unavailable': True}
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
        result['errors'].append('Docker evidence unavailable or incomplete')

    result['httpProbes'] = [probe(port, path, invalid_token=invalid) for port, path, invalid in [
        (8000, '/api/health', False), (8000, '/api/ready', False),
        (8000, '/api/auth/status', False), (8000, '/api/users', False),
        (8000, '/api/jobs', True), (8000, '/api/audit', False),
        (8000, '/docs', False), (8000, '/openapi.json', False),
        (8000, '/socket.io/?EIO=4&transport=polling', False),
        (5173, '/', False), (5173, '/api/users', False),
    ]]
    sql = """BEGIN READ ONLY;
SELECT json_build_object(
 'database',current_database(),
 'appRole',(SELECT json_build_object('name',rolname,'superuser',rolsuper,'createRole',rolcreaterole,
             'createDb',rolcreatedb,'replication',rolreplication,'bypassRls',rolbypassrls) FROM pg_roles
             WHERE rolname=CASE WHEN EXISTS(SELECT 1 FROM pg_roles WHERE rolname='vahan_app') THEN 'vahan_app' ELSE 'vahan' END),
 'ssl',(SELECT setting FROM pg_settings WHERE name='ssl'),
 'hba',(SELECT json_agg(json_build_object('type',type,'address',address,'method',auth_method))
        FROM pg_hba_file_rules WHERE error IS NULL),
 'schemaVersion',(SELECT version_num FROM alembic_version),
 'tenantColumnCount',(SELECT count(*) FROM information_schema.columns
                     WHERE table_schema='public' AND column_name IN
                     ('tenant_id','tenant','organization_id','org_id')),
 'tenantRlsMetadata',(SELECT json_agg(json_build_object('table',relname,
                     'enabled',relrowsecurity,'forced',relforcerowsecurity))
                     FROM pg_class JOIN pg_namespace n ON n.oid=relnamespace
                     WHERE n.nspname='public' AND relname IN
                     ('main_reports','users','jobs','stored_files',
                      'browser_states','report_update_history','auth_sessions')),
 'jobStatusCounts',(SELECT json_object_agg(status,n) FROM
                   (SELECT status,count(*) n FROM jobs GROUP BY status) j),
 'userRoleCounts',(SELECT json_object_agg(role,n) FROM
                   (SELECT role,count(*) n FROM users GROUP BY role) u),
 'auditEventCount',(SELECT count(*) FROM audit_events),
 'auditTypes',(SELECT json_object_agg(event,n) FROM
              (SELECT event,count(*) n FROM audit_events GROUP BY event) a),
 'browserStateCount',(SELECT count(*) FROM browser_states),
 'databaseSizeBytes',pg_database_size(current_database()));
ROLLBACK;
"""
    try:
        output = command(['docker', 'compose', '--env-file', '.docker.env', 'exec', '-T',
                          'postgres', 'psql', '-X', '-U', 'vahan', '-d', 'vahan', '-At'], stdin=sql)
        result['database'] = next(json.loads(line) for line in output.splitlines() if line.startswith('{'))
    except (RuntimeError, OSError, ValueError, StopIteration, subprocess.TimeoutExpired):
        result['errors'].append('Read-only database evidence unavailable')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = collect()
    document = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document, encoding='utf-8')
        print(json.dumps({'output': str(args.output.resolve()), 'errors': result['errors'],
                          'containerCount': len(result.get('containers', []))}))
    else:
        print(document, end='')
    return bool(result['errors'])


if __name__ == '__main__':
    raise SystemExit(main())
