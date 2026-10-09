#!/usr/bin/env python3
"""Scan history and current tracked/untracked source without exposing matches."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'diagnostics/soc/secrets')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    if not shutil.which('gitleaks'):raise SystemExit('Install gitleaks before scanning secrets.')
    statuses=[]
    history=args.output/'history.json'
    command=['gitleaks','git',str(ROOT),'--log-opts=--all','--redact','--no-banner','--log-level','error',
             '--gitleaks-ignore-path',str(ROOT/'.gitleaksignore'),'--report-path',str(history)]
    statuses.append(subprocess.run(command,capture_output=True).returncode)
    with tempfile.TemporaryDirectory(prefix='vahan-secret-source-') as temporary:
        source=Path(temporary)
        names=subprocess.run(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT,
                             capture_output=True,check=True).stdout.decode().split('\0')
        for name in set(names):
            if not name:continue
            path=ROOT/name
            if not path.is_file() or path.is_symlink() or path.stat().st_size>5*1024*1024:continue
            if path.suffix.lower() not in {'.py','.ts','.tsx','.mjs','.js','.json','.yaml','.yml','.toml','.md','.sh','.ps1','.ini','.conf','.html','.css','.example'} and path.name not in {'Dockerfile','.gitignore','.dockerignore'}:continue
            target=source/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
        report=args.output/'source.json'
        statuses.append(subprocess.run(['gitleaks','dir',str(source),'--redact','--no-banner','--log-level','error',
                        '--report-path',str(report)],capture_output=True).returncode)
        findings=json.loads(report.read_text()) if report.exists() else []
        summary=[{'file':str(Path(v['File']).relative_to(source)),'line':v['StartLine'],'rule':v['RuleID']} for v in findings]
    print(json.dumps({'historyExit':statuses[0],'sourceExit':statuses[1],'sourceFindings':summary}))
    if any(statuses):raise SystemExit(1)


if __name__=='__main__':main()
