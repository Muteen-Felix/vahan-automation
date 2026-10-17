import hashlib,json,os,pathlib,shutil,subprocess,sys,tempfile,zipfile
import prepare as p
import fresh as f

state=json.loads((p.ROOT/'t45b-environment.json').read_text())
old=pathlib.Path(state['baselineRoot'])
project=state['project']
env={**os.environ,'COMPOSE_PROJECT_NAME':project}
c=['docker','compose','--env-file','.docker.env','-p',project]
v=f.values_at(old)
p.REDACTIONS.extend(value for k,value in v.items() if any(t in k for t in ('PASSWORD','TOKEN','SECRET','STATE_KEY')))

TABLES=['main_reports','maker_office_index','report_update_history','report_sessions','batch_queue_sessions','batch_queue_tasks','jobs','job_events','stored_files','filter_profiles']
SQL='SELECT json_build_object('+','.join("'%s', (SELECT json_build_object('rows',count(*),'contentMd5',md5(coalesce(string_agg(to_jsonb(t)::text,E'\\n' ORDER BY to_jsonb(t)::text),''))) FROM \"%s\" t)"%(t,t) for t in TABLES)+');'

def query(sql,name,root=old,database='vahan'):
    return p.run([*c,'exec','-T','postgres','psql','-U','vahan','-d',database,'-XAt','-v','ON_ERROR_STOP=1','-c',sql],name,cwd=root,env=env)

def binary_run(args,name,root,stdin=None):
    result=subprocess.run(args,cwd=root,env=env,stdin=stdin,capture_output=True)
    text=(result.stdout+result.stderr).decode('utf-8','replace')
    for secret in p.REDACTIONS: text=text.replace(secret,'[redacted]')
    (p.ROOT/(name+'.log')).write_text(text,encoding='utf-8')
    p.save(name+'.json',{'sha':p.SHA,'recordedAt':p.now(),'exitCode':result.returncode,'command':args,'log':name+'.log'})
    assert result.returncode==0,name
    print(name,'PASS',flush=True)

def main():
    assert query('select version_num from alembic_version','t45b-old-version')=='0012_auth_session_limits'
    ids=json.loads((p.ROOT/'t45b-data-identity.json').read_text(encoding='utf-8'))
    assert ids['baselineSha']==state['baselineSha']
    before=json.loads(query(SQL,'t45b-data-before'))
    assert before['main_reports']['rows']==3 and before['jobs']['rows']==1
    schedules_before=json.loads(query("SELECT json_object_agg(key,value) FROM app_settings WHERE key LIKE 'automatic-report-schedule:%'",'t45b-schedules-before'))
    # The shipped backup tool resolves its root from its own file. Copy the unchanged tool and its permission helper
    # into the old installation, whose historical source predates this backup tool.
    for name in ('backup-docker.py','secure_permissions.py'):
        shutil.copyfile(p.TREE/'scripts'/name,old/'scripts'/name)
    p.run([sys.executable,'scripts/backup-docker.py'],'t45b-private-backup',cwd=old,env=env)
    backup=max((old/'backups').iterdir(),key=lambda path:path.name)
    backup_manifest=json.loads((backup/'manifest.json').read_text())
    assert f.digest(backup/'database.dump')==backup_manifest['sha256']['database.dump']
    p.save('t45b-backup-verification.json',{'sha':p.SHA,'verifiedAt':p.now(),'privateBackupDirectory':str(backup),'dumpSha256':f.digest(backup/'database.dump'),'archiveListingVerified':backup_manifest['archiveListingVerified'],'secretConfigPreserved':True,'secretConfigDigestWithheld':True})
    with (backup/'database.dump').open('rb') as data:
        binary_run([*c,'exec','-T','postgres','pg_restore','--list'],'t45b-backup-list',old,stdin=data)
    query('CREATE DATABASE vahan_t45b_restore_test','t45b-restore-create')
    with (backup/'database.dump').open('rb') as data:
        binary_run([*c,'exec','-T','postgres','pg_restore','-U','vahan','-d','vahan_t45b_restore_test','--exit-on-error'],'t45b-restore',old,stdin=data)
    assert json.loads(query(SQL,'t45b-restored-data',database='vahan_t45b_restore_test'))==before
    assert query('select version_num from alembic_version','t45b-restored-version',database='vahan_t45b_restore_test')=='0012_auth_session_limits'
    upgraded=pathlib.Path(tempfile.mkdtemp(prefix='vahan-t45b-0a67-candidate-'))
    with zipfile.ZipFile(next(f.PACKAGE.glob('*-source.zip'))) as z: z.extractall(upgraded)
    shutil.copyfile(old/'.docker.env',upgraded/'.docker.env')
    original=f.values_at(upgraded)
    assert not any(k.startswith('DB_APP_') for k in original)
    p.run([sys.executable,'scripts/run-docker.py','--check-release'],'t45b-release-guard',cwd=upgraded,env=env)
    # --check-release invokes setup, which is also the documented credential-upgrade step.
    after_setup=f.values_at(upgraded)
    assert all(after_setup.get(k)==value for k,value in original.items())
    assert after_setup.get('DB_APP_USERNAME') and len(after_setup.get('DB_APP_PASSWORD',''))>=24
    p.REDACTIONS.append(after_setup['DB_APP_PASSWORD'])
    p.save('t45b-config-preservation.json',{'sha':p.SHA,'checkedAt':p.now(),'allOriginalKeysPreserved':True,'runtimeRoleCredentialAdded':True,'runtimePasswordMinimumLengthMet':True,'valuesAndSecretHashesWithheld':True})
    p.run([*c,'stop','runner','web','api'],'t45b-old-service-stop',cwd=old,env=env,timeout=150)
    p.run(['docker','image','load','-i',str(next(f.PACKAGE.glob('*-images.tar')))],'t45b-load-final-package',cwd=upgraded,env=env)
    after_setup.update(VAHAN_IMAGE_NAMESPACE=f.M['imageNamespace'],VAHAN_IMAGE_TAG=f.M['imageTag'])
    (upgraded/'.docker.env').write_text(''.join(f'{key}={value}\n' for key,value in after_setup.items()))
    state['upgradedRoot']=str(upgraded);state['privateBackupDirectory']=str(backup)
    p.save('t45b-environment.json',state)
    p.run([sys.executable,'scripts/run-docker.py','--no-build','--workers','1'],'t45b-upgrade-launcher',cwd=upgraded,env=env,timeout=420)
    p.run([*c,'logs','--no-color','migrate'],'t45b-upgrade-migration',cwd=upgraded,env=env)
    assert query('select version_num from alembic_version','t45b-final-version',root=upgraded)=='0016_state_revision_gate_gen'
    after=json.loads(query(SQL,'t45b-data-after',root=upgraded))
    assert before==after,{'before':before,'after':after}
    schedules_after=json.loads(query("SELECT json_object_agg(key,value) FROM app_settings WHERE key LIKE 'automatic-report-schedule:%'",'t45b-schedules-after',root=upgraded))
    expected={k:value for k,value in schedules_before.items() if value['repeat']!='daily'}
    assert schedules_after==expected
    audit=json.loads(query("SELECT value FROM app_settings WHERE key='migration-audit:0015_remove_daily_schedules'",'t45b-daily-removal-audit',root=upgraded))
    daily=next(s for s in ids['schedules'] if s['repeat']=='daily')
    assert audit['count']==1 and audit['removed'][0]['id']==daily['id']
    p.run([*c,'run','--rm','--pull','never','migrate'],'t45b-migration-idempotent',cwd=upgraded,env=env,timeout=150)
    assert json.loads(query(SQL,'t45b-data-after-second-migration',root=upgraded))==after
    assert json.loads(query("SELECT value FROM app_settings WHERE key='migration-audit:0015_remove_daily_schedules'",'t45b-audit-after-second-migration',root=upgraded))==audit
    env['VAHAN_SMOKE_ADMIN_PASSWORD']=v['VAHAN_UI_AUTH_PASSWORD']
    p.run([sys.executable,'scripts/release-smoke.py','--base-url',state['baseUrl'],'--admin-user','admin','--min-runners','1','--compose-project',project,'--require-compose-checks','--output',str(p.ROOT/'t45b-smoke.json')],'t45b-smoke-command',cwd=upgraded,env=env,timeout=240)
    token=f.api(state['baseUrl'],'/api/auth/login','POST',{'username':'admin','password':v['VAHAN_UI_AUTH_PASSWORD']})['accessToken']
    p.REDACTIONS.append(token)
    report=f.api(state['baseUrl'],'/api/annual-reports?year=2025',token=token)
    assert report['summary']['rows']==3
    history=f.api(state['baseUrl'],'/api/annual-reports/run-history',token=token)
    matching=[r for r in history['runs'] if r['sessionId']==ids['sessionId']]
    assert len(matching)==1 and matching[0]['filterName']=='T45B SYNTHETIC UPGRADE PROFILE'
    p.save('t45b-reports-history-api.json',{'sha':p.SHA,'checkedAt':p.now(),'status':'PASS','report':report,'history':history,'scope':'Synthetic persistent upgrade fixture only, not D3 VAHAN data'})
    p.run([sys.executable,'scripts/config-snapshot.py','--project-dir',str(upgraded),'--env-file',str(upgraded/'.docker.env'),'--image-ids','--out',str(p.ROOT/'t45b-config-snapshot.json')],'t45b-config-snapshot-command',cwd=upgraded,env=env)
    p.run([*c,'ps','-a','--format','json'],'t45b-final-containers',cwd=upgraded,env=env)
    p.save('t45b-result.json',{'sha':p.SHA,'baselineSha':state['baselineSha'],'finishedAt':p.now(),'status':'PASS','baselineRevision':'0012_auth_session_limits','finalRevision':'0016_state_revision_gate_gen','allTenBusinessTableCountsAndContentsPreserved':True,'onceMonthlyUnchanged':True,'dailyRemoved':1,'dailyRunHistoryPreserved':True,'idempotency':'PASS','backupRestore':'PASS','runtimeRole':'PASS','scope':'Newly built baseline with labelled synthetic persistent upgrade dataset, not historical test results or real VAHAN evidence','legacyWorkerActivation':'NOT_RUN: no live VAHAN execution before D3','manifestDigest':f.digest(f.MANIFEST)})
    print('T45b core upgrade PASS',flush=True)

if __name__=='__main__':main()
