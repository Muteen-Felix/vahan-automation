import ctypes,json,os,pathlib,subprocess,sys,time
import prepare as p
import fresh as f

def host_memory():
    class Memory(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(key,ctypes.c_ulonglong) for key in ('total','available','totalPage','availablePage','totalVirtual','availableVirtual','extended')]
    value=Memory();value.length=ctypes.sizeof(value)
    assert ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value))
    return {'totalBytes':value.total,'availableBytes':value.available}

def main():
    result=json.loads((p.ROOT/'t45b-result.json').read_text(encoding='utf-8'));assert result['status']=='PASS'
    state=json.loads((p.ROOT/'t45b-environment.json').read_text(encoding='utf-8'))
    engine=json.loads((p.ROOT/'upgrade-engine.json').read_text(encoding='utf-8'))
    root=pathlib.Path(state['upgradedRoot']);env={**os.environ,'DOCKER_HOST':engine['dockerHost'],'COMPOSE_PROJECT_NAME':state['project']}
    values=f.values_at(root)
    p.REDACTIONS.extend(value for key,value in values.items() if any(t in key for t in ('PASSWORD','TOKEN','SECRET','STATE_KEY')))
    c=['docker','compose','--env-file','.docker.env','-p',state['project']]
    p.run([sys.executable,'scripts/run-docker.py','--check-release'],'t45b-final-release-guard',cwd=root,env=env)
    p.run([*c,'stop'],'t45b-retain-stopped-stack',cwd=root,env=env)
    p.run(['docker','stop',engine['containerName']],'upgrade-test-daemon-stop')
    running=subprocess.check_output(['docker','ps','-q'],text=True).split()
    assert not running,'Unexpected running containers; do not restart shared Docker Desktop'
    before=host_memory();restarted=False
    if before['availableBytes']<int(5*1024**3):
        p.run(['docker','desktop','restart','--timeout','180'],'docker-headroom-restart',timeout=210)
        deadline=time.monotonic()+90
        while True:
            probe=subprocess.run(['docker','info','--format','{{.ServerVersion}}'],capture_output=True,text=True)
            if probe.returncode==0:break
            assert time.monotonic()<deadline,'Docker Desktop did not become ready'
            time.sleep(2)
        restarted=True
    after=host_memory()
    p.save('staging-host-headroom.json',{'sha':p.SHA,'checkedAt':p.now(),'before':before,'after':after,'dockerDesktopRestartedWithZeroRunningContainers':restarted,'plannedWorkers':3})
    assert after['availableBytes']>=int(4.8*1024**3),'Insufficient measured host headroom for three staging runners'
    install_staging()

def install_staging():
    memory=host_memory()
    assert memory['availableBytes']>=int(4.8*1024**3),'Host memory has not reclaimed enough headroom yet'
    p.save('staging-host-headroom-recheck.json',{'sha':p.SHA,'checkedAt':p.now(),'status':'PASS','memory':memory,'plannedWorkers':3,'note':'Rechecked after asynchronous Docker/WSL memory reclamation settled; no source or package change.'})
    stage_env=os.environ.copy()
    local_config=pathlib.Path('C:/Users/huyvv12/Desktop/vahan-automation/.docker.env')
    existing={}
    if local_config.is_file():
        existing=dict(line.split('=',1) for line in local_config.read_text().splitlines() if '=' in line and not line.startswith('#'))
    password=existing.get('VAHAN_UI_AUTH_PASSWORD','').strip().strip('"\'')
    if len(password)>=12:
        stage_env['VAHAN_STAGING_ADMIN_PASSWORD']=password;p.REDACTIONS.append(password)
    p.save('staging-credential-policy.json',{'sha':p.SHA,'checkedAt':p.now(),'username':'admin','passwordSource':'Existing protected local configuration' if len(password)>=12 else 'New generated staging credential in the protected configuration','credentialValuesAndHashesWithheld':True})
    p.run([sys.executable,str(p.ROOT/'staging.py')],'staging-install-driver',env=stage_env,timeout=600)
    p.run([sys.executable,str(p.ROOT/'staging-network.py')],'staging-navigation-driver',timeout=360)
    manifest_digest=f.digest(f.MANIFEST)
    images_digest=f.M['files'][next(name for name in f.M['files'] if name.endswith('images.tar'))]
    p.run([sys.executable,str(p.ROOT/'d3-package-gate.py'),'--expected-sha',p.SHA,'--expected-manifest-digest',manifest_digest,'--expected-images-digest',images_digest],'staging-identity-gate',timeout=150)
    print('Staging is ready for final package review; D3 NOT_RUN',flush=True)

if __name__=='__main__':
    install_staging() if sys.argv[1:]==['--resume-install'] else main()
