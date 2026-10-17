import json,os,pathlib,subprocess
import prepare as p
import fresh as f

state=json.loads((p.ROOT/'staging-environment.json').read_text(encoding='utf-8'))
root=pathlib.Path(state['root']);env={**os.environ,'COMPOSE_PROJECT_NAME':state['project']}
ids=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+state['project'],'--filter','label=com.docker.compose.service=runner'],text=True).split()
assert len(ids)==3
checks=[]
for index,container in enumerate(ids,1):
    body=p.run(['docker','exec','--env','VAHAN_RUNTIME_LIVE_PROBE=1',container,'node','test-container-runtime.mjs'],f'staging-runner-{index}-navigation-only',cwd=root,env=env,timeout=90)
    result=json.loads(body)
    live=result.get('liveVahan',{})
    passed=live.get('status')==200 and live.get('url','').startswith('https://analytics.parivahan.gov.in/') and live.get('passed') is not False
    checks.append({'runnerContainer':container,'status':'PASS' if passed else 'FAIL','result':result})
p.save('staging-network-readiness.json',{'sha':p.SHA,'checkedAt':p.now(),'status':'PASS' if all(c['status']=='PASS' for c in checks) else 'FAIL','scope':'Pre-D3 HTTPS navigation only using the real packaged Chromium sandbox. No CAPTCHA submitted, report collected, UI Health preflight invoked or D3 result claimed. TLS verification remains enabled.','checks':checks,'D3':'NOT_RUN'})
assert all(c['status']=='PASS' for c in checks),'Real VAHAN navigation is not ready; inspect staging-network-readiness.json before authorizing D3.'
print('Real VAHAN HTTPS navigation ready on 3/3 staged runners; D3 still NOT_RUN',flush=True)
