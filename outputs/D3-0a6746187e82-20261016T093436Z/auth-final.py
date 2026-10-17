import harness as h
import json,time,base64,hmac,hashlib
h.login();began=h.now();cfg=json.loads((h.STAGE/'.d3-private.json').read_text());h.SECRETS.extend([cfg['password'],cfg['idleToken']]);out={}
if time.time()<=cfg['idleExpiresAt']+3:
    raise SystemExit('Natural idle expiry is not due yet; leave token untouched until '+str(cfg['idleExpiresAt']))
r=h.api('GET','/api/auth/me',token=cfg['idleToken']);out['naturalIdleExpiry']={'loginAt':cfg['idleLoginAt'],'idleExpiresAt':cfg['idleExpiresAt'],'checkedAt':h.now(),'response':r,'elapsedSeconds':time.time()-(cfg['idleExpiresAt']-3600)}
h.save('auth-final.json',out);assert r['status']==401,h.clean(r)
r=h.api('POST','/api/auth/login',{'username':cfg['member'],'password':cfg['password']},token=False);assert r['status']==200,h.clean(r)
mt=r['body']['accessToken'];h.SECRETS.append(mt);out['freshLoginAfterExpiry']=r
payload=json.loads(base64.urlsafe_b64decode(mt.split('.')[0]+'=='))
payload['exp']=int(time.time())-1;payload['iat']=payload['exp']-43200
encoded=base64.urlsafe_b64encode(json.dumps(payload,separators=(',',':'),sort_keys=True).encode()).rstrip(b'=')
sig=base64.urlsafe_b64encode(hmac.new(h.CONFIG['VAHAN_UI_AUTH_TOKEN_SECRET'].encode(),encoded,hashlib.sha256).digest()).rstrip(b'=')
expired=encoded.decode()+'.'+sig.decode();h.SECRETS.append(expired)
r=h.api('GET','/api/auth/me',token=expired);out['absoluteExpiredSignedToken']={'method':'Signed negative-test token for the same live disposable member session; exp already past, iat exactly12h earlier; application/server clock untouched','claims':{k:payload[k] for k in ['iat','exp','aud','typ']},'response':r};assert r['status']==401,h.clean(r)
for p in ['/api/docs','/api/openapi.json','/api/redoc','/api/annual-reports/run-history']:
    r=h.api('GET',p,token=mt);out['member'+p]=r;assert r['status']==403,h.clean(r)
r=h.api('PATCH','/api/users/'+cfg['member'],{'active':False});out['disableMember']=r;assert r['status']==200
r=h.api('GET','/api/auth/me',token=mt);out['disabledToken']=r;assert r['status']==401
r=h.api('POST','/api/auth/login',{'username':cfg['member'],'password':cfg['password']},token=False);out['disabledLogin']=r;assert r['status']==401
h.save('auth-final.json',out)
h.ledger('R2','PASS','Admin/member login/logout and RBAC verified; untouched disposable member token expired naturally after60min idle. Correctly signed already-expired12h-bound token rejected401 with server clock untouched. Disabling member revokes live token and rejects fresh login. Browser login/logout PASS, UI socket connected on exact staging Origin.',['baseline-api.json','auth-final.json','browser-ui-pass.json','ui-logout.png'],cfg['idleLoginAt'])
print('R2 PASS including natural idle expiry, signed expired-token rejection and account disable')
