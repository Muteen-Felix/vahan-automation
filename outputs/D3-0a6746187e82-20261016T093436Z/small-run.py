import harness as h
import json,time
from datetime import datetime,timedelta,timezone
h.login();began=h.now()
runner=h.api('GET','/api/runners')['body'][0]['id']
r=h.api('POST','/api/filter-profiles/options',{'runnerId':runner,'year':2018,'context':{'delhiNcr':'ALL STATES','states':['Andaman & Nicobar Island']}},timeout=180)
h.save('andaman-native-options.json',r);assert r['status']==200,h.clean(r)
rtos=r['body']['rtos'];assert len(rtos)>1,rtos
body={'name':'D3 real VAHAN small 2018','definition':{'report':{'year':2018},'fields':{'delhiNcr':{'values':['ALL STATES']},'states':{'values':['Andaman & Nicobar Island']},'rtos':{'values':rtos[:2]},'archivedFlags':{'values':['ACTIVE_COMPLIANT']}}}}
profile=h.api('POST','/api/filter-profiles',body);h.save('small-profile.json',profile);assert profile['status']==200,h.clean(profile)
pid=profile['body']['id']
preview=h.api('POST',f'/api/filter-profiles/{pid}/preview',{'runnerId':runner,'year':2018},timeout=600)
h.save('small-preview.json',preview);assert preview['status']==200
events=[json.loads(line) for line in preview['body'].splitlines() if line.strip()];assert events[-1]['type']=='ready',events[-1]
plan=events[-1]['plan'];assert len(plan['scenarios'])==2
h.ledger('R3','PASS','Loaded native VAHAN dependent State/RTO options, saved profile and streamed preview: exactly two native cases with unique scenario filters.',['native-options.json','andaman-native-options.json','small-profile.json','small-preview.json'],began)
schedule=h.api('POST','/api/run-schedules',{'profileId':pid,'startsAt':(datetime.now(timezone.utc)+timedelta(seconds=15)).isoformat(),'timeZone':'Asia/Ho_Chi_Minh','year':2018,'repeat':'once'})
h.save('small-schedule-create.json',schedule);assert schedule['status']==201,h.clean(schedule)
sid=schedule['body']['id'];h.save('small-run-ids.json',{'profileId':pid,'scheduleId':sid,'expectedCases':2})
print(json.dumps({'smallRunCreated':sid,'rtos':rtos,'profile':pid,'previewCases':2}))
