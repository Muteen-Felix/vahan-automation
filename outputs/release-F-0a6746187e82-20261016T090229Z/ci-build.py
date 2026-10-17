import json,os,subprocess,sys,time,urllib.request
import prepare as p

url=f'https://api.github.com/repos/Muteen-Felix/vahan-automation/commits/{p.SHA}/check-runs'
snapshots=[]
while True:
    with urllib.request.urlopen(urllib.request.Request(url,headers={'Accept':'application/vnd.github+json','User-Agent':'vahan-release-verification'}),timeout=30) as response:
        data=json.load(response)
    checks=data['check_runs']
    assert all(c['head_sha']==p.SHA for c in checks)
    snapshot={'checkedAt':p.now(),'checks':[{k:c.get(k) for k in ('name','head_sha','status','conclusion','html_url','started_at','completed_at')} for c in checks]}
    snapshots.append(snapshot);p.save('ci-observations.json',snapshots)
    completed=[c for c in checks if c['status']=='completed']
    print(f'CI {len(completed)}/6 completed; {sum(c["conclusion"]=="success" for c in completed)}/6 success',flush=True)
    failed=[c for c in completed if c['conclusion']!='success']
    if failed:
        p.save('ci-failure.json',{'sha':p.SHA,'checkedAt':p.now(),'failures':failed})
        raise SystemExit('Exact-SHA CI failed; package build has not started.')
    if len(checks)==6 and len(completed)==6:
        p.save('ci-checks.json',{'verifiedAt':p.now(),'sha':p.SHA,'endpoint':url,'response':data})
        break
    time.sleep(30)

assert p.run(['git','status','--porcelain=v1','--untracked-files=all'],'worktree-clean')==''
assert p.run(['git','rev-parse','HEAD'],'worktree-head')==p.SHA
assert p.run(['git','rev-parse','origin/release/pre-go-live'],'remote-head')==p.SHA
p.run(['git','ls-remote','origin','refs/heads/release/pre-go-live'],'remote-push-proof')
for args,label in [(['docker','image','ls','--format','{{json .}}'],'docker-images-before'),(['docker','volume','ls','--format','{{json .}}'],'docker-volumes-before'),(['docker','ps','-a','--format','{{json .}}'],'docker-containers-before')]:
    p.run(args,label)
p.run([sys.executable,'scripts/setup-docker.py'],'worktree-setup')
p.run([sys.executable,'scripts/run-docker.py','--assess-only'],'resources')
p.run([sys.executable,'scripts/build-review-package.py','--ref',p.SHA,'--with-images','--output-dir',str(p.ROOT/'package')],'package-build',timeout=3600)
