import json,os,pathlib,subprocess,sys
import prepare as p
import fresh as f

state=json.loads((p.ROOT/'fresh-environment.json').read_text(encoding='utf-8'))
root=pathlib.Path(state['root']);project=state['project']
env={**os.environ,'COMPOSE_PROJECT_NAME':project}
c=['docker','compose','--env-file','.docker.env','-p',project]
v=f.values_at(root)
p.REDACTIONS.extend(value for key,value in v.items() if any(t in key for t in ('PASSWORD','TOKEN','SECRET','STATE_KEY')))

def states():
    ids=subprocess.check_output(['docker','ps','-aq','--filter','label=com.docker.compose.project='+project],text=True).split()
    return {item['Config']['Labels']['com.docker.compose.service']:{'id':item['Id'],'image':item['Image'],'state':item['State']['Status']} for item in json.loads(subprocess.check_output(['docker','inspect',*ids],text=True))}

def rejected(label,flags):
    result=subprocess.run([sys.executable,'scripts/run-docker.py',*flags],cwd=root,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240)
    log=result.stdout+'\n'+result.stderr
    for value in p.REDACTIONS:log=log.replace(value,'[redacted]')
    (p.ROOT/(label+'.log')).write_text(log,encoding='utf-8')
    p.save(label+'.json',{'sha':p.SHA,'checkedAt':p.now(),'exitCode':result.returncode,'expectedExitCode':2,'status':'PASS' if result.returncode==2 else 'FAIL','log':label+'.log'})
    assert result.returncode==2
    return log

before=states();assert all(item['state']=='exited' for item in before.values())
rejected('fresh-readonly-when-stopped',['--check-release'])
assert states()==before
p.run([*c,'start','--wait','--wait-timeout','180','postgres'],'fresh-safety-probe-start-db',cwd=root,env=env)
sql="INSERT INTO app_settings(key,value) VALUES ('automatic-report-schedule:release-f-safety-probe','{\"status\":\"PREPARING\"}'::jsonb)"
p.run([*c,'exec','-T','postgres','psql','-U','vahan','-d','vahan','-XAt','-v','ON_ERROR_STOP=1','-c',sql],'fresh-stage-active-schedule-probe',cwd=root,env=env)
try:
    p.run([*c,'stop','postgres'],'fresh-safety-probe-stop-db',cwd=root,env=env)
    log=rejected('fresh-active-work-guard',['--no-build','--workers','1'])
    assert 'activeSchedules=1' in log
    after=states()
    assert after['postgres']['state']=='running' and after['postgres']['id']==before['postgres']['id']
    assert all(after[key]==before[key] for key in ('api','web','runner'))
    p.save('fresh-safety-result.json',{'sha':p.SHA,'checkedAt':p.now(),'status':'PASS','readOnlyCheckDoesNotStartServices':True,'stoppedDatabaseRecoveredBeforeGuard':True,'activeScheduleBlocksApplicationReplacement':True,'applicationContainersUnchanged':True,'source':'Unmodified host scripts extracted from the exact final package','scope':'Labelled temporary release safety probe; not D3 VAHAN evidence'})
finally:
    p.run([*c,'exec','-T','postgres','psql','-U','vahan','-d','vahan','-XAt','-v','ON_ERROR_STOP=1','-c',"DELETE FROM app_settings WHERE key='automatic-report-schedule:release-f-safety-probe'"],'fresh-remove-active-schedule-probe',cwd=root,env=env)
    p.run([*c,'stop'],'fresh-safety-retain-stopped-stack',cwd=root,env=env)
