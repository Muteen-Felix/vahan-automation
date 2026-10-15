from dataclasses import replace
from cryptography.fernet import Fernet
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings


def configured():
    return Settings(environment='production',ui_auth_token_secret='s'*48,
        runner_token='r'*32,browser_state_key=Fernet.generate_key().decode(),
        cors_origins=('https://dashboard.example',),socketio_cors_origins=('https://dashboard.example',))


def test_valid_production_configuration():
    configured().validate_startup()


@pytest.mark.parametrize('field,value',[
    ('ui_auth_token_secret','short'),('runner_token','change-me'),('browser_state_key','bad-key'),
    ('browser_state_key',''),('debug',True),('cors_origins',()),('cors_origins',('*',)),
    ('socketio_cors_origins','*'),('socketio_cors_origins',()),
    ('socketio_cors_origins',('*',)),
    ('environment','produciton'),
])
def test_invalid_production_configuration_fails_before_database_writes(field,value):
    with pytest.raises(RuntimeError):replace(configured(),**{field:value}).validate_startup()


def test_socket_origins_default_to_configured_dashboard_origins(monkeypatch):
    monkeypatch.setenv('VAHAN_API_CORS_ORIGINS','https://dashboard.example,https://backup.example')
    monkeypatch.delenv('VAHAN_API_SOCKETIO_CORS_ORIGINS',raising=False)
    values=Settings.from_env()
    assert values.socketio_cors_origins==values.cors_origins


def test_http_cors_accepts_only_the_production_origin_allowlist():
    import os, subprocess
    program = '''
from fastapi.testclient import TestClient
from app.main import fastapi_app
client = TestClient(fastapi_app)
allowed = client.options('/api/health', headers={
    'Origin':'https://dashboard.example', 'Access-Control-Request-Method':'GET'})
blocked = client.options('/api/health', headers={
    'Origin':'https://evil.example', 'Access-Control-Request-Method':'GET'})
assert allowed.status_code == 200 and allowed.headers.get('access-control-allow-origin') == 'https://dashboard.example'
assert blocked.status_code == 400 and 'access-control-allow-origin' not in blocked.headers
read = client.get('/api/health', headers={'Origin':'https://evil.example'})
assert read.status_code == 200 and 'access-control-allow-origin' not in read.headers
'''
    subprocess.run([sys.executable,'-c',program],cwd=Path(__file__).resolve().parents[1],
        env={**os.environ,'VAHAN_ENVIRONMENT':'production',
             'VAHAN_API_CORS_ORIGINS':'https://dashboard.example',
             'VAHAN_API_SOCKETIO_CORS_ORIGINS':'https://dashboard.example'},
        check=True,capture_output=True,text=True,timeout=30)


@pytest.mark.parametrize('environment,expected', [('production',404),('test',200)])
def test_api_reference_is_not_public_in_production(environment,expected):
    import os, subprocess
    program = '''
import asyncio
from httpx import ASGITransport, AsyncClient
from app.main import application
async def check():
    async with AsyncClient(transport=ASGITransport(app=application),base_url='http://test') as client:
        for path in ['/docs','/redoc','/openapi.json']:
            response=await client.get(path)
            assert response.status_code==EXPECTED,(path,response.status_code)
        assert (await client.get('/')).status_code==200
asyncio.run(check())
'''.replace('EXPECTED',str(expected))
    subprocess.run([sys.executable,'-c',program],cwd=Path(__file__).resolve().parents[1],
        env={**os.environ,'VAHAN_ENVIRONMENT':environment},check=True,capture_output=True,text=True,timeout=30)
