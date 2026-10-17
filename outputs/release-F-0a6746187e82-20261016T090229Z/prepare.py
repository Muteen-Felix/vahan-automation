import datetime, hashlib, json, os, pathlib, subprocess, sys, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
TREE = pathlib.Path('C:/Users/huyvv12/AppData/Local/Temp/vahan-release-F-clean-20261016T090229Z')
SHA = '0a6746187e820efd23e2e8e96f37eb3aa1efcba6'
REDACTIONS=[]

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def save(name, data):
    (ROOT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

def run(args, name, cwd=TREE, timeout=1800, env=None, input=None):
    start=now()
    proc=subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, env=env, input=input)
    output=proc.stdout+'\n'+proc.stderr
    for value in REDACTIONS:
        if value: output=output.replace(value,'[redacted]')
    (ROOT / (name + '.log')).write_text(output, encoding='utf-8')
    record={'command':[next(('[redacted]' if secret and secret in str(arg) else str(arg) for secret in REDACTIONS if secret and secret in str(arg)),str(arg)) for arg in args], 'cwd':str(cwd), 'startedAt':start, 'finishedAt':now(), 'exitCode':proc.returncode, 'log':name+'.log', 'sha':SHA}
    save(name+'.json', record)
    print(name, 'PASS' if proc.returncode==0 else 'FAIL', flush=True)
    if proc.returncode:
        raise SystemExit(proc.returncode)
    return proc.stdout.strip()

