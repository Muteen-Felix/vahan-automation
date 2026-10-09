#!/usr/bin/env python3
"""Create/remove a synthetic account only in the isolated SOC staging tenant."""
import json
import os
from pathlib import Path
import secrets
import subprocess
from environment import read_env

ROOT=Path(__file__).resolve().parents[1]


def main():
    values=read_env(ROOT/'.secrets/soc-validation.env')
    if values['VAHAN_TENANT_ID']!='soc-validation':raise RuntimeError('Refusing customer account changes.')
    username='soc-browser-'+secrets.token_hex(6);password=secrets.token_urlsafe(32)
    command=['docker','compose','--env-file',str(ROOT/'.secrets/soc-validation.env'),'exec','-T','api','python','-c']
    create="""import asyncio,json,sys
from app.services import services
from app.db import engine
async def main():
 value=json.load(sys.stdin);await services.users.create(value['username'],value['password'],role='admin');await engine.dispose()
asyncio.run(main())"""
    cleanup="""import asyncio,json,sys
from sqlalchemy import delete
from app.db import engine,schema as db
async def main():
 user=json.load(sys.stdin)['username']
 async with engine.begin() as c:
  await c.execute(delete(db.auth_sessions).where(db.auth_sessions.c.username==user))
  await c.execute(delete(db.user_state).where(db.user_state.c.username==user))
  await c.execute(delete(db.users).where(db.users.c.username==user))
 await engine.dispose()
asyncio.run(main())"""
    subprocess.run([*command,create],input=json.dumps({'username':username,'password':password}),text=True,check=True,capture_output=True)
    try:
        environment=dict(os.environ,SOC_TEST_USER=username,SOC_TEST_PASSWORD=password,
                         SOC_TEST_UI_URL='http://127.0.0.1:18080/')
        subprocess.run(['node','scripts/test-soc-live-ui.mjs'],cwd=ROOT/'apps/web-ui',env=environment,check=True)
    finally:
        subprocess.run([*command,cleanup],input=json.dumps({'username':username}),text=True,check=True,capture_output=True)


if __name__=='__main__':main()
