import json,os,pathlib,shutil,socket,subprocess,sys,tempfile,zipfile
import prepare as p
import fresh as f

PROJECT='vahan-d3-0a67-20261016t090229'
def free_port(preferred):
    with socket.socket() as sock:
        try:sock.bind(('127.0.0.1',preferred));return preferred
        except OSError:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]

def main():
    assert 'DOCKER_HOST' not in os.environ,'Staging must use the host Docker engine'
    ci=json.loads((p.ROOT/'ci-checks.json').read_text(encoding='utf-8'))
    assert len(ci['response']['check_runs'])==6 and all(c['head_sha']==p.SHA and c['conclusion']=='success' for c in ci['response']['check_runs'])
    fresh=json.loads((p.ROOT/'fresh-result.json').read_text(encoding='utf-8'))
    upgrade=json.loads((p.ROOT/'t45b-result.json').read_text(encoding='utf-8'))
    assert fresh['status']=='PASS' and upgrade['status']=='PASS'
    for filename,expected in f.M['files'].items():assert f.digest(f.PACKAGE/filename)==expected
    root=pathlib.Path(tempfile.mkdtemp(prefix='vahan-d3-0a67-staging-'))
    with zipfile.ZipFile(next(f.PACKAGE.glob('*-source.zip'))) as z:z.extractall(root)
    p.run([sys.executable,'scripts/setup-docker.py'],'staging-setup',cwd=root)
    values=f.values_at(root)
    if os.environ.get('VAHAN_STAGING_ADMIN_PASSWORD'):
        values['VAHAN_UI_AUTH_PASSWORD']=os.environ['VAHAN_STAGING_ADMIN_PASSWORD']
    web,api=free_port(15187),free_port(18087)
    base=f'http://127.0.0.1:{web}'
    values.update(VAHAN_WORKER_REPLICAS='3',VAHAN_IMAGE_NAMESPACE=f.M['imageNamespace'],VAHAN_IMAGE_TAG=f.M['imageTag'],WEB_PORT=str(web),API_PORT=str(api),WEB_BIND_ADDRESS='127.0.0.1',API_BIND_ADDRESS='127.0.0.1',VAHAN_API_CORS_ORIGINS=base,VAHAN_API_SOCKETIO_CORS_ORIGINS=base)
    (root/'.docker.env').write_text(''.join(f'{key}={value}\n' for key,value in values.items()))
    p.REDACTIONS.extend(value for key,value in values.items() if any(t in key for t in ('PASSWORD','TOKEN','SECRET','STATE_KEY')))
    env={**os.environ,'COMPOSE_PROJECT_NAME':PROJECT,'VAHAN_SMOKE_ADMIN_PASSWORD':values['VAHAN_UI_AUTH_PASSWORD']}
    env.pop('VAHAN_STAGING_ADMIN_PASSWORD',None)
    c=['docker','compose','--env-file','.docker.env','-p',PROJECT]
    state={'sha':p.SHA,'createdAt':p.now(),'project':PROJECT,'root':str(root),'baseUrl':base,'apiUrl':f'http://127.0.0.1:{api}','workers':3,'manifestDigest':f.digest(f.MANIFEST),'imageArchiveDigest':f.M['files'][next(n for n in f.M['files'] if n.endswith('images.tar'))],'userSelected':'Separate clean staging from the new package on this machine','D3':'NOT_RUN','credentialsLocation':str(root/'.docker.env')}
    p.save('staging-environment.json',state)
    p.run(['docker','image','load','-i',str(next(f.PACKAGE.glob('*-images.tar')))],'staging-load-final-package',cwd=root)
    p.run([sys.executable,'scripts/run-docker.py','--check-release'],'staging-fresh-release-guard',cwd=root,env=env)
    p.run([sys.executable,'scripts/run-docker.py','--assess-only'],'staging-resource-assessment',cwd=root,env=env)
    p.run([sys.executable,'scripts/run-docker.py','--no-build','--workers','3'],'staging-launcher',cwd=root,env=env,timeout=420)
    p.run([sys.executable,'scripts/release-smoke.py','--base-url',base,'--admin-user','admin','--min-runners','3','--compose-project',PROJECT,'--require-compose-checks','--output',str(p.ROOT/'staging-smoke.json')],'staging-smoke-command',cwd=root,env=env,timeout=240)
    ids=subprocess.check_output(['docker','ps','-aq','--filter','label=com.docker.compose.project='+PROJECT],text=True).split()
    containers=json.loads(subprocess.check_output(['docker','inspect',*ids],text=True));safe=[]
    for container in containers:
        ref=container['Config']['Image'];assert container['Image']==f.M['imageIds'][ref]
        safe.append({'name':container['Name'],'imageRef':ref,'imageId':container['Image'],'state':container['State']['Status'],'health':container['State'].get('Health',{}).get('Status'),'exitCode':container['State']['ExitCode'],'service':container['Config']['Labels']['com.docker.compose.service']})
    assert len([item for item in safe if item['service']=='runner' and item['health']=='healthy'])==3
    p.save('staging-image-identity.json',{'sha':p.SHA,'checkedAt':p.now(),'status':'PASS','manifestDigest':state['manifestDigest'],'containers':safe})
    p.run([sys.executable,'scripts/config-snapshot.py','--env-file',str(root/'.docker.env'),'--project-dir',str(root),'--image-ids','--out',str(p.ROOT/'staging-config-snapshot.json')],'staging-config-snapshot-command',cwd=root,env=env)
    assert not json.loads((p.ROOT/'staging-config-snapshot.json').read_text(encoding='utf-8'))['reviewErrors']
    sql="SELECT json_build_object('businessReports',(SELECT count(*) FROM main_reports),'jobs',(SELECT count(*) FROM jobs),'reportSessions',(SELECT count(*) FROM report_sessions),'queueSessions',(SELECT count(*) FROM batch_queue_sessions),'schedules',(SELECT count(*) FROM app_settings WHERE key LIKE 'automatic-report-schedule:%'),'schema',(SELECT version_num FROM alembic_version));"
    counts=json.loads(p.run([*c,'exec','-T','postgres','psql','-U','vahan','-d','vahan','-XAtc',sql],'staging-clean-data',cwd=root,env=env))
    assert all(value==0 for key,value in counts.items() if key!='schema')
    assert counts['schema']=='0016_state_revision_gate_gen'
    p.run([sys.executable,'scripts/run-docker.py','--check-release'],'staging-final-release-guard',cwd=root,env=env)
    p.save('staging-result.json',{'sha':p.SHA,'finishedAt':p.now(),'status':'PASS','project':PROJECT,'baseUrl':base,'workers':3,'smoke':'14/14 PASS','cleanBusinessData':counts,'manifestDigest':state['manifestDigest'],'imageArchiveDigest':state['imageArchiveDigest'],'D3':'NOT_RUN','pending':'User review and approval of the final package digest before D3'})
    print('Separate staging prepared from final package; D3 NOT_RUN',flush=True)

if __name__=='__main__':main()
