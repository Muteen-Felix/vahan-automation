#!/usr/bin/env python3
"""Install an offline review package into a disposable Compose project and record real checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import time
import urllib.parse
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from test_container_security import free_port, request, require, header_value


def d3_status(d3: dict) -> str:
    """NOT_RUN unless the operator asked for the live VAHAN checks; never PASS without a recorded PASS."""
    if not d3['requested']:
        return 'NOT_RUN'
    parts = [d3['livePreflight']['status']]
    if d3['liveCaseRequested']:
        parts.append(d3['liveSingleCase']['status'])
    return 'PASS' if all(part == 'PASS' for part in parts) else 'FAIL'


def classify_outcome(checks: list[dict], error: str | None, d3: dict) -> tuple[str, int]:
    """Package checks and D3 live VAHAN checks are separate. Exit: 0 package PASS (D3 NOT_RUN or PASS),
    1 package FAIL, 2 package PASS but the requested D3 live check did not pass."""
    package_failed = bool(error) or any(
        entry.get('passed') is False or entry.get('exitCode', 0) != 0 for entry in checks)
    if package_failed:
        return 'PACKAGE_FAIL', 1
    status = d3_status(d3)
    if status == 'NOT_RUN':
        return 'PACKAGE_PASS_D3_NOT_RUN', 0
    if status == 'PASS':
        return 'PACKAGE_PASS_D3_PASS', 0
    return 'PACKAGE_PASS_D3_FAIL', 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-dir', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--vahan-preflight', action='store_true', help='Also run the D3 UI Health preflight against the real VAHAN site. Off by default; without it the result is recorded as NOT_RUN. Its result is reported separately from the package checks (exit status 2 if it fails).')
    parser.add_argument('--live-case', action='store_true', help='Requires --vahan-preflight. After the live preflight passes, attempt one real VAHAN case with native State/RTO options (at most 180 seconds).')
    args = parser.parse_args()
    if args.live_case and not args.vahan_preflight:
        parser.error('--live-case requires --vahan-preflight.')
    package = Path(args.package_dir).resolve()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifests = list(package.glob('*-manifest.json'))
    require(len(manifests) == 1, 'Supply a directory containing exactly one package manifest.')
    manifest = json.loads(manifests[0].read_text(encoding='utf-8'))
    require(bool(manifest['imageIds']), 'Offline installation requires a --with-images package.')
    for name, expected in manifest['files'].items():
        require(Path(name).name == name, 'Invalid manifest filename.')
        with (package / name).open('rb') as source:
            require(hashlib.file_digest(source, 'sha256').hexdigest() == expected, f'Checksum mismatch: {name}')
    project = f'vahan-review-{secrets.token_hex(6)}'
    evidence = {'sourceCommit':manifest['sourceCommit'], 'packageSha256':manifest['files'],
                'project':project, 'startedAt':datetime.now(timezone.utc).isoformat(), 'checks':[],
                'driverScriptSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'd3':{'requested':args.vahan_preflight,'liveCaseRequested':args.live_case,
                      'livePreflight':{'status':'NOT_RUN','reason':'Not requested; D3 is a separate check (--vahan-preflight).'},
                      'liveSingleCase':{'status':'NOT_RUN','reason':'Not requested (--live-case).'}},
                'limits':['Synthetic data/fixtures are explicitly labelled; external VAHAN collection is a separate check.',
                          'The D3 live VAHAN preflight is reported under "d3", never in "checks"; NOT_RUN is not a pass.']}
    with tempfile.TemporaryDirectory(prefix='vahan-review-install-') as temporary:
        root = Path(temporary)
        source_zip = next(package.glob('*-source.zip'))
        with zipfile.ZipFile(source_zip) as archive:
            for member in archive.infolist():
                require((root / member.filename).resolve().is_relative_to(root.resolve()), 'Unsafe archive member.')
            archive.extractall(root)
        # This is a fresh directory with no repository/user secrets.
        subprocess.run([os.sys.executable, 'scripts/setup-docker.py'], cwd=root, check=True,
                       stdout=subprocess.DEVNULL)
        env_path = root / '.docker.env'
        values = dict(line.split('=',1) for line in env_path.read_text().splitlines() if '=' in line)
        api_port, web_port = free_port(), free_port()
        while api_port == web_port:
            web_port = free_port()
        values.update(API_PORT=str(api_port), WEB_PORT=str(web_port),
            VAHAN_IMAGE_NAMESPACE=manifest['imageNamespace'], VAHAN_IMAGE_TAG=manifest['imageTag'],
            VAHAN_API_CORS_ORIGINS=f'http://127.0.0.1:{web_port}',
            VAHAN_API_SOCKETIO_CORS_ORIGINS=f'http://127.0.0.1:{web_port}')
        env_path.write_text(''.join(f'{k}={v}\n' for k,v in values.items()), encoding='utf-8')
        secret_values = [v for k,v in values.items() if any(s in k for s in ('PASSWORD','SECRET','TOKEN','STATE_KEY'))]
        env = {**os.environ, 'COMPOSE_PROJECT_NAME':project}
        compose = ['docker','compose','--env-file','.docker.env','-p',project]
        restore_compose = ['docker','compose','--env-file','.docker.env','-p',project+'-restore']

        def run(command, label, *, timeout=600, optional=False):
            started = time.monotonic()
            result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=timeout)
            log = result.stdout + '\n' + result.stderr
            command_text = ' '.join(command)
            for secret in secret_values:
                log = log.replace(secret,'[redacted]')
                command_text = command_text.replace(secret,'[redacted]')
            (output / f'{label}.log').write_text(log, encoding='utf-8')
            entry = {'name':label,'command':command_text,'exitCode':result.returncode,
                     'seconds':round(time.monotonic()-started,2),'log':f'{label}.log'}
            evidence['checks'].append(entry)
            print(f'{label}: {"PASS" if result.returncode == 0 else "FAIL"} ({entry["seconds"]} s)', flush=True)
            if result.returncode and not optional:
                raise RuntimeError(f'{label} failed; inspect its redacted log.')
            return result

        def check(name, operation):
            started = time.monotonic()
            try:
                detail = operation()
                entry = {'name':name,'passed':True,'details':detail,'seconds':round(time.monotonic()-started,2)}
            except Exception as error:
                entry = {'name':name,'passed':False,'error':str(error)}
                raise
            finally:
                evidence['checks'].append(entry)
                print(f'{name}: {"PASS" if entry["passed"] else "FAIL"}',flush=True)
            return detail

        api = f'http://127.0.0.1:{web_port}'
        evidence.update(webUrl=api, directApiUrl=f'http://127.0.0.1:{api_port}')
        admin_token = None

        def call(path, method='GET', payload=None, token=None, expected=200):
            headers = {'Content-Type':'application/json'}
            if token:
                headers['Authorization'] = f'Bearer {token}'
            status, response_headers, body = request(api + path, method=method, headers=headers,
                body=json.dumps(payload).encode() if payload is not None else None)
            require(status == expected, f'{method} {path}: expected {expected}, got {status}; {body[:350]!r}')
            return json.loads(body) if body and 'json' in response_headers.get('Content-Type','') else body

        try:
            run(['docker','image','load','-i',str(next(package.glob('*-images.tar')))],'image-load',timeout=900)
            for ref, expected in manifest['imageIds'].items():
                actual = subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',ref],text=True).strip()
                require(actual == expected, f'Loaded image differs from manifest: {ref}')
            run([os.sys.executable,'scripts/run-docker.py','--no-build','--workers','1'],
                'fresh-install-launcher',timeout=360)
            check('external-readiness',lambda: call('/api/ready'))
            def production_docs():
                statuses = {p:request(f'http://127.0.0.1:{api_port}'+p)[0] for p in ('/docs','/redoc','/openapi.json')}
                require(all(status==404 for status in statuses.values()), 'Direct production API docs must be absent.')
                return statuses
            check('production-docs-disabled',production_docs)
            check('retired-routes-404',lambda: [call(p,method=m,expected=404) for p,m in (
                ('/api/ui-health/schedule','GET'),('/api/ui-health/run-now','POST'))])
            auth = call('/api/auth/login','POST',{'username':values['VAHAN_UI_AUTH_USERNAME'],
                'password':values['VAHAN_UI_AUTH_PASSWORD']})
            admin_token = auth['accessToken']; secret_values.append(admin_token)
            check('administrator-login',lambda: call('/api/auth/me',token=admin_token)['role'])
            empty = check('default-report-data-empty',lambda:call('/api/annual-reports',token=admin_token))
            require(empty['summary']['rows'] == 0 and empty['datasets'] == [], 'Fresh install includes unexpected sample reports.')

            def profiles_schedules():
                definition = {'report':{'year':datetime.now().year}, 'fields':{
                    'delhiNcr':{'values':['ALL STATES']},'states':{'values':['ROUND5 SYNTHETIC STATE']},
                    'rtos':{'values':['ROUND5 SYNTHETIC RTO']},'archivedFlags':{'values':['ACTIVE_COMPLIANT']}}}
                profile = call('/api/filter-profiles','POST',{'name':'ROUND5 SYNTHETIC profile','definition':definition},token=admin_token)
                require(profile['revision'] == 1,'Initial profile revision differs.')
                profile = call('/api/filter-profiles/'+profile['id'],'PUT',{'name':'ROUND5 SYNTHETIC profile revised',
                    'definition':definition,'revision':1},token=admin_token)
                require(profile['revision']==2,'Profile update did not increment revision.')
                schedules = []
                for zone in ('Asia/Ho_Chi_Minh','Asia/Kolkata'):
                    schedule = call('/api/run-schedules','POST',{'profileId':profile['id'],
                        'startsAt':(datetime.now(timezone.utc)+timedelta(days=7)).isoformat(),
                        'timeZone':zone,'year':datetime.now().year,'repeat':'monthly','workerCount':999},
                        token=admin_token,expected=201)
                    require(schedule['timeZone']==zone and 'workerCount' not in schedule,'Legacy worker limit/time zone mismatch.')
                    call('/api/run-schedules/'+schedule['id'],'PATCH',{'enabled':False},token=admin_token)
                    schedules.append(schedule['id'])
                for identifier in schedules:
                    call('/api/run-schedules/'+identifier,'DELETE',token=admin_token)
                call('/api/filter-profiles/'+profile['id']+'?revision=2','DELETE',token=admin_token)
                return {'profileRevisions':[1,2], 'zones':['Asia/Ho_Chi_Minh','Asia/Kolkata'],
                        'legacyWorkerCount':999,'legacySettingIgnored':True,'futureSchedulesDeleted':True}
            check('profile-crud-and-schedule-time-zones',profiles_schedules)
            member_password = secrets.token_urlsafe(24);secret_values.append(member_password)
            call('/api/users','POST',{'username':'round5-member','password':member_password,'role':'user'},
                 token=admin_token,expected=201)
            member = call('/api/auth/login','POST',{'username':'round5-member','password':member_password})['accessToken']
            secret_values.append(member)
            def permissions():
                for path in ('/api/annual-reports/run-history','/api/run-schedules','/api/users','/api/filter-profiles'):
                    call(path,token=member,expected=403)
                call('/api/annual-reports',token=member)
                call('/api/annual-reports/run-history',token=admin_token)
                call('/api/users/round5-member','PATCH',{'role':'admin'},token=admin_token)
                call('/api/users/round5-member','PATCH',{'role':'user'},token=admin_token)
                return 'Member reports allowed; history/schedules/users/profiles forbidden; admin role changes persisted.'
            check('member-access-and-admin-account-management',permissions)
            for zone in ('Asia/Ho_Chi_Minh','Asia/Kolkata'):
                call('/api/run-schedules/time-zone','POST',{'timeZone':zone},token=admin_token)
            call('/api/user-state/round5Probe','PUT',{'value':{'label':'ROUND5 SYNTHETIC','persisted':True}},token=admin_token)
            run([*compose,'restart','api'],'api-restart',timeout=90)
            for _ in range(90):
                try:
                    call('/api/ready');break
                except Exception: time.sleep(1)
            check('session-and-state-survive-api-restart',lambda: call('/api/user-state',token=admin_token)['round5Probe'])

            # Exercise the real built import/export implementation with labelled data, not an external report claim.
            seed = """import asyncio
from datetime import datetime, timezone
from app.db import engine
from app.repositories.annual_reports import import_rows
async def main():
 rows=[{'sheet':'Sheet1','row_number':0,'cells':['Maker','2026-Jan']}]
 rows += [{'sheet':'Sheet1','row_number':i+1,'cells':['ROUND5 SYNTHETIC MAKER %04d'%i,i]} for i in range(1000)]
 async with engine.begin() as c:
  await import_rows(c,source_key='round5-synthetic-1000',name='ROUND5 SYNTHETIC FIXTURE - NOT VAHAN DATA',
    rows=rows,owner='admin',observed_at=datetime.now(timezone.utc),filters={'states':['ROUND5 SYNTHETIC STATE'],'rtos':['ROUND5 SYNTHETIC RTO - ZZ01'],
    'fromYear':'2026','toYear':'2026','categoryGroups':['Two Wheeler'],'fuels':['ELECTRIC(BOV)']})
 await engine.dispose()
 print('Imported 1000 explicitly synthetic makers through the built import_rows implementation.')
asyncio.run(main())"""
            run([*compose,'exec','-T','api','python','-c',seed],'synthetic-import-1000')
            def exports():
                table = call('/api/annual-reports?year=2026',token=admin_token)
                require(len(table['rows'])==100 and table['summary']['rows']==1000,'Pagination/full count mismatch.')
                dataset = urllib.parse.quote(table['datasetId'])
                call(f'/api/annual-reports/export?year=2026&dataset={dataset}',token=admin_token,expected=409)
                for label, suffix in [('unfiltered','&confirmAll=true'),('state','&state=ROUND5'),
                                      ('rto','&rto=ZZ01'),('combined','&state=ROUND5&rto=ZZ01')]:
                    status, headers, body = request(api+f'/api/annual-reports/export?year=2026&dataset={dataset}{suffix}',
                        headers={'Authorization':f'Bearer {admin_token}'})
                    count = header_value(headers, 'X-Report-Row-Count')
                    require(status==200 and count=='1000', f'{label} export: status={status}, row count={count!r}.')
                    artifact = output / f'export-{label}-SYNTHETIC.xlsx';artifact.write_bytes(body)
                    with zipfile.ZipFile(artifact) as workbook:
                        from xml.etree import ElementTree as ET
                        sheet = ET.fromstring(workbook.read('xl/worksheets/sheet1.xml'))
                        rows = sheet.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheetData/{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row')
                        require(len(rows)==1003, f'{label} workbook expected 3 header rows + 1000 data rows, got {len(rows)}.')
                return {'displayed':100,'total':1000,'workbookDataRows':1000,'cases':['unfiltered-confirmed','State','RTO','State+RTO']}
            check('actual-excel-all-1000-matching-rows',exports)
            run([os.sys.executable,'scripts/backup-docker.py'],'backup-custom-dump-and-manifest')
            backup = max((root / 'backups').iterdir(),key=lambda path:path.name)
            backup_manifest = json.loads((backup/'manifest.json').read_text())
            for filename, expected in backup_manifest['sha256'].items():
                with (backup/filename).open('rb') as source:
                    require(hashlib.file_digest(source,'sha256').hexdigest()==expected,'Backup checksum mismatch.')
            try:
                run([*restore_compose,'up','-d','--no-build','--wait','postgres'],'restore-fresh-postgres')
                run([*restore_compose,'cp',str(backup/'database.dump'),'postgres:/tmp/restore.dump'],'restore-copy-binary-dump')
                run([*restore_compose,'exec','-T','postgres','pg_restore','-U','vahan','-d','vahan',
                    '--clean','--if-exists','--no-owner','--no-acl','--exit-on-error','/tmp/restore.dump'],'restore-sql-dump')
                run([*restore_compose,'run','--rm','--no-deps','migrate'],'restore-provision-runtime-role')
                restored_probe = """import asyncio
from sqlalchemy import text
from app.db import engine
from app.main import fastapi_app
async def main():
 async with fastapi_app.router.lifespan_context(fastapi_app):
  async with engine.connect() as c:
   assert await c.scalar(text('SELECT current_user')) == 'vahan_app'
   assert await c.scalar(text('SELECT count(*) FROM main_reports')) == 1000
   assert await c.scalar(text("SELECT value->>'persisted' FROM user_state WHERE key='round5Probe'")) == 'true'
   assert await c.scalar(text("SELECT count(*) FROM users WHERE username='round5-member'")) == 1
   assert not await c.scalar(text("SELECT has_schema_privilege(current_user,'public','CREATE')"))
   print('Restored 1000 synthetic reports, member account and persisted state; API lifespan works with DML-only role.')
asyncio.run(main())"""
                run([*restore_compose,'run','--rm','--no-deps','--entrypoint','python','api','-c',restored_probe],
                    'restored-api-lifespan-and-data',timeout=90)
            finally:
                run([*restore_compose,'down','--volumes','--remove-orphans','--timeout','15'],
                    'restore-disposable-project-cleanup',optional=True)
            run([*compose,'run','--rm','--no-deps','-e','VAHAN_RUNTIME_LIVE_PROBE=1','--entrypoint','node',
                'runner','test-container-runtime.mjs'],'chromium-sandbox-and-real-tesseract',timeout=120)
            for test in ('test-image-pipe.mjs','test-filter-fill.mjs','test-options.mjs','test-profile-options.mjs',
                         'test-ui-health-contract.mjs','test-health-trigger.mjs','test-health-navigation.mjs',
                         'test-navigation.mjs','test-page-recovery.mjs','test-results.mjs','test-job-lifecycle.mjs',
                         'test-main-report-save.mjs','test-ocr-start.mjs'):
                run([*compose,'exec','-T','runner','node',test],test.removesuffix('.mjs'),timeout=300)
            # Run host Playwright test scripts against the package's Nginx-built assets.
            # API/Socket.IO fixtures within these scripts remain simulated and are labelled as such.
            web_root = Path(__file__).resolve().parents[1] / 'apps' / 'web-ui'
            names = ['test-batch-timing','test-schedule-timing','test-time-zones','test-session-ui','test-annual-reports',
                'test-filter-profiles-ui','test-health-page-ui','test-navigation-ui','test-run-schedules-ui',
                'test-update-history-ui','test-account-settings-ui','test-network-ui','test-permissions-ui']
            aliases = {'WORKER_UI_URL':'#filters','ANNUAL_UI_URL':'#reports','HISTORY_UI_URL':'#reports',
                'HEALTH_UI_URL':'#settings-ui-health','SCHEDULE_UI_URL':'#settings','NAV_UI_URL':'',
                'ACCOUNT_UI_URL':'','NETWORK_UI_URL':'','PERMISSIONS_UI_URL':''}
            env.update({k:api+'/'+v for k,v in aliases.items()})
            env['UI_TEST_ARTIFACT_DIR'] = str(output / 'ui-screenshots')
            env.update(INSTALLED_UI_URL=api, REVIEW_ADMIN_USERNAME=values['VAHAN_UI_AUTH_USERNAME'],
                REVIEW_ADMIN_PASSWORD=values['VAHAN_UI_AUTH_PASSWORD'], REVIEW_MEMBER_PASSWORD=member_password)
            run(['node',str(web_root/'scripts'/'test-installed-dashboard.mjs')], 'real-installed-dashboard',timeout=180)
            for name in names:
                run(['node',str(web_root/'scripts'/f'{name}.mjs')],'built-ui-fixture-'+name,timeout=300)
            run([*compose,'ps','--format','json'],'final-container-status')
            runner = next(r for r in call('/api/runners',token=admin_token) if r['status']=='ONLINE')
            # D3: the real-VAHAN preflight is opt-in and is recorded under evidence['d3'], not in 'checks'.
            preflight_status = None
            if args.vahan_preflight:
                preflight_request = urllib.request.Request(api+'/api/ui-health/preflight',method='POST',
                    data=json.dumps({'runnerIds':[runner['id']]}).encode(),
                    headers={'Content-Type':'application/json','Authorization':f'Bearer {admin_token}'})
                try:
                    with urllib.request.urlopen(preflight_request,timeout=130) as response:
                        preflight_status, preflight_body = response.status,response.read()
                except urllib.error.HTTPError as response:
                    preflight_status, preflight_body = response.code,response.read()
                preflight = {'httpStatus':preflight_status,'body':json.loads(preflight_body)}
                (output/'d3-live-preflight.json').write_text(json.dumps(preflight,indent=2),encoding='utf-8')
                evidence['d3']['livePreflight'] = {'status':'PASS' if preflight_status==200 else 'FAIL',
                    'httpStatus':preflight_status,'log':'d3-live-preflight.json',
                    'scope':'Actual VAHAN DOM through installed runner/API; failure stays an open D3 finding.'}
                print(f'live-vahan-preflight (D3): {"PASS" if preflight_status==200 else "FAIL"}',flush=True)
            else:
                print('live-vahan-preflight (D3): NOT_RUN (separate check; pass --vahan-preflight to request it)',flush=True)
            if args.live_case and preflight_status==200:
                live = {'scope':'One actual VAHAN case, using native State/RTO options; no synthetic page or CAPTCHA.',
                    'observations':[]}
                job = None
                try:
                    def live_options(context):
                        req=urllib.request.Request(api+'/api/filter-profiles/options',method='POST',
                            data=json.dumps({'runnerId':runner['id'],'year':datetime.now().year,'context':context}).encode(),
                            headers={'Content-Type':'application/json','Authorization':f'Bearer {admin_token}'})
                        with urllib.request.urlopen(req,timeout=150) as response:
                            return json.load(response)
                    options=live_options({})
                    require(bool(options.get('states')),'Live State options are empty.')
                    state=next((v for v in options['states'] if v.casefold()=='assam'),options['states'][0])
                    options=live_options({'delhiNcr':'ALL STATES','states':[state]})
                    require(bool(options.get('rtos')) and bool(options.get('archivedFlags')),'Live RTO/Active options are empty.')
                    filters={'period':'CALENDAR YEAR','fromYear':str(datetime.now().year),'toYear':str(datetime.now().year),
                        'delhiNcr':'ALL STATES','states':[state],'rtos':[options['rtos'][0]],
                        'archivedFlags':[options['archivedFlags'][0]],'yAxis':'Maker','xAxis':'Month Wise',
                        'autoApply':True,'autoExport':True}
                    live['filters']=filters
                    job=call('/api/jobs','POST',{'runnerId':runner['id'],'filters':filters,
                        'scenarioName':'ROUND5 LIVE VAHAN SINGLE-CASE VERIFICATION'},token=admin_token,expected=201)
                    deadline=time.monotonic()+180
                    while True:
                        job=call('/api/jobs/'+job['id'],token=admin_token)
                        observation={key:job.get(key) for key in ('id','sessionId','caseId','status','error','updatedAt',
                            'successfulApplyCount','reportRowCount','mainReportSavedAt','mainReportSummary')}
                        if not live['observations'] or observation!=live['observations'][-1]:
                            live['observations'].append(observation)
                        if job['status'] in ('COMPLETED','NO_DATA','FAILED','CANCELLED'):break
                        if time.monotonic()>deadline:
                            call('/api/jobs/'+job['id']+'/cancel','POST',token=admin_token)
                            live['error']='Timed out at 180 seconds; the test cancelled only its own job.'
                            break
                        time.sleep(2)
                    live['passed']=job['status'] in ('COMPLETED','NO_DATA')
                    live['workbookImported']=bool(job.get('mainReportSavedAt'))
                except Exception as error:
                    # Do not retain request headers, CAPTCHA images or OCR strings.
                    live.update(passed=False,error=str(error).split('\n')[0])
                    if job and job.get('status') not in ('COMPLETED','NO_DATA','FAILED','CANCELLED'):
                        call('/api/jobs/'+job['id']+'/cancel','POST',token=admin_token)
                evidence['d3']['liveSingleCase'] = {'status':'PASS' if live['passed'] else 'FAIL',
                    'workbookImported':live.get('workbookImported',False),'log':'d3-live-single-case.json'}
                (output/'d3-live-single-case.json').write_text(json.dumps(live,indent=2),encoding='utf-8')
                print(f'live-vahan-single-case (D3): {"PASS" if live["passed"] else "FAIL"}',flush=True)
            elif args.live_case:
                evidence['d3']['liveSingleCase'] = {'status':'NOT_RUN','reason':'The D3 live preflight did not pass.'}
            # Reproduce an existing product behavior without changing product code.
            # Deliberately incompatible evidence is synthetic and lives only in this disposable DB.
            payload = {'runnerId':runner['id'],'pageUrl':'https://round5-synthetic.invalid/',
                'healthCheck':{'observedControls':[], 'status':'CHECK_ERROR',
                    'error':'ROUND5 SYNTHETIC disconnect diagnostic','checkId':str(secrets.token_hex(16))}}
            status, _, body = request(api+'/api/ui-health/logs',method='POST',body=json.dumps(payload).encode(),
                headers={'Content-Type':'application/json','X-VAHAN-RUNNER-TOKEN':values['VAHAN_API_RUNNER_TOKEN'],
                    'X-VAHAN-RUNNER-ID':runner['id']})
            require(status==201, 'Could not stage isolated synthetic UI Health diagnostic.')
            before = call('/api/ui-health/status',token=admin_token)
            require(before['blocked'] is True,'Synthetic incompatible evidence must block the online runner.')
            run([*compose,'stop','runner'],'runner-disconnect-diagnostic')
            disconnected_deadline=time.monotonic()+45
            while any(r['id']==runner['id'] for r in call('/api/runners',token=admin_token)):
                require(time.monotonic()<disconnected_deadline,'Runner did not leave SQL connected pool after disconnect grace.')
                time.sleep(1)
            after = call('/api/ui-health/status',token=admin_token)
            finding = {'name':'ui-health-blocked-after-disconnect','passed':after['blocked'] is True,
                'beforeBlocked':before['blocked'],'afterBlocked':after['blocked'],
                'storedRunnerDiagnosticRetained':runner['id'] in after.get('runnerErrors',{}),
                'scope':'Controlled incompatible synthetic DOM evidence; actual HTTP API and actual runner disconnect.',
                'source':'apps/api-server/app/repositories/ui_contract.py:current',
                'productChanged':False}
            evidence['checks'].append(finding)
            (output/'ui-health-disconnect-finding.json').write_text(json.dumps(finding,indent=2),encoding='utf-8')
            print(f'ui-health-blocked-after-disconnect: {"PASS" if finding["passed"] else "OPEN PRODUCT DEFECT"}',flush=True)
            run([*compose,'logs','--no-color','--tail','100','api','runner'],'runtime-logs')
            check('administrator-logout',lambda: call('/api/auth/logout','POST',token=admin_token))
            call('/api/auth/me',token=admin_token,expected=401)
        except Exception as error:
            evidence['error'] = str(error)
            run([*compose,'logs','--no-color','--tail','100'],'failure-runtime-logs',optional=True)
            raise
        finally:
            run([*compose,'down','--volumes','--remove-orphans','--timeout','15'],'disposable-project-cleanup',timeout=120,optional=True)
            evidence['finishedAt'] = datetime.now(timezone.utc).isoformat()
            evidence['outcome'], evidence['exitStatus'] = classify_outcome(
                evidence['checks'], evidence.get('error'), evidence['d3'])
            evidence['d3Status'] = d3_status(evidence['d3'])
            (output / 'results.json').write_text(json.dumps(evidence,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(f"package outcome: {evidence['outcome']}; D3 live VAHAN: {evidence['d3Status']}; exit {evidence['exitStatus']}",flush=True)
    if evidence['exitStatus']:
        raise SystemExit(evidence['exitStatus'])


if __name__ == '__main__':
    main()
