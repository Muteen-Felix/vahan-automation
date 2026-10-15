"""Build an explicitly labelled uncommitted candidate, excluding unrelated changes."""
import hashlib, json, os, subprocess, zipfile
from pathlib import Path

root=Path.cwd()
out=Path(os.environ.get('VAHAN_AUDIT_OUTPUT_DIR',str(root/'diagnostics/round1-5-audit'))).resolve()
out.mkdir(parents=True,exist_ok=True)
package=out/'package'
snapshot=out/'snapshot'
if any(folder.exists() and any(folder.iterdir()) for folder in (package,snapshot)):
    raise SystemExit('Artifacts already exist; set VAHAN_AUDIT_OUTPUT_DIR to a new directory. Nothing was overwritten.')
package.mkdir(exist_ok=True)
snapshot.mkdir(exist_ok=True)
sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
paths=['README.md','compose.yaml','.dockerignore','.gitignore','run-vahan-rpa.ps1',
       'run-vahan-rpa.sh','backup-vahan-rpa.ps1','apps','docker','docs','scripts','tools','test-scenarios-filter.json']
baseline=out/'baseline.zip'
subprocess.run(['git','archive','--format=zip','-o',str(baseline),sha,*paths],check=True)
changed=['apps/api-server/app/repositories/ui_contract.py',
         'apps/api-server/verification/test_ui_contract.py','scripts/test_container_security.py']
with zipfile.ZipFile(baseline) as source:
    contents={entry.filename:source.read(entry.filename) for entry in source.infolist() if not entry.is_dir()}
for name in changed: contents[name]=(root/name).read_bytes()
source_zip=package/'vahan-audit-source.zip'
with zipfile.ZipFile(source_zip,'w',compression=zipfile.ZIP_DEFLATED) as target:
    for name,data in contents.items(): target.writestr(name,data)
with zipfile.ZipFile(source_zip) as source: source.extractall(snapshot)
subprocess.run(['python','scripts/setup-docker.py'],cwd=snapshot,check=True)
namespace,tag='vahan-audit','working-fix'
env={**os.environ,'VAHAN_IMAGE_NAMESPACE':namespace,'VAHAN_IMAGE_TAG':tag}
with (out/'package-build.log').open('wb') as stream:
    subprocess.run(['docker','compose','--env-file','.docker.env','build','--sbom=true','--provenance=mode=max'],
                   cwd=snapshot,env=env,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=1800)
refs=[f'{namespace}/{name}:{tag}' for name in ('postgres','api','web','runner')]
ids={ref:subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',ref],text=True).strip() for ref in refs}
image_tar=package/'vahan-audit-images.tar'
subprocess.run(['docker','image','save','-o',str(image_tar),*refs],check=True)
def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()
manifest={'format':1,'sourceCommit':sha,'imageNamespace':namespace,'imageTag':tag,
          'files':{path.name:digest(path) for path in (source_zip,image_tar)},'imageIds':ids,
          'scope':'Uncommitted candidate: base commit plus exactly the recorded fixes; unrelated dirty UI and outputs excluded.',
          'uncommittedOverrides':{name:digest(root/name) for name in changed}}
(package/'vahan-audit-manifest.json').write_text(json.dumps(manifest,indent=2))
# Isolated, committed UI fixtures must match the packaged UI. Reuse installed dependencies.
for name in ('web-ui','browser-runner'):
    target=snapshot/'apps'/name/'node_modules'
    subprocess.run(['cmd','/c','mklink','/J',str(target),str(root/'apps'/name/'node_modules')],check=True,stdout=subprocess.DEVNULL)
print('Built labelled candidate from',sha,'with',len(changed),'scoped overrides.',flush=True)
with (out/'package-test-console.log').open('wb') as stream:
    result=subprocess.run(['python',str(snapshot/'scripts/test-review-package.py'),'--package-dir',str(package),
                           '--output-dir',str(out/'installed-package')],cwd=root,
                          stdout=stream,stderr=subprocess.STDOUT,timeout=1800)
print('Fresh candidate package exit:',result.returncode,flush=True)
raise SystemExit(result.returncode)
