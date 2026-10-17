"""Read-only identity gate. Approval values must be supplied explicitly before D3."""
import argparse,hashlib,json,pathlib,subprocess,sys,urllib.request

ROOT=pathlib.Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--expected-sha',required=True)
parser.add_argument('--expected-manifest-digest',required=True)
parser.add_argument('--expected-images-digest',required=True)
args=parser.parse_args()

def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

package=ROOT/'package';manifest_path=next(package.glob('*-manifest.json'))
manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
state=json.loads((ROOT/'staging-environment.json').read_text(encoding='utf-8'))
assert manifest['sourceCommit']==manifest['imageRevision']==state['sha']==args.expected_sha,'SHA mismatch: D3 must not start'
assert digest(manifest_path)==args.expected_manifest_digest,'Manifest digest mismatch: D3 must not start'
images=next(package.glob('*-images.tar'))
assert digest(images)==args.expected_images_digest,'Image archive digest mismatch: D3 must not start'
for line in (package/'SHA256SUMS').read_text(encoding='utf-8').splitlines():
    expected,name=line.split('  ',1);assert digest(package/name)==expected,'Package checksum mismatch: '+name
for name,expected in manifest['files'].items():assert digest(package/name)==expected,'Manifest file mismatch: '+name
ids=subprocess.check_output(['docker','ps','-aq','--filter','label=com.docker.compose.project='+state['project']],text=True).split()
assert ids,'Staging containers are missing'
containers=json.loads(subprocess.check_output(['docker','inspect',*ids],text=True));safe=[]
for container in containers:
    service=container['Config']['Labels']['com.docker.compose.service'];ref=container['Config']['Image']
    assert ref in manifest['imageIds'] and container['Image']==manifest['imageIds'][ref],'Running image mismatch: '+service
    if service=='migrate':assert container['State']['Status']=='exited' and container['State']['ExitCode']==0,'Migration is not successful'
    else:assert container['State'].get('Health',{}).get('Status')=='healthy','Unhealthy staging service: '+service
    safe.append({'service':service,'container':container['Name'],'imageId':container['Image']})
assert len([c for c in safe if c['service']=='runner'])==state['workers'],'Runner count differs from the reviewed staging'
assert {c['service'] for c in safe}=={'postgres','migrate','api','web','runner'},'Unexpected or missing staging services'
for route in ('/api/health','/api/ready'):
    with urllib.request.urlopen(state['baseUrl']+route,timeout=20) as response:
        body=json.load(response);assert response.status==200 and body['status']=='ok','Staging health check failed'
print(json.dumps({'identityGate':'PASS','sha':args.expected_sha,'manifestDigest':args.expected_manifest_digest,'imageArchiveDigest':args.expected_images_digest,'project':state['project'],'baseUrl':state['baseUrl'],'containers':safe,'D3':'NOT_STARTED: identity check only'},indent=2))
