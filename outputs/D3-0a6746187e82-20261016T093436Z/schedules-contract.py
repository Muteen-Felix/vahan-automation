import harness as h
import json
from datetime import datetime,timezone,timedelta
h.login();start=h.now();out={}
pid=json.loads((h.ROOT/'small-run-ids.json').read_text())['profileId']
def check(key,method,path,status,body=None):
    r=h.api(method,path,body);out[key]=r;h.save('schedule-contract.json',out);assert r['status']==status,(key,h.clean(r));return r['body']
base={'profileId':pid,'startsAt':'2027-01-31T09:00:00+05:30','timeZone':'Asia/Kolkata','year':2018,'repeat':'monthly'}
monthly=check('monthlyCreate','POST','/api/run-schedules',201,base)
assert monthly['timeZone']=='Asia/Kolkata' and monthly['nextRunAt']=='2027-01-31T03:30:00+00:00'
check('disableFutureMonthly','PATCH','/api/run-schedules/'+monthly['id'],200,{'enabled':False})
daily=check('dailyRejected','POST','/api/run-schedules',422,{**base,'repeat':'daily'})
assert 'repeat' in str(daily)
naive=check('timezoneRequired','POST','/api/run-schedules',422,{**base,'startsAt':'2027-01-31T09:00:00'})
assert 'time zone' in str(naive)
vn=check('vietnamOnce','POST','/api/run-schedules',201,{**base,'startsAt':'2027-01-31T09:00:00+07:00','timeZone':'Asia/Ho_Chi_Minh','repeat':'once'})
assert vn['nextRunAt']=='2027-01-31T02:00:00+00:00'
check('disableFutureOnce','PATCH','/api/run-schedules/'+vn['id'],200,{'enabled':False})
# Runtime calendar calculation from the exact packaged API module; no clock/source/database mutation.
code="from datetime import datetime;import json;from app.repositories.run_schedules import next_monthly_run;print(json.dumps({z:next_monthly_run('2027-01-31T03:30:00+00:00',datetime.fromisoformat('2027-02-01T00:00:00+00:00'),z) for z in ['Asia/Kolkata','Asia/Ho_Chi_Minh']}))"
r=h.compose('exec','-T','api','python','-c',code);h.save('packaged-monthly-calendar.json',r);assert r['returncode']==0
calendar=json.loads(r['stdout']);assert calendar['Asia/Kolkata']=='2027-02-28T03:30:00+00:00';assert calendar['Asia/Ho_Chi_Minh']=='2027-02-28T03:30:00+00:00'
h.save('schedule-test-ids.json',{'monthly':monthly['id'],'once':vn['id'],'disabled':True})
h.ledger('R7','PASS','Once actually triggered and completed two real cases. Monthly future schedule accepted, UTC offset correct; packaged runtime clamps Jan31 to Feb28; Daily rejected422. Future test schedules disabled; no extra workload during R8.',['small-schedule-create.json','small-run-current.json','schedule-contract.json','packaged-monthly-calendar.json'],start)
print('R7 PASS; zone API conversions PASS; display zone UI pending after R8')
