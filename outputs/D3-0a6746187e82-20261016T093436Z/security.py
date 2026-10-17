import harness as h
import urllib.request,urllib.error,time,json
h.login();began=h.now();out={}
def check(key,method,path,expected,body=None,**kw):
    r=h.api(method,path,body,**kw);out[key]=r;h.save('security-api.json',out)
    assert r['status']==expected,(key,h.clean(r));return r
for p in ['/api/maker-updates','/api/ui-health/schedule','/api/ui-health/run-now']:
    check(p,'POST' if p.endswith('run-now') else 'GET',p,404)
before=h.api('GET','/api/jobs');out['jobsBefore']=before
for field,value in [('updateKind','GLOBAL'),('updateKind','DISCOVER'),('updateKind','REFRESH'),('updateRunId','removed'),('updateTaskId','removed'),('update_kind','GLOBAL')]:
    r=check(field+value,'POST','/api/jobs',422,{'runnerId':'d3-rejected-no-dispatch','filters':{},field:value})
    assert 'Maker Update has been removed' in str(r['body'])
after=h.api('GET','/api/jobs');out['jobsAfter']=after
# No job using our rejected sentinel may exist; concurrent real VAHAN jobs are allowed.
assert 'd3-rejected-no-dispatch' not in json.dumps(after['body'])
h.ledger('R13','PASS','All six retired Maker Update fields/variants rejected with 422; no sentinel job dispatched.',['security-api.json'],began)
h.ledger('R15','PASS','Removed Maker Update and UI Health schedule/run-now routes return 404.',['security-api.json'],began)
for p in ['/docs','/openapi.json','/redoc']:
    r=check('SPA'+p,'GET',p,200,token=False)
    assert 'text/html' in r['headers'].get('Content-Type','') and '<html' in r['body'].lower()
    check('admin'+p,'GET','/api'+p,404)
    check('unauth'+p,'GET','/api'+p,401,token=False)
h.ledger('S7','PASS','API docs disabled: unauthenticated 401, admin 404; root paths return accepted SPA HTML shell only.',['security-api.json'],began)
for p in ['/','/api/health']:
    r=check('headers'+p,'GET',p,200,token=False);headers={k.lower():v for k,v in r['headers'].items()}
    for k in ['x-content-type-options','x-frame-options','referrer-policy','permissions-policy','content-security-policy']:assert k in headers,(p,k)
    assert headers['x-frame-options']=='DENY' and headers['x-content-type-options']=='nosniff'
h.ledger('S6','PASS','Web and API responses include expected security headers, DENY and nosniff.',['security-api.json'],began)
socket=[]
for origin,expected in [('http://evil.example',400),(h.ENV['baseUrl'],200)]:
    req=urllib.request.Request(h.ENV['baseUrl']+'/socket.io/?EIO=4&transport=polling',headers={'Origin':origin})
    try:
        with urllib.request.urlopen(req,timeout=15) as r:status=r.status;headers=dict(r.headers);data=r.read().decode()
    except urllib.error.HTTPError as r:status=r.code;headers=dict(r.headers);data=r.read().decode()
    socket.append({'at':h.now(),'origin':origin,'status':status,'headers':headers,'engineOpen':data.startswith('0{')})
    h.save('socket-origin.json',socket);assert status==expected,socket[-1]
h.ledger('S5','PASS','Engine.IO handshake rejects untrusted Origin with 400; exact staging Origin accepted with 200.',['socket-origin.json'],began)
# Deliberately invalid credentials for a nonexistent account, through packaged nginx rate limiter.
rates=[]
for i in range(24):
    r=h.api('POST','/api/auth/login',{'username':'d3-no-such-user-rate-test','password':'invalid-d3-rate-test'},token=False)
    rates.append({'at':r['startedAt'],'status':r['status']});assert r['status'] in (401,429)
h.save('login-rate-limit.json',rates);assert any(r['status']==429 for r in rates)
h.ledger('S3','PASS','Burst of 24 invalid logins to nonexistent account through nginx produced 401 and 429; no admin credential lockout.',['login-rate-limit.json'],began)
print('Security checks completed PASS')
