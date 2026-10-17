import harness as h
import integrity
import json,time
from datetime import datetime,timedelta,timezone
h.login();started=h.now();sid=None;target=h.ENV['project']+'-runner-1';killed=False
def save(name,data):h.save('isolated-runner-'+name+'.json',{'at':h.now(),'sha':h.SHA,'data':data});print(name,flush=True)
def api(method,path,body=None,expected=200):
    r=h.api(method,path,body);assert r['status']==expected,h.clean(r);return r['body']
def schedule():
    return next(x for x in api('GET','/api/run-schedules') if x['id']==sid)
try:
    runners=api('GET','/api/runners');pre=api('POST','/api/ui-health/preflight',{'runnerIds':[r['id'] for r in runners]});assert pre['allowed'];save('preflight',pre)
    p=api('POST','/api/filter-profiles',{'name':'D3 isolated runner recovery 2020','definition':{'report':{'year':2020},'fields':{'delhiNcr':{'values':['ALL STATES']},'states':{'values':['Andaman & Nicobar Island']},'rtos':{'mode':'iterate'},'archivedFlags':{'values':['ACTIVE_COMPLIANT']}}}})
    r=api('POST',f'/api/filter-profiles/{p["id"]}/preview',{'runnerId':runners[0]['id'],'year':2020});events=[json.loads(x) for x in r.splitlines() if x.strip()];assert events[-1]['type']=='ready';plan=events[-1]['plan'];save('plan',plan)
    created=api('POST','/api/run-schedules',{'profileId':p['id'],'startsAt':(datetime.now(timezone.utc)+timedelta(seconds=15)).isoformat(),'timeZone':'Asia/Ho_Chi_Minh','year':2020,'repeat':'once'},expected=201);sid=created['id'];save('created',created)
    deadline=time.monotonic()+600;job_id=None;session=None
    while time.monotonic()<deadline:
        s=schedule()
        if s['status']=='RUNNING':
            r=h.cmd(['docker','exec',target,'node','-e',"fetch('http://127.0.0.1:3001').then(r=>r.json()).then(x=>console.log(JSON.stringify(x)))"])
            health=json.loads(r['stdout']);job_id=health.get('activeJobId')
            if job_id:
                session=s['sessionId'];break
        time.sleep(1)
    assert job_id,'No actual active job for isolated kill'
    job=api('GET','/api/jobs/'+job_id);save('kill-target',{'container':target,'jobId':job_id,'runnerId':job['runnerId'],'sessionId':session,'status':job['status'],'schedule':s})
    result=h.cmd(['docker','kill',target]);save('kill',result);assert result['returncode']==0;killed=True
    save('constraints',{'networkInjection':False,'apiRestart':False,'runnerRestoreOnlyAfterAutomaticCaseRecovery':True})
    deadline=time.monotonic()+900
    while time.monotonic()<deadline:
        s=schedule();j=api('GET','/api/jobs/'+job_id);net=api('GET','/api/network/status')
        with (h.ROOT/'isolated-runner-progress.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'at':h.now(),'schedule':s,'killedJob':{k:j.get(k) for k in ['id','status','error','updatedAt']},'network':net})+'\n')
        assert net['online'],'Unexpected real VAHAN outage overlaps isolated kill; do not claim isolation'
        if s['status'] in ['COMPLETED','COMPLETED_WITH_ERRORS']:break
        time.sleep(3)
    else:raise RuntimeError('Isolated worker recovery did not complete within15min')
    assert s['done']==s['total']==len(plan['scenarios']) and s['failed']==0,s
    finaljob=api('GET','/api/jobs/'+job_id);assert finaljob['status']=='FAILED' and finaljob['error']=='Runner disconnected.',finaljob
    proof=integrity.capture(session,'isolated-runner-integrity.json',len(plan['scenarios']),plan['scenarios']);assert proof['retriedTasks']
    save('PASS',{'schedule':s,'killedJob':{k:finaljob.get(k) for k in ['id','status','error','updatedAt']},'actualCaseRecoveryVerified':True})
    h.save('isolated-runner-ids.json',{'scheduleId':sid,'sessionId':session,'profileId':p['id'],'total':len(plan['scenarios']),'startedAt':started})
    h.ledger('R11','PASS','Isolated busy runner kill with no API restart or network change: server marked original job FAILED / Runner disconnected after grace, remaining real runners retried and completed every native case with no loss/duplicate. Runner stayed stopped until recovery proof. NO_DATA terminal behavior also verified on both larger workloads.',['isolated-runner-PASS.json','isolated-runner-progress.jsonl','isolated-runner-integrity.json','resilience-integrity.json'],started)
except Exception as e:
    save('BLOCKER',{'error':h.clean(str(e)),'sourceOrArtifactChanged':False});raise
finally:
    if killed:save('restore',h.cmd(['docker','start',target]))
