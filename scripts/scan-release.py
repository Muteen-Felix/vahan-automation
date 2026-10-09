#!/usr/bin/env python3
"""Offline local vulnerability scan of release images; no source upload."""
import argparse
import json
from pathlib import Path
import subprocess
from environment import read_env

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,default=ROOT/'.docker.env')
    parser.add_argument('--roles',nargs='+',default=['api','web','runner','postgres','backup'])
    parser.add_argument('--sbom',action='store_true')
    args=parser.parse_args();values=read_env(args.env_file)
    output=ROOT/'diagnostics/security/scans';output.mkdir(parents=True,exist_ok=True)
    summaries=[]
    for role in args.roles:
        if role not in {'api','web','runner','postgres','backup'}:raise ValueError('Unknown image role.')
        image=f"{values['VAHAN_IMAGE_NAMESPACE']}/{role}:{values['VAHAN_IMAGE_TAG']}"
        report=output/f'{role}.json'
        subprocess.run(['trivy','image','--scanners','vuln','--image-src','docker','--offline-scan',
            '--skip-db-update','--parallel','2','--cache-dir',str(ROOT/'diagnostics/security/trivy-cache'),
            '--format','json','--output',str(report),image],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        data=json.loads(report.read_text());findings=[v for r in data.get('Results',[]) for v in r.get('Vulnerabilities',[]) or []]
        summary={'role':role,'instances':{level:sum(v['Severity']==level for v in findings)
            for level in ['CRITICAL','HIGH','MEDIUM','LOW','UNKNOWN']},
            'fixableHighCritical':sum(v['Severity'] in {'HIGH','CRITICAL'} and bool(v.get('FixedVersion')) for v in findings)}
        summaries.append(summary);print(json.dumps(summary),flush=True)
        if args.sbom:
            subprocess.run(['trivy','image','--scanners','vuln','--image-src','docker','--offline-scan',
                '--skip-db-update','--parallel','2','--cache-dir',str(ROOT/'diagnostics/security/trivy-cache'),
                '--format','cyclonedx','--output',str(output/f'{role}.cdx.json'),image],
                check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    (output/'summary.json').write_text(json.dumps(summaries,indent=2)+'\n')


if __name__=='__main__':main()
