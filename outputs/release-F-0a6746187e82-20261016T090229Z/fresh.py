import hashlib, json, os, pathlib, re, socket, subprocess, sys, tempfile, time, urllib.request, zipfile
import prepare as p

PACKAGE=p.ROOT/'package'
MANIFEST=next(PACKAGE.glob('*-manifest.json'),None)
M=json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST else None
PROJECT='vahan-f0a67-fresh-20261016t090229'

def digest(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()

def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0)); return s.getsockname()[1]

def values_at(root):
    return dict(line.split('=',1) for line in (root/'.docker.env').read_text().splitlines() if line and not line.startswith('#') and '=' in line)

def api(base,path,method='GET',payload=None,token=None):
    headers={'Content-Type':'application/json'}
    if token: headers['Authorization']='Bearer '+token
    req=urllib.request.Request(base+path, data=json.dumps(payload).encode() if payload is not None else None,headers=headers,method=method)
    with urllib.request.urlopen(req,timeout=30) as r: return json.load(r)

def main():
    assert M['sourceCommit']==M['imageRevision']==p.SHA and M['version']==M['imageTag']=='1.0.0'
    sums={name:value for value,name in (line.split('  ',1) for line in (PACKAGE/'SHA256SUMS').read_text().splitlines())}
    checked={name:digest(PACKAGE/name) for name in sums}
    assert checked==sums and all(checked[k]==v for k,v in M['files'].items())
    p.save('package-validation.json',{'sha':p.SHA,'checkedAt':p.now(),'checksums':checked,'sha256sumsDigest':digest(PACKAGE/'SHA256SUMS'),'manifest':M,'status':'PASS'})
    root=pathlib.Path(tempfile.mkdtemp(prefix='vahan-f0a67-fresh-new-'))
    source=next(PACKAGE.glob('*-source.zip'))
    with zipfile.ZipFile(source) as z:
        names=z.namelist()
        forbidden=[n for n in names if pathlib.PurePosixPath(n).name in {'.env','.docker.env'} or pathlib.PurePosixPath(n).suffix.lower() in {'.crt','.pem','.key','.p12','.pfx'} or '.secrets' in pathlib.PurePosixPath(n).parts]
        assert not forbidden
        z.extractall(root)
    assert not (root/'.docker.env').exists() and not (root/'node_modules').exists()
    env={**os.environ,'COMPOSE_PROJECT_NAME':PROJECT}
    comp=['docker','compose','--env-file','.docker.env','-p',PROJECT]
    p.run([sys.executable,'scripts/setup-docker.py'],'fresh-setup',cwd=root)
    v=values_at(root)
    assert v.get('DB_APP_USERNAME') and len(v.get('DB_APP_PASSWORD',''))>=24
    web_port,api_port=port(),port()
    while api_port==web_port: api_port=port()
    v.update(WEB_BIND_ADDRESS='0.0.0.0',API_BIND_ADDRESS='0.0.0.0',VAHAN_IMAGE_NAMESPACE=M['imageNamespace'],VAHAN_IMAGE_TAG=M['imageTag'],WEB_PORT=str(web_port),API_PORT=str(api_port),VAHAN_API_CORS_ORIGINS=f'http://127.0.0.1:{web_port}',VAHAN_API_SOCKETIO_CORS_ORIGINS=f'http://127.0.0.1:{web_port}')
    (root/'.docker.env').write_text(''.join(f'{k}={value}\n' for k,value in v.items()))
    p.REDACTIONS.extend(value for k,value in v.items() if any(t in k for t in ('PASSWORD','TOKEN','SECRET','STATE_KEY')))
    p.save('fresh-environment.json',{'sha':p.SHA,'project':PROJECT,'root':str(root),'baseUrl':f'http://127.0.0.1:{web_port}','apiPort':api_port,'createdAt':p.now(),'scope':'New extracted source and generated credentials in an initially empty isolated Docker daemon; only package images loaded. Inner bind 0.0.0.0 is published solely on 127.0.0.1 by the outer test container. Same Windows host, not a separate VM. No live VAHAN preflight requested.'})
    p.run(['docker','image','load','-i',str(next(PACKAGE.glob('*-images.tar')))],'fresh-docker-load',cwd=root)
    image_checks=[]
    for ref,expected in M['imageIds'].items():
        info=json.loads(subprocess.check_output(['docker','image','inspect',ref],text=True))[0]
        labels=info['Config'].get('Labels') or {}
        assert info['Id']==expected
        assert info['Os']+'/'+info['Architecture']=='linux/amd64'
        if not M['images'][ref]['upstream']:
            assert labels.get('org.opencontainers.image.revision')==p.SHA
            assert labels.get('org.opencontainers.image.version')=='1.0.0'
        image_checks.append({'ref':ref,'id':info['Id'],'revision':labels.get('org.opencontainers.image.revision'),'version':labels.get('org.opencontainers.image.version')})
    p.save('fresh-loaded-images.json',{'sha':p.SHA,'checkedAt':p.now(),'status':'PASS','images':image_checks})
    p.run([sys.executable,'scripts/run-docker.py','--check-release'],'fresh-release-guard',cwd=root,env=env)
    p.run([sys.executable,'scripts/run-docker.py','--no-build','--workers','1'],'fresh-install-launcher',cwd=root,env=env,timeout=420)
    p.run([*comp,'ps','-a','--format','json'],'fresh-container-status',cwd=root,env=env)
    p.run([*comp,'logs','--no-color','migrate'],'fresh-initial-migration',cwd=root,env=env)
    revision=p.run([*comp,'exec','-T','postgres','psql','-U','vahan','-d','vahan','-XAtc','select version_num from alembic_version'],'fresh-schema',cwd=root,env=env)
    assert revision=='0016_state_revision_gate_gen'
    env['VAHAN_SMOKE_ADMIN_PASSWORD']=v['VAHAN_UI_AUTH_PASSWORD']
    p.run([sys.executable,'scripts/release-smoke.py','--base-url',f'http://127.0.0.1:{web_port}','--admin-user','admin','--min-runners','1','--compose-project',PROJECT,'--require-compose-checks','--output',str(p.ROOT/'fresh-smoke.json')],'fresh-smoke-command',cwd=root,env=env,timeout=240)
    p.run([*comp,'run','--rm','--pull','never','migrate'],'fresh-migration-rerun',cwd=root,env=env,timeout=150)
    p.run([*comp,'exec','-T','runner','node','test-container-runtime.mjs'],'fresh-chromium-tesseract',cwd=root,env=env,timeout=240)
    p.run([sys.executable,'scripts/config-snapshot.py','--env-file',str(root/'.docker.env'),'--project-dir',str(root),'--image-ids','--out',str(p.ROOT/'fresh-config-snapshot.json')],'fresh-config-snapshot-command',cwd=root,env=env)
    snap=json.loads((p.ROOT/'fresh-config-snapshot.json').read_text())
    assert not snap['reviewErrors']
    base=f'http://127.0.0.1:{web_port}'
    login=api(base,'/api/auth/login','POST',{'username':'admin','password':v['VAHAN_UI_AUTH_PASSWORD']})
    token=login['accessToken']; p.REDACTIONS.append(token)
    marker={'label':'RELEASE F FRESH INSTALL PERSISTENCE TEST','sha':p.SHA}
    api(base,'/api/user-state/releaseFProbe','PUT',{'value':marker},token)
    p.run([*comp,'stop'],'fresh-stop',cwd=root,env=env,timeout=120)
    p.run([sys.executable,'scripts/run-docker.py','--no-build','--workers','1'],'fresh-restart',cwd=root,env=env,timeout=420)
    assert api(base,'/api/user-state',token=token)['releaseFProbe']==marker
    p.save('fresh-persistence.json',{'sha':p.SHA,'checkedAt':p.now(),'status':'PASS','test':'User state and login session survive complete Compose stop/start without rebuilding'})
    fingerprint={}
    fingerprint['apiPackages']=p.run([*comp,'exec','-T','api','python','-c','import importlib.metadata,json; print(json.dumps(sorted([(d.metadata["Name"],d.version) for d in importlib.metadata.distributions()])))'],'fresh-api-packages',cwd=root,env=env)
    fingerprint['chromiumTesseract']=p.run([*comp,'exec','-T','runner','sh','-c','tesseract --version; node -e "const {chromium}=require(\'playwright\'); console.log(chromium.executablePath())"'],'fresh-runner-versions',cwd=root,env=env)
    fingerprint['locks']={str(path.relative_to(root)).replace('\\','/'):digest(path) for path in root.glob('apps/*/*lock*') if path.is_file()}
    fingerprint.update(sha=p.SHA,recordedAt=p.now(),imageIds=M['imageIds'],dockerCerts=[path.name for path in (root/'docker/certs').iterdir() if path.is_file()],manifestDigest=digest(MANIFEST))
    p.save('fresh-build-fingerprint.json',fingerprint)
    p.save('fresh-result.json',{'sha':p.SHA,'finishedAt':p.now(),'status':'PASS','schema':revision,'manifestDigest':digest(MANIFEST),'imageArchiveDigest':M['files'][next(n for n in M['files'] if n.endswith('images.tar'))],'d3':'NOT_RUN','project':PROJECT,'root':str(root)})
    print('Fresh installation PASS; stack retained for inspection, no VAHAN calls requested',flush=True)

if __name__=='__main__': main()
