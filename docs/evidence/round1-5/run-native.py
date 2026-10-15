import json, os, subprocess, sys
from pathlib import Path

root=Path.cwd()
out=root/'diagnostics/round1-5-audit'
results=[]
env={**os.environ,'UI_TEST_ARTIFACT_DIR':str(out/'screenshots')}
commands=[]
commands.append(('docs',['python','scripts/check-doc-links.py'],root))
for name in ('test_ocr_platform.py','test_captcha_ephemeral.py','test_captcha_refresh_race.py','test_production_config.py'):
    commands.append((name,['python','-m','pytest','verification/'+name,'-v'],root/'apps/api-server'))
for name in ('test_deployment_guard.py','test_worker_capacity.py','test_container_scan.py'):
    commands.append((name,['python','-m','unittest','discover','-s','scripts','-p',name],root))
commands.append(('ui-diagnostics',['python','tools/ui-drift-guard/test_ui_diagnostics.py'],root))
for file in sorted((root/'apps/browser-runner').glob('test-*.mjs')):
    if file.name=='test-container-runtime.mjs': continue
    commands.append((file.name,['node',file.name],file.parent))
for action in ('check','build','test:platform'):
    commands.append(('web-'+action.replace(':','-'),['npm.cmd','run',action],root/'apps/web-ui'))
for label,command,cwd in commands:
    with (out/(label+'.log')).open('wb') as stream:
        try:
            result=subprocess.run(command,cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=1200)
            code=result.returncode
        except Exception as error:
            stream.write(str(error).encode());code=1
    results.append({'fileOrSuite':label,'command':command,'exitCode':code})
    print(label,'PASS' if code==0 else 'FAIL',flush=True)
    (out/'native-results.json').write_text(json.dumps(results,indent=2))
sys.exit(int(any(row['exitCode'] for row in results)))
