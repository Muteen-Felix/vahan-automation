import json, os, subprocess, time, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parent
PRE=ROOT.parent/'release-F-0a6746187e82-20261016T090229Z'
ENV=json.loads((PRE/'staging-environment.json').read_text(encoding='utf-8-sig'))
STAGE=Path(ENV['root'])
SOURCE=Path(r'C:\Users\huyvv12\AppData\Local\Temp\vahan-release-F-clean-20261016T090229Z')
SHA=ENV['sha']
CONFIG={}
for line in (STAGE/'.docker.env').read_text(encoding='utf-8-sig').splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        k,v=line.split('=',1); CONFIG[k.strip()]=v.strip().strip('"').strip("'")
SECRETS=[v for k,v in CONFIG.items() if any(x in k.upper() for x in ('PASSWORD','SECRET','TOKEN','DATABASE_URL')) and v]
TOKEN=None
def now(): return datetime.now(timezone.utc).isoformat()
def clean(value):
    if isinstance(value,dict):
        return {k:('[REDACTED]' if any(x in k.lower() for x in ('password','accesstoken','authorization','secret','captchatext','ocrtext')) else clean(v)) for k,v in value.items()}
    if isinstance(value,list): return [clean(v) for v in value]
    if isinstance(value,str):
        for secret in SECRETS: value=value.replace(secret,'[REDACTED]')
    return value
def save(name,value):
    (ROOT/name).write_text(json.dumps(clean(value),ensure_ascii=False,indent=2),encoding='utf-8')
def call(method,path,body=None,token=True,timeout=180,base=None):
    headers={}
    if token and (TOKEN if token is True else token): headers['Authorization']='Bearer '+(TOKEN if token is True else token)
    if body is not None: headers['Content-Type']='application/json'
    req=urllib.request.Request((base or ENV['baseUrl'])+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
    started=now()
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r: status=r.status; data=r.read(); hdr=dict(r.headers)
    except urllib.error.HTTPError as r: status=r.code; data=r.read(); hdr=dict(r.headers)
    try: value=json.loads(data)
    except (ValueError,UnicodeDecodeError):
        try: value=data.decode()
        except UnicodeDecodeError: value={'binaryBytes':len(data)}
    return {'startedAt':started,'finishedAt':now(),'method':method,'path':path,'status':status,'headers':hdr,'body':value},data
def api(method,path,body=None,**kw): return call(method,path,body,**kw)[0]
def login():
    global TOKEN
    result=api('POST','/api/auth/login',{'username':CONFIG.get('VAHAN_UI_AUTH_USERNAME','admin'),'password':CONFIG['VAHAN_UI_AUTH_PASSWORD']},token=False)
    assert result['status']==200,clean(result)
    TOKEN=result['body']['accessToken'];SECRETS.append(TOKEN)
    return result
def cmd(args,timeout=180):
    e=os.environ.copy(); e.pop('DOCKER_HOST',None)
    r=subprocess.run(args,cwd=STAGE,env=e,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
    return {'command':args,'at':now(),'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr}
def compose(*args): return cmd(['docker','compose','--env-file','.docker.env','-p',ENV['project'],*args])
def ledger(item,status,reason,evidence,started=None):
    p=ROOT/'checklist.json'; data=json.loads(p.read_text(encoding='utf-8'))
    for row in data['items']:
        if row['item']==item: row.update(status=status,reason=reason,evidence=evidence,startedAt=started or now(),finishedAt=now(),recordedAt=now())
    save('checklist.json',data)
if __name__=='__main__':
    approval={'approvedAtRecorded':now(),'userReply':'Chốt gói và bắt đầu D3','sha':SHA,'manifestDigest':ENV['manifestDigest'],'imageArchiveDigest':ENV['imageArchiveDigest'],'staging':ENV['baseUrl'],'constraints':['Staging and real VAHAN only','No source changes or artifact rebuild during D3','Stop and report if source/artifact change is needed']}
    save('approval.json',approval)
    checklist=json.loads((PRE/'D3-checklist.json').read_text(encoding='utf-8-sig'));checklist.update(D3Started=True,recordedAt=now())
    for row in checklist['items']:
        row.update(recordedAt=now(),reason='Not yet executed during this D3' if row['item'] not in ('S8','S10') else 'Deferred under approved D-02 scope',evidence=[],startedAt=None,finishedAt=None)
    save('checklist.json',checklist)
    gate=cmd(['py','-3',str(PRE/'d3-package-gate.py'),'--expected-sha',SHA,'--expected-manifest-digest',ENV['manifestDigest'],'--expected-images-digest',ENV['imageArchiveDigest']],timeout=300)
    save('identity-gate.json',gate); assert gate['returncode']==0
    login();save('initial-observations.json',{p:api('GET',p,token=p!='/api/health' and p!='/api/ready') for p in ['/api/health','/api/ready','/api/auth/me','/api/runners','/api/worker-pool','/api/ui-health/status','/api/run-schedules','/api/annual-reports/run-history']})
    runners=api('GET','/api/runners')['body']; ids=[r['id'] for r in runners]
    result=api('POST','/api/ui-health/preflight',{'runnerIds':ids},timeout=240)
    save('real-vahan-preflight.json',result)
    print(json.dumps({'identityGate':gate['returncode'],'runners':ids,'preflightStatus':result['status'],'preflightBody':clean(result['body'])},ensure_ascii=False))
