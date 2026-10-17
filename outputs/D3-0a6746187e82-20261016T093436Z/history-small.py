import harness as h
import json
h.login();started=h.now();out={}
def get(key,method,path,body=None):
    r=h.api(method,path,body);out[key]=r;h.save('small-history-delete-restore.json',out);assert r['status']==200,h.clean(r);return r['body']
sid=json.loads((h.ROOT/'small-run-ids.json').read_text())['scheduleId']
s=next(x for x in get('schedules','GET','/api/run-schedules') if x['id']==sid)
assert s['status']=='COMPLETED' and s['done']==s['total']==2 and s['noData']==2
session=s['lastSessionId'];queue=get('queue','GET',f'/api/batch-queue/sessions/{session}');history=get('runHistory','GET','/api/annual-reports/run-history')
row=[x for x in history['runs'] if x['sessionId']==session];assert len(row)==1
assert row[0]['totalCases']==2 and row[0]['noData']==2 and row[0]['failed']==0
sessions=get('sessionsBefore','GET','/api/jobs/reports/sessions');small=next(x for x in sessions if x['sessionId']==session)
assert small['jobCount']==2 and small['noDataCount']==2
for i,j in enumerate(small['jobs']):
    assert j['status']=='NO_DATA' and j['error'] is None
get('delete','DELETE',f'/api/jobs/reports/sessions/{session}')
assert not any(x['sessionId']==session for x in get('visibleAfterDelete','GET','/api/jobs/reports/sessions'))
assert any(x['sessionId']==session for x in get('trash','GET','/api/jobs/reports/sessions?deleted=true'))
get('restore','POST',f'/api/jobs/reports/sessions/{session}/restore')
restored=next(x for x in get('visibleAfterRestore','GET','/api/jobs/reports/sessions') if x['sessionId']==session)
assert restored==small
historyAfter=get('historyAfter','GET','/api/annual-reports/run-history')
assert [x for x in historyAfter['runs'] if x['sessionId']==session]==row
h.ledger('R4','PASS','Two real VAHAN NO_DATA outcomes retained; soft-delete hides session, trash shows it, restore preserves identical session/jobs and exactly one Run History row. Current report-table design does not require legacy per-job text files.',['small-history-delete-restore.json'],started)
print('R4 PASS; small real run has exactly one history row and two NO_DATA outcomes')
