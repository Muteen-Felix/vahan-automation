#!/usr/bin/env python3
"""Verify live SOC controls only against the dedicated disposable staging tenant."""
import asyncio
from http.cookiejar import CookieJar
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request,build_opener,HTTPCookieProcessor,ProxyHandler
from urllib.error import HTTPError
from environment import read_env


def main():
    env=read_env(Path('.secrets/soc-validation.env'))
    if env['VAHAN_TENANT_ID']!='soc-validation' or env['COMPOSE_PROJECT_NAME']!='vahan-soc-validation':
        raise RuntimeError('Refusing to run synthetic enrollment on a customer tenant.')
    base='http://127.0.0.1:'+env['API_PORT']
    cookies=CookieJar();client=build_opener(ProxyHandler({}),HTTPCookieProcessor(cookies))
    results=[]
    def call(path,body=None,headers=None,client_override=None):
        request=Request(base+path,data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type':'application/json',**(headers or {})})
        try:
            with (client_override or client).open(request,timeout=20) as response:
                return response.status,json.load(response),dict(response.headers)
        except HTTPError as error:
            try:value=json.load(error)
            except ValueError:value={}
            return error.code,value,dict(error.headers)
    status,info,_=call('/api/auth/status');assert status==200 and info['adminMfaRequired']
    status,_,_=call('/docs');assert status==404;results.append('production docs disabled')
    status,_,_=call('/api/ready',headers={'Host':'evil.invalid'});assert status==400;results.append('untrusted host rejected')
    status,_,_=call('/api/auth/status',headers={'Origin':'https://evil.invalid'});assert status==403;results.append('untrusted origin rejected')
    status,login,_=call('/api/auth/login',{'username':env['VAHAN_UI_AUTH_USERNAME'],'password':env['VAHAN_UI_AUTH_PASSWORD'],'browserSession':True})
    assert status==200 and login.get('mfaSetupToken');assert login['accessToken'] is None
    challenge=login['mfaSetupToken']
    status,enrollment,_=call('/api/auth/mfa/enroll',{'challenge':challenge});assert status==200
    import pyotp
    status,session,headers=call('/api/auth/mfa/confirm',{'challenge':challenge,'code':pyotp.TOTP(enrollment['secret']).now()})
    assert status==200 and session['accessToken'] is None
    assert 'HttpOnly' in headers.get('set-cookie',headers.get('Set-Cookie',''))
    results.append('MFA enrollment and HttpOnly session')
    status,_,_=call('/api/auth/activity',{});assert status==403
    csrf={'X-CSRF-Token':session['csrfToken']}
    status,_,_=call('/api/auth/activity',{},csrf);assert status==200;results.append('CSRF enforced')
    anonymous=build_opener(ProxyHandler({}))
    status,_,_=call('/api/runner-state/playwright-1',headers={
        'X-VAHAN-RUNNER-TOKEN':env['VAHAN_RUNNER_TOKEN_1'],'X-VAHAN-RUNNER-ID':'playwright-1'},client_override=anonymous)
    assert status==200
    status,_,_=call('/api/runner-state/playwright-2',headers={
        'X-VAHAN-RUNNER-TOKEN':env['VAHAN_RUNNER_TOKEN_1'],'X-VAHAN-RUNNER-ID':'playwright-2'},client_override=anonymous)
    assert status==401
    status,_,_=call('/api/runner-state/playwright-2',headers={
        'X-VAHAN-RUNNER-TOKEN':env['VAHAN_RUNNER_TOKEN_1'],'X-VAHAN-RUNNER-ID':'playwright-1'},client_override=anonymous)
    assert status==403;results.append('worker credential and state identity isolation')
    command=['docker','compose','--env-file','.secrets/soc-validation.env']
    code="""import asyncio,json,io
from sqlalchemy import text
from app.db import engine
from app.document_client import document
from openpyxl import Workbook
async def main():
 async with engine.connect() as c:
  role=await c.execute(text("SELECT current_user AS name, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls FROM pg_roles WHERE rolname=current_user"));row=dict(role.mappings().one())
  denied=not await c.scalar(text("SELECT has_table_privilege(current_user,'audit_events','DELETE')"))
  tenant=await c.scalar(text('SELECT tenant_id FROM deployment_identity WHERE id=1'))
 w=Workbook();w.active.append(['Maker','Jan']);w.active.append(['TEST',1]);out=io.BytesIO();w.save(out);w.close()
 rows,info=await document('extract',out.getvalue(),'fixture.xlsx')
 assert len(rows)==2
 print(json.dumps({'role':row,'auditDeleteDenied':denied,'tenant':tenant,'isolatedParserRows':len(rows)}))
 await engine.dispose()
asyncio.run(main())"""
    data=json.loads(subprocess.run([*command,'exec','-T','api','python','-c',code],capture_output=True,text=True,check=True).stdout)
    assert data['role']['name']=='vahan_app' and not any(data['role'][k] for k in ['rolsuper','rolcreatedb','rolcreaterole','rolbypassrls'])
    assert data['auditDeleteDenied'] and data['tenant']=='soc-validation'
    results.extend(['runtime database least privilege','immutable audit access','isolated document parsing'])
    status,report,_=call('/api/security/status');assert status==200
    deadline=time.monotonic()+30
    while report['pendingEvents'] and time.monotonic()<deadline:
        time.sleep(1);_,report,_=call('/api/security/status')
    assert report['lastDeliveredEventAt'];results.append('durable events delivered to independent collector')
    output={'checks':results,'passed':True,'database':data}
    path=Path('diagnostics/soc/staged-verification.json');path.write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps({'passed':True,'checks':len(results),'report':str(path)}))


if __name__=='__main__':main()
