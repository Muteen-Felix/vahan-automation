import json, os, pathlib, subprocess, sys, tempfile, zipfile
import prepare as p
import fresh as f

BASE='2bc878eed2640c3f6560657afee49aef5b956cf5'
root=pathlib.Path(tempfile.mkdtemp(prefix='vahan-t45b-0a67-baseline-'))
archive=root.parent/(root.name+'.zip')
p.run(['git','archive','--format=zip','-o',str(archive),BASE,'README.md','compose.yaml','.dockerignore','.gitignore','apps','docker','scripts','tools'],'t45b-baseline-source')
with zipfile.ZipFile(archive) as z: z.extractall(root)
p.run([sys.executable,'scripts/setup-docker.py'],'t45b-baseline-setup',cwd=root)
v=f.values_at(root)
assert not any(k.startswith('DB_APP_') for k in v)
web,api=f.port(),f.port()
while web==api: api=f.port()
v.update(WEB_BIND_ADDRESS='0.0.0.0',API_BIND_ADDRESS='0.0.0.0',VAHAN_IMAGE_NAMESPACE='vahan-t45b-0a67-baseline',VAHAN_IMAGE_TAG='2bc878eed264',WEB_PORT=str(web),API_PORT=str(api))
(root/'.docker.env').write_text(''.join(f'{k}={value}\n' for k,value in v.items()))
p.REDACTIONS.extend(value for k,value in v.items() if any(t in k for t in ('PASSWORD','TOKEN','SECRET','STATE_KEY')))
project='vahan-t45b-0a67-20261016t090229'
env={**os.environ,'COMPOSE_PROJECT_NAME':project}
p.save('t45b-environment.json',{'sha':p.SHA,'baselineSha':BASE,'project':project,'baselineRoot':str(root),'baseUrl':f'http://127.0.0.1:{web}','webPort':web,'apiPort':api,'createdAt':p.now(),'dataScope':'Explicitly labelled persistent upgrade test data on a newly built old version. No production dump, no real-VAHAN result claim.'})
outer_env={k:value for k,value in env.items() if k not in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH')}
p.run(['docker','compose','--env-file','.docker.env','-p',project,'build','api','web','runner'],'t45b-baseline-build',cwd=root,env=outer_env,timeout=3600)
p.run(['docker','pull','postgres:17.7-bookworm'],'t45b-baseline-postgres',cwd=root,env=outer_env)
baseline_tar=root.parent/(root.name+'-images.tar')
refs=['vahan-t45b-0a67-baseline/'+name+':2bc878eed264' for name in ('api','web','runner')]+['postgres:17.7-bookworm']
p.run(['docker','image','save','-o',str(baseline_tar),*refs],'t45b-baseline-save',cwd=root,env=outer_env)
p.run(['docker','image','load','-i',str(baseline_tar)],'t45b-baseline-load',cwd=root,env=env)
p.run(['docker','compose','--env-file','.docker.env','-p',project,'up','-d','--wait','--wait-timeout','180','--no-build','postgres','api','web','runner'],'t45b-baseline-start',cwd=root,env=env,timeout=360)
p.run(['docker','compose','--env-file','.docker.env','-p',project,'exec','-T','postgres','psql','-U','vahan','-d','vahan','-XAtc','select version_num from alembic_version'],'t45b-baseline-schema',cwd=root,env=env)
