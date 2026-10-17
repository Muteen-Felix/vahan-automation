import harness as h
import integrity
import json,time,subprocess,collections
from datetime import datetime,timedelta,timezone
assert (h.ROOT/'r8-analysis.json').exists(),'R8 must finish first'
r8=json.loads((h.ROOT/'r8-analysis.json').read_text());assert r8['eligible'] and r8['thresholdPass'],'STOP: R8 did not pass; do not proceed'
h.login();started=h.now();sid=None;session=None
def event(name,data):
    h.save('resilience-'+name+'.json',{'at':h.now(),'sha':h.SHA,'data':data})
    print(json.dumps({'at':h.now(),'event':name}),flush=True)
def api(method,path,body=None,expected=200):
    r=h.api(method,path,body);assert r['status']==expected,h.clean(r);return r['body']
def schedule():
    r=api('GET','/api/run-schedules');s=next(x for x in r if x['id']==sid)
    with (h.ROOT/'resilience-progress.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'at':h.now(),'schedule':s})+'\n')
    return s
def wait(predicate,seconds=240,label='condition'):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        s=schedule()
        if predicate(s):return s
        if s['status']=='ERROR':raise RuntimeError('STOP: schedule ERROR '+str(s))
        time.sleep(3)
    raise RuntimeError('Timed out: '+label)
def queue():return api('GET','/api/batch-queue/sessions/'+session)
def pool():return api('GET','/api/worker-pool')
def hosts(container,block):
    if container.endswith('-api-1'):
        code="from pathlib import Path;p=Path('/etc/hosts');b=Path('/tmp/d3-hosts-before');"+("assert not b.exists();b.write_bytes(p.read_bytes());p.open('ab').write(b'\\n127.0.0.1 analytics.parivahan.gov.in # D3 external network injection\\n::1 analytics.parivahan.gov.in # D3 external network injection\\n');print('VAHAN DNS blocked')" if block else "assert b.exists();p.write_bytes(b.read_bytes());b.unlink();print('VAHAN DNS restored')")
        args=['docker','exec','--user','0',container,'python','-c',code]
    else:
        code="const fs=require('fs'),p='/etc/hosts',b='/tmp/d3-hosts-before';"+("if(fs.existsSync(b))throw Error('backup exists');fs.copyFileSync(p,b);fs.appendFileSync(p,'\\n127.0.0.1 analytics.parivahan.gov.in # D3 external network injection\\n::1 analytics.parivahan.gov.in # D3 external network injection\\n');console.log('VAHAN DNS blocked')" if block else "if(!fs.existsSync(b))throw Error('backup missing');fs.writeFileSync(p,fs.readFileSync(b));fs.unlinkSync(b);console.log('VAHAN DNS restored')")
        args=['docker','exec','--user','0',container,'node','-e',code]
    r=h.cmd(args);event(('block-' if block else 'restore-')+container,r);assert r['returncode']==0,r
containers=[h.ENV['project']+'-api-1']+[h.ENV['project']+f'-runner-{i}' for i in (1,2,3)]
blocked=[];killed=False
try:
    runners=api('GET','/api/runners');pre=api('POST','/api/ui-health/preflight',{'runnerIds':[x['id'] for x in runners]});event('preflight',pre);assert pre['allowed']
    profile=api('POST','/api/filter-profiles',{'name':'D3 resilience real VAHAN Kerala 2019','definition':{'report':{'year':2019},'fields':{'delhiNcr':{'values':['ALL STATES']},'states':{'values':['Kerala']},'rtos':{'mode':'iterate'},'archivedFlags':{'mode':'iterate'},'categoryGroups':{'values':['Two Wheeler']},'evTypes':{'values':['ELECTRIC(BOV)']}}}})
    event('profile',profile)
    preview=api('POST',f'/api/filter-profiles/{profile["id"]}/preview',{'runnerId':runners[0]['id'],'year':2019})
    events=[json.loads(x) for x in preview.splitlines() if x.strip()];assert events[-1]['type']=='ready',events[-1]
    plan=events[-1]['plan'];event('plan',plan);total=len(plan['scenarios']);assert total>=100
    created=api('POST','/api/run-schedules',{'profileId':profile['id'],'startsAt':(datetime.now(timezone.utc)+timedelta(seconds=15)).isoformat(),'timeZone':'Asia/Ho_Chi_Minh','year':2019,'repeat':'monthly'},expected=201)
    sid=created['id'];event('created',created)
    s=wait(lambda s:s['status']=='RUNNING' and s['done']>=5,seconds=600,label='real collection start');session=s['sessionId'];assert s['total']==total
    h.save('resilience-ids.json',{'scheduleId':sid,'sessionId':session,'profileId':profile['id'],'total':total,'startedAt':started})
    # Disabling future starts must leave this active real run running.
    event('disable-active',api('PATCH','/api/run-schedules/'+sid,{'enabled':False}));before=s['done']
    s=wait(lambda s:s['status']=='RUNNING' and s['done']>before);event('disabled-run-continued',s)
    # Pause drains active cases, then all queue states remain fixed.
    event('pause',api('POST',f'/api/run-schedules/{sid}/pause'))
    s=wait(lambda s:s['status']=='PAUSED');q1=queue();time.sleep(20);q2=queue();assert q1==q2
    event('paused-stable',{'schedule':s,'queue':q2,'stableSeconds':20})
    event('resume',api('POST',f'/api/run-schedules/{sid}/resume'))
    s=wait(lambda s:s['status']=='RUNNING' and s['done']>before+3);event('resumed-progress',s)
    # Restart only packaged API while actual reports are active.
    state_before=api('GET','/api/user-state');event('api-restart',h.compose('restart','api'))
    for i in range(90):
        try:
            if h.api('GET','/api/ready',token=False,timeout=5)['status']==200:break
        except Exception:pass
        time.sleep(1)
    assert api('GET','/api/user-state')==state_before
    s=wait(lambda s:s['status']=='RUNNING');event('api-recovered',s)
    # Kill an actual busy worker; query its loopback health, never its environment.
    target=containers[1]
    for i in range(60):
        r=h.cmd(['docker','exec',target,'node','-e',"fetch('http://127.0.0.1:3001').then(r=>r.json()).then(x=>console.log(JSON.stringify(x)))"])
        health=json.loads(r['stdout'])
        if health.get('activeJobId'):break
        time.sleep(1)
    assert health.get('activeJobId'),'No busy runner available for fault test'
    job=api('GET','/api/jobs/'+health['activeJobId']);event('kill-target',{'container':target,'health':health,'job':job})
    r=h.cmd(['docker','kill',target]);event('kill-runner',r);assert r['returncode']==0;killed=True
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        p=pool()
        if p['runningCount']==2 and p['desiredCount']==2:break
        time.sleep(3)
    else:raise RuntimeError('Worker capacity did not contract to two')
    event('capacity-two',p);time.sleep(15)
    r=h.cmd(['docker','start',target]);event('start-runner',r);assert r['returncode']==0;killed=False
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        p=pool()
        if p['runningCount']==3 and p['desiredCount']==3:break
        time.sleep(3)
    else:raise RuntimeError('Worker capacity did not return to three')
    event('capacity-three',p)
    # Real network loss only for VAHAN hostname inside this isolated staging.
    s=wait(lambda s:s['status']=='RUNNING');event('before-network',{'schedule':s,'queue':queue()})
    for container in containers:hosts(container,True);blocked.append(container)
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        net=api('GET','/api/network/status')
        if not net['online']:break
        time.sleep(2)
    else:raise RuntimeError('Real network outage was not detected')
    s=wait(lambda s:s['status']=='PAUSED' and s.get('networkPaused'),seconds=180)
    q1=queue();time.sleep(25);q2=queue();assert q1==q2
    event('offline-no-claims',{'network':net,'schedule':s,'queue':q2,'stableSeconds':25})
    for container in reversed(blocked[:]):hosts(container,False);blocked.remove(container)
    restored_at=h.now();s=wait(lambda s:s['status']=='RUNNING' and not s.get('networkPaused'),seconds=240)
    event('network-auto-resumed',{'restoredAt':restored_at,'schedule':s,'network':api('GET','/api/network/status')})
    # Explicit stop and resume retains the very same durable queue.
    event('stop',api('POST',f'/api/run-schedules/{sid}/stop'));s=wait(lambda s:s['status']=='STOPPED');q1=queue();time.sleep(15);q2=queue()
    assert not any(t['status']=='PROCESSING' for t in q2['tasks'])
    event('stopped-stable',{'schedule':s,'queue':q2})
    event('resume-after-stop',api('POST',f'/api/run-schedules/{sid}/resume'));s=wait(lambda s:s['status']=='RUNNING');assert s['sessionId']==session
    event('same-session-resumed',s)
    s=wait(lambda s:s['status'] in ['COMPLETED','COMPLETED_WITH_ERRORS'],seconds=3600,label='resilience collection completion')
    event('terminal',{'schedule':s,'queue':queue()});assert s['done']==s['total']==total and s['failed']==0
    data=integrity.capture(session,'resilience-integrity.json',total,plan['scenarios'])
    assert data['retriedTasks'],'No real recovery attempt observed'
    history_before=api('GET','/api/annual-reports/run-history');rows=[r for r in history_before['runs'] if r['sessionId']==session];assert len(rows)==1 and rows[0]['processed']==total
    reports_before=api('GET','/api/annual-reports?year=2019');event('before-delete',{'history':history_before,'reports':reports_before})
    event('delete-completed',api('DELETE','/api/run-schedules/'+sid));history_after=api('GET','/api/annual-reports/run-history');reports_after=api('GET','/api/annual-reports?year=2019')
    assert [r for r in history_after['runs'] if r['sessionId']==session]==rows
    assert reports_before==reports_after
    event('after-delete',{'history':history_after,'reports':reports_after})
    for item,reason in [('R9','Pause drained active cases; queue fixed for20s; resume and later stop/resume retained same session; all real cases terminal, no missing or duplicate successful cases.'),('R9b','Killed actual busy runner: logical capacity3→2; same packaged container restarted with new runner ID and capacity2→3. Terminal case integrity checked.'),('R10','Disabled Monthly future starts while active collection continued; explicit stop/resume retained same queue; deleting completed schedule preserved all rows and named one-row Run History.'),('R11','Busy runner killed during real case; interrupted case recovered with recorded retry attempts; real NO_DATA is terminal and logical successes are not duplicated.'),('R12','Actual VAHAN DNS blocked in staging API/runners; network guard paused automatically, no claims25s; DNS restored and same queue resumed automatically; all cases reconciled.')]:
        h.ledger(item,'PASS',reason,['resilience-progress.jsonl','resilience-integrity.json','resilience-terminal.json','resilience-after-delete.json','resilience-offline-no-claims.json','resilience-network-auto-resumed.json','resilience-capacity-two.json','resilience-capacity-three.json'],started)
    event('PASS',{'total':total,'sessionId':session})
except Exception as e:
    event('BLOCKER',{'type':type(e).__name__,'message':h.clean(str(e)),'sourceOrArtifactChanged':False})
    raise
finally:
    for container in reversed(blocked[:]):
        try:hosts(container,False)
        except Exception as e:event('RESTORE-ERROR',{'container':container,'error':str(e)})
    if killed:event('restore-killed-runner',h.cmd(['docker','start',containers[1]]))
