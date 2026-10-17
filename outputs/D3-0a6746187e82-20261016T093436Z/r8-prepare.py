import harness as h
import json
from datetime import datetime,timedelta,timezone
h.login();began=h.now();runners=h.api('GET','/api/runners')['body']
pre=h.api('POST','/api/ui-health/preflight',{'runnerIds':[r['id'] for r in runners]},timeout=240);h.save('r8-preflight.json',pre);assert pre['status']==200 and pre['body']['allowed'],h.clean(pre)
body={'name':'D3 R8 real VAHAN 2018 three states','definition':{'report':{'year':2018},'fields':{'delhiNcr':{'values':['ALL STATES']},'states':{'values':['Karnataka','Kerala','Tamil Nadu']},'rtos':{'mode':'iterate'},'archivedFlags':{'mode':'iterate'},'categoryGroups':{'values':['Two Wheeler']},'evTypes':{'values':['ELECTRIC(BOV)']}}}}
p=h.api('POST','/api/filter-profiles',body);h.save('r8-profile.json',p);assert p['status']==200,h.clean(p)
pid=p['body']['id'];r=h.api('POST',f'/api/filter-profiles/{pid}/preview',{'runnerId':runners[0]['id'],'year':2018},timeout=900);h.save('r8-preview.json',r);assert r['status']==200
events=[json.loads(x) for x in r['body'].splitlines() if x.strip()];assert events[-1]['type']=='ready',events[-1]
plan=events[-1]['plan'];h.save('r8-plan.json',plan);n=len(plan['scenarios']);assert n>=100,n
keys=[x['caseKey'] for x in plan['scenarios']];assert len(keys)==len(set(keys))
s=h.api('POST','/api/run-schedules',{'profileId':pid,'startsAt':(datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat(),'timeZone':'Asia/Ho_Chi_Minh','year':2018,'repeat':'once'});h.save('r8-schedule-create.json',s);assert s['status']==201,h.clean(s)
h.save('r8-ids.json',{'profileId':pid,'scheduleId':s['body']['id'],'cases':n,'preparedAt':began,'monitorIntervalSeconds':60,'operatorInterventionsAllowed':False,'thresholds':{'50-75medianAbsRelativeError':0.25,'75-100medianAbsRelativeError':0.15},'outages':'Include genuine VAHAN outages in ETA error; record durations'})
print(json.dumps({'r8Scheduled':s['body']['id'],'cases':n,'workers':len(runners)}))
