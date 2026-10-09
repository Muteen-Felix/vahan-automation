#!/usr/bin/env python3
"""Create an isolated tenant configuration; never reuse a customer's database."""
import argparse
from pathlib import Path
import subprocess
import sys
from security_setup import ROOT, provision
from environment import read_env


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tenant',required=True)
    parser.add_argument('--api-port',required=True,type=int)
    parser.add_argument('--web-port',required=True,type=int)
    parser.add_argument('--public-origin')
    parser.add_argument('--up',action='store_true')
    args=parser.parse_args()
    if args.tenant=='legacy':raise SystemExit('The legacy tenant is reserved for the existing deployment.')
    if args.api_port==args.web_port or not all(1024<=p<=65535 for p in [args.api_port,args.web_port]):
        raise SystemExit('Use two different unprivileged ports.')
    # Validate tenant before composing a path, preventing traversal.
    import re
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}',args.tenant):raise SystemExit('Invalid tenant ID.')
    target=ROOT/'tenants'/args.tenant/'.env'
    configs=[ROOT/'.docker.env',*ROOT.glob('tenants/*/.env')]
    for config in configs:
        if not config.exists() or config==target:continue
        values=read_env(config)
        if {str(args.api_port),str(args.web_port)} & {values.get('API_PORT'),values.get('WEB_PORT')}:
            raise SystemExit('A port is already assigned to another tenant.')
        if args.public_origin and values.get('VAHAN_PUBLIC_ORIGIN')==args.public_origin.rstrip('/'):
            raise SystemExit('A public origin is already assigned to another tenant.')
    provision(target,args.tenant,str(args.api_port),str(args.web_port),args.public_origin)
    print('Tenant credentials remain in its protected environment file.')
    if args.up:
        subprocess.run([sys.executable,str(ROOT/'scripts/run-docker.py'),'--env-file',str(target),
                        '--tenant',args.tenant],cwd=ROOT,check=True)


if __name__=='__main__':main()
