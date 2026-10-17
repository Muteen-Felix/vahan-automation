import json,os,socket,subprocess,time,sys
import prepare as p

def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));return sock.getsockname()[1]

ports=[]
while len(ports)<3:
    port=free_port()
    if port not in ports:ports.append(port)
daemon,web,api=ports
kind=sys.argv[1] if len(sys.argv)>1 else 'fresh'
assert kind in ('fresh','upgrade')
name='vahan-f0a67-'+kind+'-engine-20261016t090229'
ref='docker.io/library/docker:29-dind@sha256:0b6d18a4a222e71c88be6034926b4f6cde2fc33c2218643d03ccfddc65995470'
assert not subprocess.check_output(['docker','ps','-aq','--filter','name=^/'+name+'$'],text=True).strip()
command=['docker','run','-d','--privileged','--name',name,'--memory','3g','--publish',f'127.0.0.1:{daemon}:2375','--publish',f'127.0.0.1:{web}:{web}','--publish',f'127.0.0.1:{api}:{api}','--env','DOCKER_TLS_CERTDIR=','--volume',name+'-data:/var/lib/docker',ref,'--tls=false','--feature','containerd-snapshotter=true']
p.run(command,kind+'-clean-engine-create',timeout=180)
engine_env={**os.environ,'DOCKER_HOST':f'tcp://127.0.0.1:{daemon}'}
for key in ('DOCKER_CONTEXT','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'):engine_env.pop(key,None)
deadline=time.monotonic()+90
while True:
    result=subprocess.run(['docker','info','--format','{{json .}}'],env=engine_env,capture_output=True,text=True)
    if result.returncode==0:
        info=json.loads(result.stdout);break
    assert time.monotonic()<deadline,'Isolated Docker daemon did not start'
    time.sleep(2)
assert info['Containers']==0 and info['Images']==0
state={'sha':p.SHA,'createdAt':p.now(),'containerName':name,'dockerHost':engine_env['DOCKER_HOST'],'webPort':web,'apiPort':api,'toolImage':ref,'serverVersion':info['ServerVersion'],'storageDriver':info['Driver'],'initialContainers':0,'initialImages':0,'initialVolumes':subprocess.check_output(['docker','volume','ls','-q'],env=engine_env,text=True).split(),'scope':'Clean isolated Docker daemon and image/volume store on this Windows host; loopback-only host ports. Not a separate VM.'}
assert not state['initialVolumes']
p.save('clean-engine.json' if kind=='fresh' else 'upgrade-engine.json',state)
print('Clean isolated Docker daemon PASS: zero images, containers and volumes',flush=True)
