import json,os,pathlib,sys
import prepare as p
import fresh as f

state=json.loads((p.ROOT/'t45b-environment.json').read_text(encoding='utf-8'))
root=pathlib.Path(state['baselineRoot']);env={**os.environ,'COMPOSE_PROJECT_NAME':state['project']}
v=f.values_at(root)
p.REDACTIONS.extend(value for key,value in v.items() if any(t in key for t in ('PASSWORD','TOKEN','SECRET','STATE_KEY')))
c=['docker','compose','--env-file','.docker.env','-p',state['project']]
assert not (p.ROOT/'t45b-data-identity.json').exists(),'Do not populate an existing test dataset twice'
version=p.run([*c,'exec','-T','postgres','psql','-U','vahan','-d','vahan','-XAtc','select version_num from alembic_version'],'t45b-preparation-schema',cwd=root,env=env)
assert version=='0012_auth_session_limits'
seed=p.run([*c,'exec','-T','api','python','-'],'t45b-seed',cwd=root,env=env,input=(p.ROOT/'t45b-seed.py').read_text(encoding='utf-8'))
ids=json.loads(seed.splitlines()[-1]);ids['createdAt']=p.now();ids['baselineSha']=state['baselineSha'];p.save('t45b-data-identity.json',ids)
token=f.api(state['baseUrl'],'/api/auth/login','POST',{'username':'admin','password':v['VAHAN_UI_AUTH_PASSWORD']})['accessToken'];p.REDACTIONS.append(token)
report=f.api(state['baseUrl'],'/api/annual-reports?year=2025',token=token)
history=f.api(state['baseUrl'],'/api/annual-reports/history?year=2025',token=token)
assert report['summary']['rows']==3 and history['total']==1
p.save('t45b-old-application-data.json',{'checkedAt':p.now(),'baselineSha':state['baselineSha'],'candidateSha':p.SHA,'status':'PASS','report':report,'history':history,'scope':'Labelled synthetic content saved persistently by the running old application, verified through its HTTP API. This is upgrade preparation, not real VAHAN or D3 evidence.'})
print('Old version is running with persisted application data for T45b',flush=True)
