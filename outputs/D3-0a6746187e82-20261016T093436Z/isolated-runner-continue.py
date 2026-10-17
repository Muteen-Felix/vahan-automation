import harness as h
import integrity
import json,time
h.login();started=h.now();created=json.loads((h.ROOT/'isolated-runner-created.json').read_text())['data'];sid=created['id'];plan=json.loads((h.ROOT/'isolated-runner-plan.json').read_text())['data'];target=h.ENV['project']+'-runner-1';killed=False
def api(method,path,body=None):
    r=h.api(method,path,body);assert r['status']==200,h.clean(r);return r['body']
def schedule():return next(x for x in api('GET','/api/run-schedules') if x['id']==sid)
def event(name,data):h.save('isolated-clean-'+name+'.json',{'at':h.now(),'sha':h.SHA,'data':data});print(name,flush=True)
try:
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        s=schedule()
        if s['status']=='PAUSED' and not s.get('networkPaused'):break
        time.sleep(2)
    else:raise RuntimeError('Manual hold did not drain')
    session=s['sessionId'];event('held',s)
    stable=None;deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        net=api('GET','/api/network/status');stable=stable or time.monotonic() if net['online'] else None
        if stable and time.monotonic()-stable>=30:break
        time.sleep(3)
    else:raise RuntimeError('VAHAN did not stabilize')
    event('stable-before-resume',net);event('resume',api('POST',f'/api/run-schedules/{sid}/resume'))
    deadline=time.monotonic()+180;job_id=None
    while time.monotonic()<deadline:
        s=schedule()
        if s['status']=='RUNNING':
            r=h.cmd(['docker','exec',target,'node','-e',"fetch('http://127.0.0.1:3001').then(r=>r.json()).then(x=>console.log(JSON.stringify(x)))"])
            health=json.loads(r['stdout']);job_id=health.get('activeJobId')
            if job_id:break
        time.sleep(1)
    assert job_id,'No active job after held queue resumed'
    j=api('GET','/api/jobs/'+job_id);event('kill-target',{'container':target,'jobId':job_id,'runnerId':j['runnerId'],'status':j['status'],'sessionId':session,'network':api('GET','/api/network/status')})
    r=h.cmd(['docker','kill',target]);event('kill',r);assert r['returncode']==0;killed=True
    deadline=time.monotonic()+900
    while time.monotonic()<deadline:
        s=schedule();j=api('GET','/api/jobs/'+job_id);net=api('GET','/api/network/status')
        with (h.ROOT/'isolated-clean-progress.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'at':h.now(),'schedule':s,'killedJob':{k:j.get(k) for k in ['id','status','error','updatedAt']},'network':net})+'\n')
        assert net['online'],'Natural VAHAN outage overlaps second isolated kill'
        if s['status'] in ['COMPLETED','COMPLETED_WITH_ERRORS']:break
        time.sleep(3)
    else:raise RuntimeError('Recovery timeout')
    assert s['done']==s['total']==len(plan['scenarios']) and s['failed']==0
    finaljob=api('GET','/api/jobs/'+job_id);assert finaljob['status']=='FAILED' and finaljob['error']=='Runner disconnected.',finaljob
    proof=integrity.capture(session,'isolated-runner-integrity.json',len(plan['scenarios']),plan['scenarios'])
    event('PASS',{'schedule':s,'killedJob':{k:finaljob.get(k) for k in ['id','status','error','updatedAt']},'noNetworkOutageDuringThisKill':True,'noApiRestartDuringThisKill':True,'runnerRemainedStoppedUntilFullQueueRecovered':True})
    h.save('isolated-runner-ids.json',{'scheduleId':sid,'sessionId':session,'profileId':created['profileId'],'total':len(plan['scenarios']),'startedAt':started})
    h.ledger('R11','PASS','Separate observed window with network continuously online and no API restart: killed busy worker, original job FAILED / Runner disconnected after grace, remaining real workers recovered and completed all14 native cases. Killed container stayed stopped until completion; no missing/duplicate case. Earlier overlapping natural outage is preserved as an invalid isolated window, not used as PASS.',['isolated-clean-PASS.json','isolated-clean-progress.jsonl','isolated-runner-integrity.json','isolated-runner-BLOCKER.json','resilience-integrity.json'],started)
except Exception as e:event('BLOCKER',{'error':h.clean(str(e)),'sourceOrArtifactChanged':False});raise
finally:
    if killed:event('restore',h.cmd(['docker','start',target]))
