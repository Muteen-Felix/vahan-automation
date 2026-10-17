import json,os,pathlib
import prepare as p
import fresh as f

state=json.loads((p.ROOT/'t45b-environment.json').read_text(encoding='utf-8'))
root=pathlib.Path(state['baselineRoot']);env={**os.environ,'COMPOSE_PROJECT_NAME':state['project']}
values=f.values_at(root)
p.REDACTIONS.extend(value for key,value in values.items() if any(t in key for t in ('PASSWORD','TOKEN','SECRET','STATE_KEY')))
c=['docker','compose','--env-file','.docker.env','-p',state['project']]
p.run([*c,'start','--wait','--wait-timeout','180','postgres'],'t45b-resume-old-database',cwd=root,env=env,timeout=210)
p.run([*c,'start','--wait','--wait-timeout','180','api','web'],'t45b-resume-old-applications',cwd=root,env=env,timeout=210)
version=p.run([*c,'exec','-T','postgres','psql','-U','vahan','-d','vahan','-XAtc','select version_num from alembic_version'],'t45b-old-schema-reverified',cwd=root,env=env)
assert version=='0012_auth_session_limits'
token=f.api(state['baseUrl'],'/api/auth/login','POST',{'username':'admin','password':values['VAHAN_UI_AUTH_PASSWORD']})['accessToken'];p.REDACTIONS.append(token)
report=f.api(state['baseUrl'],'/api/annual-reports?year=2025',token=token)
history=f.api(state['baseUrl'],'/api/annual-reports/history?year=2025',token=token)
assert report['summary']['rows']==3 and history['total']==1
p.save('t45b-old-application-data.json',{'candidateSha':p.SHA,'baselineSha':state['baselineSha'],'checkedAt':p.now(),'status':'PASS','report':report,'history':history,'scope':'Current HTTP verification of the prepared persistent old-version dataset. Content is explicitly synthetic; no prior candidate test outcome or real VAHAN result is reused.'})
p.run([*c,'stop','api','web'],'t45b-stop-old-applications-after-reverification',cwd=root,env=env)
