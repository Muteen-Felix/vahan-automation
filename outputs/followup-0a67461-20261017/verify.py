"""Post-D3 checks on frozen release image IDs. Disposable fixtures only."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PRE = ROOT / 'outputs/release-F-0a6746187e82-20261016T090229Z'
OLD = ROOT / 'outputs/D3-0a6746187e82-20261016T093436Z'
STATE = json.loads((PRE / 'staging-environment.json').read_text())
SOURCE = Path(STATE['root'])
SHA = STATE['sha']
MANIFEST = PRE / 'package/vahan-0a6746187e82-manifest.json'
manifest = json.loads(MANIFEST.read_text())
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ').lower()
prefix = 'vahan-followup-' + stamp
network = prefix
db_name, web_name = prefix + '-db', prefix + '-web'
api_name = prefix + '-api'
created = []
ledger = []


def now():
    return datetime.now(timezone.utc).isoformat()


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run(cmd, timeout=180, cwd=ROOT):
    proc = subprocess.run([str(x) for x in cmd], cwd=cwd, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=timeout)
    if proc.returncode:
        raise RuntimeError('Command failed: ' + ' '.join(str(x) for x in cmd[:4]) + '\n' + proc.stderr[-3000:])
    if 'unittest' in cmd:
        (OUT / 'def15-unittest.log').write_text(proc.stderr + proc.stdout, encoding='utf-8')
    return proc.stdout


def check(item, function):
    entry = {'item': item, 'sha': SHA, 'startedAt': now(), 'manifestDigest': STATE['manifestDigest']}
    try:
        entry['result'] = function()
        entry['status'] = 'PASS'
    except Exception as exc:
        entry['status'] = 'FAIL'
        entry['blocker'] = str(exc)
    entry['finishedAt'] = now()
    ledger.append(entry)
    write('checklist.json', ledger)
    print(item + ': ' + entry['status'], flush=True)


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def identity():
    assert sha(MANIFEST) == STATE['manifestDigest']
    assert manifest['sourceCommit'] == manifest['imageRevision'] == SHA
    for name, expected in manifest['files'].items():
        assert sha(PRE / 'package' / name) == expected, name
    with zipfile.ZipFile(next((PRE / 'package').glob('*-source.zip'))) as archive:
        for name in ['apps/api-server/requirements.lock', 'apps/browser-runner/package-lock.json',
                     'compose.yaml', 'docker/seccomp_profile.json', 'docker/nginx.conf']:
            assert archive.read(name) == (SOURCE / name).read_bytes(), name
    images = []
    for ref, expected in manifest['imageIds'].items():
        info = json.loads(run(['docker', 'image', 'inspect', expected]))[0]
        assert info['Id'] == expected
        upstream = manifest['images'][ref]['upstream']
        labels = info['Config'].get('Labels') or {}
        if not upstream:
            assert labels.get('org.opencontainers.image.revision') == SHA
            assert labels.get('org.opencontainers.image.version') == '1.0.0'
        else:
            assert ref in (SOURCE / 'compose.yaml').read_text()
            assert ref.rsplit('@', 1)[1] == expected
        assert info['Os'] + '/' + info['Architecture'] == 'linux/amd64'
        images.append({'ref': ref, 'id': expected, 'platform': 'linux/amd64',
                       'upstream': upstream, 'revision': labels.get('org.opencontainers.image.revision'),
                       'version': labels.get('org.opencontainers.image.version')})
    write('identity.json', {'checkedAt': now(), 'sha': SHA, 'manifestDigest': sha(MANIFEST),
                            'images': images, 'frozenPackageUnchanged': True})
    return ['identity.json']


def snapshot():
    result = run([sys.executable, ROOT / 'scripts/config-snapshot.py', '--project-dir', SOURCE,
                  '--env-file', SOURCE / '.docker.env', '--image-ids', '--out', OUT / 'config-snapshot.json'], cwd=SOURCE)
    snap = json.loads((OUT / 'config-snapshot.json').read_text())
    old = json.loads((PRE / 'staging-config-snapshot.json').read_text())
    assert not snap['reviewErrors'], snap['reviewErrors']
    changed = {k: [old.get(k), snap.get(k)] for k in old.keys() | snap.keys()
               if k not in {'generatedAt', 'imageIds'} and old.get(k) != snap.get(k)}
    assert not changed, changed
    assert snap['values']['runner.replicas'] == '3'
    write('snapshot-provenance.json', {'recordedAt': now(), 'sha': SHA,
        'context': 'Post-D3 rendering of retained staging configuration; no original staging containers remain',
        'historicalSnapshot': str((PRE / 'staging-config-snapshot.json').relative_to(ROOT)),
        'historicalSnapshotSha256': sha(PRE / 'staging-config-snapshot.json'),
        'historicalGeneratedAt': old['generatedAt'], 'configurationDifferences': changed,
        'historicalImageIds': old.get('imageIds'), 'currentImageIds': snap.get('imageIds'),
        'stdout': result.strip()})
    return ['config-snapshot.json', 'snapshot-provenance.json']


def runtime():
    runner = manifest['imageIds']['vahan-review/runner:1.0.0']
    raw = run(['docker', 'run', '--rm', '--pull=never', '--init', '--shm-size=1g',
               '--network=none', '--security-opt=seccomp=' + str(SOURCE / 'docker/seccomp_profile.json'),
               '--entrypoint', 'node', runner, 'test-container-runtime.mjs'])
    result = json.loads(raw)
    assert result['sandbox'] and result['uid'] != 0 and result['ocr']['passed']
    write('container-runtime.json', {'checkedAt': now(), 'sha': SHA, 'imageId': runner,
                                    'seccompSha256': sha(SOURCE / 'docker/seccomp_profile.json'), 'result': result})
    return ['container-runtime.json']


def setup_fixtures():
    run(['docker', 'network', 'create', '--label', 'vahan.followup=' + prefix, network])
    created.append(('network', network))
    run(['docker', 'run', '-d', '--pull=never', '--name', db_name, '--network', network,
         '--label', 'vahan.followup=' + prefix, '--tmpfs', '/var/lib/postgresql/data',
         '-e', 'POSTGRES_PASSWORD=followup-fixture-password', '-e', 'POSTGRES_USER=vahan',
         '-e', 'POSTGRES_DB=vahan_schedule_followup_test',
         manifest['imageIds'][next(r for r in manifest['imageIds'] if '/postgres:' in r)]])
    created.append(('container', db_name))
    for _ in range(30):
        result = subprocess.run(['docker', 'exec', db_name, 'pg_isready', '-U', 'vahan'], capture_output=True)
        if result.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError('Disposable PostgreSQL not ready')
    return ['Disposable isolated PostgreSQL and web only; no real VAHAN jobs or original volumes']


def def15():
    raw = run(['docker', 'run', '--rm', '--pull=never', '--network', network,
         '--mount', 'type=bind,source=' + str(ROOT / 'apps/api-server/verification/test_run_schedules.py') + ',target=/checks/test_run_schedules.py,readonly',
         '-e', 'DATABASE_URL=postgresql+asyncpg://vahan:followup-fixture-password@' + db_name + ':5432/vahan_schedule_followup_test',
         '-e', 'VAHAN_SCHEDULE_TEST_DATABASE=vahan_schedule_followup_test', '-e', 'PYTHONPATH=/app',
         '--entrypoint', 'python', manifest['imageIds']['vahan-review/api:1.0.0'],
         '-m', 'unittest', 'discover', '-s', '/checks', '-p', 'test_run_schedules.py', '-k', 'large', '-v'])
    log = (OUT / 'def15-unittest.log').read_text()
    assert 'Ran 3 tests' in log and '\nOK' in log, log
    write('def15.json', {'checkedAt': now(), 'sha': SHA, 'status': 'PASS', 'selectedTests': [
        'test_one_worker_ignores_legacy_large_count_and_runs_one_case',
        'test_three_workers_ignores_legacy_large_count_and_runs_three_cases',
        'test_resume_ignores_persisted_large_worker_count'], 'stdout': raw,
        'database': 'disposable vahan_schedule_followup_test',
        'harnessSha256': sha(ROOT / 'apps/api-server/verification/test_run_schedules.py')})
    return ['def15.json', 'def15-unittest.log']


def setup_api():
    run(['docker', 'exec', db_name, 'psql', '-U', 'vahan', '-d', 'vahan_schedule_followup_test',
         '-c', 'CREATE DATABASE vahan_web_followup_test'])
    url = 'postgresql+asyncpg://vahan:followup-fixture-password@' + db_name + ':5432/vahan_web_followup_test'
    role_password = secrets.token_hex(24)
    run(['docker', 'run', '--rm', '--pull=never', '--network', network, '-e', 'DATABASE_URL=' + url,
         '-e', 'DB_APP_PASSWORD=' + role_password, '--entrypoint', 'python',
         manifest['imageIds']['vahan-review/api:1.0.0'], '-m', 'app.provision_database'])
    url = url.replace('vahan:followup-fixture-password@', 'vahan_app:' + role_password + '@')
    run(['docker', 'run', '-d', '--pull=never', '--name', api_name, '--network', network,
         '--network-alias', 'api', '--label', 'vahan.followup=' + prefix,
         '-e', 'DATABASE_URL=' + url, '-e', 'VAHAN_ENVIRONMENT=test',
         '-e', 'VAHAN_UI_AUTH_TOKEN_SECRET=' + secrets.token_hex(32),
         '-e', 'VAHAN_UI_AUTH_USERNAME=followup-admin',
         '-e', 'VAHAN_UI_AUTH_PASSWORD=followup-fixture-password',
         manifest['imageIds']['vahan-review/api:1.0.0']])
    created.append(('container', api_name))
    for _ in range(30):
        proc = subprocess.run(['docker', 'exec', api_name, 'python', '-c',
            "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8000/api/ready').status==200"], capture_output=True)
        if proc.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError('Disposable API did not become ready')
    run(['docker', 'run', '-d', '--pull=never', '--name', web_name, '--network', network,
         '--label', 'vahan.followup=' + prefix, '--network-alias', 'web',
         '-p', '127.0.0.1::80', manifest['imageIds']['vahan-review/web:1.0.0']])
    created.append(('container', web_name))
    return ['Disposable restricted-role API, separate empty migrated database, fixture account only']


def nginx():
    port = run(['docker', 'port', web_name, '80/tcp']).strip().rsplit(':', 1)[1]
    url = 'http://127.0.0.1:' + port
    with urllib.request.urlopen(url, timeout=20) as response:
        headers = dict(response.headers)
        assert response.status == 200
        assert headers['Server'] == 'nginx', headers['Server']
        assert "script-src 'self'" in headers['Content-Security-Policy']
    config = run(['docker', 'exec', web_name, 'nginx', '-T'])
    assert re.search(r'\bserver_tokens\s+off;', config)
    # Observe the real login app and CSP in a packaged sandboxed browser through nginx.
    js = '''(async()=>{const {chromium}=require('playwright');
      const browser=await chromium.launch({headless:true,chromiumSandbox:true});
      try {const page=await browser.newPage();const violations=[];
       await page.addInitScript(()=>document.addEventListener('securitypolicyviolation',e=>{
        (window.__cspViolations ||= []).push({directive:e.effectiveDirective,blocked:e.blockedURI});}));
       await page.goto('http://web/',{waitUntil:'networkidle'});
       await page.locator('input[type=password]').waitFor({timeout:20000});
       const result={passwordInputs:await page.locator('input[type=password]').count(),
        cspViolations:await page.evaluate(()=>window.__cspViolations || [])};
       console.log(JSON.stringify(result));
      } finally {await browser.close()}})().catch(e=>{console.error(e);process.exit(1)})'''
    raw = run(['docker', 'run', '--rm', '--pull=never', '--init', '--shm-size=1g', '--network', network,
               '--security-opt=seccomp=' + str(SOURCE / 'docker/seccomp_profile.json'), '--entrypoint', 'node',
               manifest['imageIds']['vahan-review/runner:1.0.0'], '-e', js])
    browser = json.loads(raw)
    assert browser['passwordInputs'] == 1
    assert all(v['directive'] == 'style-src-elem' and v['blocked'].startswith('https://fonts.googleapis.com/')
               for v in browser['cspViolations']), browser
    write('nginx-runtime.json', {'checkedAt': now(), 'sha': SHA, 'webImageId': manifest['imageIds']['vahan-review/web:1.0.0'],
                                'httpStatus': 200, 'headers': headers, 'serverTokensOff': True,
                                'browser': browser, 'scope': 'Real login page through packaged nginx; original D3 covers authenticated workflows',
                                'fontCspFinding': 'Original artifact blocks remote Google Fonts; login renders using fallback fonts. Fix verified separately on working-tree web assets.'})
    # Verify the working-tree fix separately: same nginx config, newly built web assets mounted read-only.
    patched_name = prefix + '-web-patched'
    run(['docker', 'run', '-d', '--pull=never', '--name', patched_name, '--network', network,
         '--label', 'vahan.followup=' + prefix, '--network-alias', 'web-patched',
         '--mount', 'type=bind,source=' + str(ROOT / 'apps/web-ui/dist') + ',target=/usr/share/nginx/html,readonly',
         manifest['imageIds']['vahan-review/web:1.0.0']])
    created.append(('container', patched_name))
    patched = json.loads(run(['docker', 'run', '--rm', '--pull=never', '--init', '--shm-size=1g', '--network', network,
               '--security-opt=seccomp=' + str(SOURCE / 'docker/seccomp_profile.json'), '--entrypoint', 'node',
               manifest['imageIds']['vahan-review/runner:1.0.0'], '-e', js.replace('http://web/', 'http://web-patched/')]))
    assert patched['passwordInputs'] == 1 and not patched['cspViolations'], patched
    write('web-source-fix.json', {'checkedAt': now(), 'status': 'PASS', 'releaseArtifactModified': False,
        'scope': 'Working-tree Vite build mounted over immutable nginx image; this is not the original release web payload',
        'stylesheetSha256': sha(ROOT / 'apps/web-ui/src/styles.css'), 'browser': patched})
    return ['nginx-runtime.json', 'web-source-fix.json']


def fingerprint():
    inventory = json.loads((OUT / 'lock-image.json').read_text())
    assert inventory['status'] == 'PASS'
    versions = json.loads((OUT / 'container-runtime.json').read_text())['result']
    tess = run(['docker', 'run', '--rm', '--pull=never', '--network=none', '--entrypoint', 'tesseract',
                manifest['imageIds']['vahan-review/runner:1.0.0'], '--version']).splitlines()[0]
    bases = {p: re.findall(r'^FROM (\S+)', (SOURCE / p).read_text(), re.M) for p in [
        'apps/api-server/Dockerfile', 'apps/browser-runner/Dockerfile', 'apps/web-ui/Dockerfile']}
    value = {'recordedAt': now(), 'sha': SHA, 'manifestDigest': STATE['manifestDigest'],
       'context': 'Post-D3 probes of unchanged immutable candidate images; not a historical staging observation',
       'imageIds': manifest['imageIds'], 'base_image_digests': bases,
       'python_dependencies': inventory['images']['api']['inventory']['packages'],
       'setuptools': inventory['images']['api']['inventory']['packages'].get('setuptools', '<absent>'),
       'chromium_version': versions['chromium'], 'tesseract_version': tess,
       'custom_ca_sha256': json.loads((OUT / 'config-snapshot.json').read_text())['docker_certs_sha256'],
       'lockHashes': {s: v['lockSha256'] for s,v in inventory['images'].items()},
       'lock_image_diff': [], 'historicalFingerprint': str((PRE / 'fresh-build-fingerprint.json').relative_to(ROOT))}
    write('build-fingerprint.json', value)
    return ['build-fingerprint.json', 'lock-image.json']


try:
    previous = OUT / 'checklist.json'
    if previous.exists():
        ledger = json.loads(previous.read_text())
        write('prior-checklist-' + stamp + '.json', ledger)
        assert ledger[0]['status'] == 'PASS'
    else:
        check('identity/DEF-27/DEF-26', identity)
        if ledger[-1]['status'] != 'PASS':
            raise RuntimeError('Identity gate failed')
        check('snapshot', snapshot)
        check('DEF-32 packaged Chromium sandbox and real OCR', runtime)
    check('isolated fixtures', setup_fixtures)
    if ledger[-1]['status'] == 'PASS':
        if '--web-only' not in sys.argv:
            check('DEF-15 persisted large limit, start and resume', def15)
        check('isolated API fixture', setup_api)
        if ledger[-1]['status'] == 'PASS':
            check('DEF-22 nginx server tokens and login CSP', nginx)
    if not (OUT / 'build-fingerprint.json').exists():
        check('fingerprint/DEF-25', fingerprint)
finally:
    cleanup = []
    for kind, name in reversed(created):
        # Only resources successfully created by this invocation are eligible.
        cmd = ['docker', 'rm', '-f', name] if kind == 'container' else ['docker', 'network', 'rm', name]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        cleanup.append({'kind': kind, 'name': name, 'exitCode': proc.returncode})
    write('cleanup.json', {'recordedAt': now(), 'resources': cleanup})
latest = {x['item']: x for x in ledger}
sys.exit(1 if any(x['status'] != 'PASS' for x in latest.values()) else 0)
