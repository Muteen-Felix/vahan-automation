import json,os,pathlib,subprocess,sys,tempfile
import prepare as p
import fresh as f
import importlib.util

state=json.loads((p.ROOT/'t45b-environment.json').read_text())
root=pathlib.Path(state['upgradedRoot'])
project=state['project']
env={**os.environ,'COMPOSE_PROJECT_NAME':project}
v=f.values_at(root)
p.REDACTIONS.extend(value for key,value in v.items() if any(t in key for t in ('PASSWORD','TOKEN','SECRET','STATE_KEY')))
c=['docker','compose','--env-file','.docker.env','-p',project]

def query(sql,label,database='vahan'):
    return p.run([*c,'exec','-T','postgres','psql','-U','vahan','-d',database,'-XAt','-v','ON_ERROR_STOP=1','-c',sql],label,cwd=root,env=env)

def expected_failure(args,label,extra_env=None):
    result=subprocess.run(args,cwd=root,env=extra_env or env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
    log=result.stdout+'\n'+result.stderr
    for value in p.REDACTIONS: log=log.replace(value,'[redacted]')
    (p.ROOT/(label+'.log')).write_text(log,encoding='utf-8')
    assert result.returncode!=0,label+' should fail'
    p.save(label+'.json',{'sha':p.SHA,'checkedAt':p.now(),'expectedNonzeroExit':True,'exitCode':result.returncode,'status':'PASS','log':label+'.log'})
    print(label,'PASS (expected rejection)',flush=True)

ids=subprocess.check_output(['docker','ps','-aq','--filter','label=com.docker.compose.project='+project],text=True).split()
containers=json.loads(subprocess.check_output(['docker','inspect',*ids],text=True))
sanitized=[]
for container in containers:
    ref=container['Config']['Image']
    assert container['Image']==f.M['imageIds'][ref]
    sanitized.append({'name':container['Name'],'ref':ref,'id':container['Image'],'state':container['State']['Status'],'health':container['State'].get('Health',{}).get('Status'),'exitCode':container['State']['ExitCode'],'service':container['Config']['Labels']['com.docker.compose.service']})
assert len([x for x in sanitized if x['service']=='runner' and x['state']=='running'])==1
p.save('t45b-installed-image-identity.json',{'sha':p.SHA,'checkedAt':p.now(),'status':'PASS','containers':sanitized,'legacyWorkerSetting':9999,'actualRunnerReplicas':1,'scope':'Startup preserves the explicitly selected one-runner pool. Live scheduling capacity is reserved for D3 R9b.'})

# Missing password must fail at Compose interpolation, before any service or data changes.
missing=root/'.docker.missing-test.env'
missing.write_text(''.join(f'{key}={value}\n' for key,value in v.items() if key!='DB_APP_PASSWORD'))
sys.path.insert(0,str(root/'scripts'))
from secure_permissions import restrict_permissions
restrict_permissions(missing)
expected_failure(['docker','compose','--env-file',str(missing),'-p',project,'config','--quiet'],'t45b-missing-runtime-password')

# Run the short-password case against an independently restored disposable DB, never the upgraded DB.
database='vahan_t45b_short_password_test'
query('CREATE DATABASE '+database,'t45b-short-password-create-db')
backup=pathlib.Path(state['privateBackupDirectory'])/'database.dump'
with backup.open('rb') as source:
    result=subprocess.run([*c,'exec','-T','postgres','pg_restore','-U','vahan','-d',database,'--exit-on-error'],cwd=root,env=env,stdin=source,capture_output=True)
assert result.returncode==0,'short-password fixture restore'
spec=importlib.util.spec_from_file_location('upgrade_driver',p.ROOT/'t45b-upgrade.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
before=json.loads(query(mod.SQL,'t45b-short-password-before',database))
negative_env={**env,'DATABASE_URL':f'postgresql+asyncpg://vahan:{v["POSTGRES_PASSWORD"]}@postgres:5432/{database}','DB_APP_PASSWORD':'short-test-value'}
expected_failure([*c,'run','--rm','--no-deps','--pull','never','-e','DATABASE_URL','-e','DB_APP_PASSWORD','migrate'],'t45b-short-runtime-password',negative_env)
after=json.loads(query(mod.SQL,'t45b-short-password-after',database))
assert before==after
schema=query('select version_num from alembic_version','t45b-short-password-schema',database)
p.save('t45b-negative-credential-safety.json',{'sha':p.SHA,'checkedAt':p.now(),'status':'PASS','missingPassword':'Compose refused before start','shortPassword':'Provisioning rejected; all ten business tables retain exact counts and content in an isolated restored test database','schemaAfterShortPasswordFailure':schema,'migrationOrderingNote':'Schema migrations execute before runtime credential validation; this negative test is isolated from the upgraded stack.','upgradedDatabaseUntouched':True})
query('DROP DATABASE '+database,'t45b-short-password-drop-db')
missing.unlink()
token=f.api(state['baseUrl'],'/api/auth/login','POST',{'username':'admin','password':v['VAHAN_UI_AUTH_PASSWORD']})['accessToken']
schedule_list=f.api(state['baseUrl'],'/api/run-schedules',token=token)
assert len(schedule_list)==2 and all('workerCount' not in x for x in schedule_list)
p.save('t45b-schedule-public-api.json',{'sha':p.SHA,'checkedAt':p.now(),'status':'PASS','schedules':schedule_list,'legacyWorkerCountHidden':True})
result=json.loads((p.ROOT/'t45b-result.json').read_text())
result.update(credentialFailureSafety='PASS',installedImageIdentity='PASS',legacyWorkerStartup='PASS: 9999 saved; one actual runner as selected',finishedAt=p.now())
p.save('t45b-result.json',result)
print('Additional T45b checks PASS',flush=True)
