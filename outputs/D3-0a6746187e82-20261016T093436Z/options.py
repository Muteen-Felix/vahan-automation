import harness as h
import time,json
h.login(); began=h.now()
for i in range(60):
    runners=h.api('GET','/api/runners')['body']
    if len(runners)==3 and all(r['status']=='ONLINE' for r in runners):break
    time.sleep(1)
else:raise RuntimeError('Three runners did not reconnect')
pre=h.api('POST','/api/ui-health/preflight',{'runnerIds':[r['id'] for r in runners]},timeout=240)
h.save('post-restart-preflight.json',pre)
assert pre['status']==200 and pre['body']['allowed'],h.clean(pre)
h.ledger('R6','PASS','Three real packaged runners pass SQL-backed VAHAN DOM preflight, before and after API restart. Test harness waited for reconnect; no gate bypass.',['real-vahan-preflight.json','post-restart-preflight.json'],began)
opts=h.api('POST','/api/filter-profiles/options',{'runnerId':runners[0]['id'],'year':2018,'context':{}},timeout=180)
h.save('native-options.json',opts);assert opts['status']==200,h.clean(opts)
print(json.dumps(h.clean(opts['body']),ensure_ascii=False))
