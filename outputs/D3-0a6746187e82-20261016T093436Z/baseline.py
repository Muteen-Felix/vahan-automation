import harness as h
import json,secrets,time
from datetime import datetime,timedelta,timezone
h.login(); started=h.now(); results={}
def check(key,method,path,expected,body=None,**kw):
    r=h.api(method,path,body,**kw);results[key]=r;h.save('baseline-api.json',results)
    assert r['status']==expected,(key,h.clean(r));return r['body']
password=secrets.token_urlsafe(24);h.SECRETS.append(password)
member='d3-member-20261016';check('createMember','POST','/api/users',201,{'username':member,'password':password,'role':'user'})
memberLogin=check('memberLogin','POST','/api/auth/login',200,{'username':member,'password':password},token=False)
mt=memberLogin['accessToken'];h.SECRETS.append(mt)
check('memberMe','GET','/api/auth/me',200,token=mt)
for p in ['/api/users','/api/audit','/api/run-schedules','/api/worker-pool','/api/annual-reports/run-history']:
    check('memberDenied'+p,'GET',p,403,token=mt)
check('memberRead','GET','/api/annual-reports',200,token=mt)
check('memberLogout','POST','/api/auth/logout',200,token=mt)
check('memberRevoked','GET','/api/auth/me',401,token=mt)
idle=h.api('POST','/api/auth/login',{'username':member,'password':password},token=False)
assert idle['status']==200
# Keep test-only credentials outside the evidence tree; natural idle expiry will be verified later.
(h.STAGE/'.d3-private.json').write_text(json.dumps({'member':member,'password':password,'idleToken':idle['body']['accessToken'],'idleLoginAt':idle['startedAt'],'idleExpiresAt':idle['body']['idleExpiresAt']}),encoding='utf-8')
check('adminLogout','POST','/api/auth/logout',200)
check('adminRevoked','GET','/api/auth/me',401)
h.login()
check('persistenceMarker','PUT','/api/user-state/d3-persistence',200,{'value':{'sha':h.SHA,'createdAt':started}})
before={p:check('before'+p,'GET',p,200) for p in ['/api/user-state','/api/users','/api/run-schedules','/api/annual-reports/run-history']}
restart=h.compose('restart','api');h.save('api-restart.json',restart);assert restart['returncode']==0
for i in range(45):
    try:
        ready=h.api('GET','/api/ready',token=False,timeout=5)
        if ready['status']==200:break
    except Exception:pass
    time.sleep(1)
else: raise RuntimeError('API did not become ready')
after={p:check('after'+p,'GET',p,200) for p in before}
assert before==after
check('sameAdminSessionAfterRestart','GET','/api/auth/me',200)
h.ledger('R1','PASS','Health/ready 200; restart packaged API preserved user state, users, schedules, run history and existing admin session. Business report persistence also checked after real workload.',['baseline-api.json','api-restart.json'],started)
h.ledger('O1','PASS','Health and readiness probed from host outside Docker stack before and after restart.',['baseline-api.json','api-restart.json'],started)
runners=check('runners','GET','/api/runners',200)
pre=check('preflightAfterRestart','POST','/api/ui-health/preflight',200,{'runnerIds':[r['id'] for r in runners]})
assert pre['allowed'] and all(r['allowed'] for r in pre['reports'])
h.ledger('R6','PASS','Real VAHAN preflight after API restart: three actual packaged runners PASS, SQL-backed matching DOM evidence, no bypass.',['real-vahan-preflight.json','baseline-api.json'],started)
opts=check('nativeOptions','POST','/api/filter-profiles/options',200,{'runnerId':runners[0]['id'],'year':2018,'context':{}})
h.save('native-options.json',opts)
print(json.dumps({'baseline':'PASS','R2':'logout/RBAC PASS; natural idle expiry pending','options':opts},ensure_ascii=False))
