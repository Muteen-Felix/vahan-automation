"""Reuse only the prepared old-version data and empty test daemon, never prior candidate results."""
import json,os,pathlib,subprocess,sys,time
import prepare as p

ORIGIN=pathlib.Path('C:/Users/huyvv12/Desktop/vahan-automation/outputs/release-F-965a9eca42ef-20261016T085232Z')
kind=sys.argv[1];assert kind in ('fresh','upgrade')
filename='clean-engine.json' if kind=='fresh' else 'upgrade-engine.json'
state=json.loads((ORIGIN/filename).read_text(encoding='utf-8'))
old_name=state['containerName'];new_name='vahan-f0a67-'+kind+'-engine-20261016t090229'
info=json.loads(subprocess.check_output(['docker','inspect',old_name],text=True))[0]
assert info['State']['Status']=='exited'
assert subprocess.check_output(['docker','ps','-q'],text=True).strip()=='' or kind=='upgrade'
p.run(['docker','rename',old_name,new_name],kind+'-rename-preparation-daemon')
p.run(['docker','start',new_name],kind+'-resume-preparation-daemon')
engine_env={**os.environ,'DOCKER_HOST':state['dockerHost']}
for key in ('DOCKER_CONTEXT','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'):engine_env.pop(key,None)
deadline=time.monotonic()+90
while True:
    result=subprocess.run(['docker','info','--format','{{json .}}'],env=engine_env,capture_output=True,text=True)
    if result.returncode==0:engine_info=json.loads(result.stdout);break
    assert time.monotonic()<deadline,'Prepared Docker daemon did not restart'
    time.sleep(2)
counts={key:len(subprocess.check_output(['docker',*command],env=engine_env,text=True).split()) for key,command in [('images',['image','ls','-aq']),('containers',['ps','-aq']),('volumes',['volume','ls','-q'])]}
if kind=='fresh':assert not any(counts.values()),'Fresh-install daemon is no longer empty'
else:assert counts['containers']==4 and counts['volumes']==1,'Old-version preparation resources changed'
state.update(sha=p.SHA,containerName=new_name,verifiedAt=p.now(),preparationResourceOrigin=str(ORIGIN/filename),currentStoreCounts=counts,serverVersion=engine_info['ServerVersion'])
p.save(filename,state)
if kind=='upgrade':
    old=json.loads((ORIGIN/'t45b-environment.json').read_text(encoding='utf-8'))
    old.update(sha=p.SHA,reverifiedForCandidateAt=p.now(),preparationOrigin=str(ORIGIN),scope='Reuse of the actual running-old-version dataset, not its old candidate verification results')
    p.save('t45b-environment.json',old)
    identity=json.loads((ORIGIN/'t45b-data-identity.json').read_text(encoding='utf-8'))
    p.save('t45b-data-identity.json',identity)
    p.save('baseline-resource-provenance.json',{'candidateSha':p.SHA,'baselineSha':old['baselineSha'],'recordedAt':p.now(),'root':old['baselineRoot'],'originalDataCreatedAt':identity['createdAt'],'reuse':'Old-version data asset and its identifiers only. All package/upgrade outcomes for this candidate must be executed anew.'})
print(kind,'preparation resources verified for',p.SHA,flush=True)
