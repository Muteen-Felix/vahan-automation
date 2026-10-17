import json,os,pathlib,runpy,subprocess,sys
import prepare as p

action=sys.argv[1]
state=json.loads((p.ROOT/('upgrade-engine.json' if action.startswith('t45b') else 'clean-engine.json')).read_text(encoding='utf-8'))
os.environ['DOCKER_HOST']=state['dockerHost']
for key in ('DOCKER_CONTEXT','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'):os.environ.pop(key,None)
import fresh as f
ports=iter([state['webPort'],state['apiPort']])
f.port=lambda:next(ports)
action=sys.argv[1]
if action=='fresh':
    f.main()
    installed=json.loads((p.ROOT/'fresh-environment.json').read_text(encoding='utf-8'))
    root=pathlib.Path(installed['root'])
    p.run(['docker','compose','--env-file','.docker.env','-p',installed['project'],'stop'],'fresh-retain-stopped-stack',cwd=root)
elif action in ('fresh-safety','t45b-build','t45b-prepopulate','t45b-revalidate-baseline','t45b-upgrade','t45b-extra'):
    runpy.run_path(str(p.ROOT/(action+'.py')),run_name='__main__')
else:raise SystemExit('Unknown phase')
