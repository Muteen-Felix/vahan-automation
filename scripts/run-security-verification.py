#!/usr/bin/env python3
"""Run security regression suites against an isolated temporary PostgreSQL server."""
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    python=ROOT/('apps/api-server/.venv/Scripts/python.exe' if os.name=='nt'
                 else 'apps/api-server/.venv/bin/python')
    if not python.exists(): python=Path(sys.executable)
    container='vahan-security-verification-'+secrets.token_hex(6)
    password=secrets.token_hex(24)
    environment=dict(os.environ);environment['POSTGRES_PASSWORD']=password
    try:
        subprocess.run(['docker','run','-d','--name',container,'--memory','768m','--cpus','1',
            '--pids-limit','128','--label','com.vahan.security.test=true','-p','127.0.0.1::5432',
            '--env','POSTGRES_PASSWORD','--env','POSTGRES_USER=vahan','--env','POSTGRES_DB=vahan_security_test',
            'postgres:17.7-bookworm'],env=environment,check=True,capture_output=True)
        for _ in range(60):
            ready=subprocess.run(['docker','exec',container,'pg_isready','-U','vahan'],capture_output=True)
            main=subprocess.run(['docker','exec',container,'cat','/proc/1/comm'],capture_output=True,text=True)
            if not ready.returncode and main.stdout.strip()=='postgres':break
            time.sleep(1)
        else:raise RuntimeError('Disposable verification database is unavailable.')
        port=subprocess.run(['docker','port',container,'5432/tcp'],capture_output=True,text=True,check=True).stdout.strip().rsplit(':',1)[-1]
        tests=[('vahan_security_test','verification/test_security_integration.py',{}),
               ('vahan_session_security_test','verification/test_session_limits.py',{'VAHAN_SESSION_TEST_DATABASE':'vahan_session_security_test'}),
               ('vahan_remove_soc_test','verification/test_remove_soc.py',{})]
        for database,suite,extra in tests:
            if database!='vahan_security_test':
                subprocess.run(['docker','exec',container,'psql','-U','vahan','-d','vahan_security_test','-c',
                    f'CREATE DATABASE {database}'],check=True,capture_output=True)
            env=dict(os.environ)
            env.update({'DATABASE_URL':f'postgresql+asyncpg://vahan:{password}@127.0.0.1:{port}/{database}',
                'VAHAN_UI_AUTH_TOKEN_SECRET':'isolated-regression-signing-key-'+'s'*48,
                'VAHAN_API_RUNNER_TOKEN':'isolated-regression-worker-'+'r'*40,
                'VAHAN_ALLOW_DATABASE_CLEAR':'test-only', **extra})
            for key in ['VAHAN_PRODUCTION','VAHAN_RUNNER_TOKENS','VAHAN_REQUIRE_ADMIN_MFA','VAHAN_TENANT_ID']:
                env.pop(key,None)
            subprocess.run([str(python),'-m','pytest',suite,'-q'],cwd=ROOT/'apps/api-server',env=env,check=True)
        print('Isolated security, session and schema removal verification passed.')
    finally:
        subprocess.run(['docker','rm','-f','-v',container],capture_output=True)


if __name__=='__main__':main()
