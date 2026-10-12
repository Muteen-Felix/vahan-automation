from unittest.mock import AsyncMock
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.db import engine, schema as db
from app.main import application
from app.services import services
from app.worker_pool import apply_pool


async def test_parallel_limit_is_not_reported_as_runner_disconnect(admin_headers, monkeypatch):
    monkeypatch.setattr('app.repositories.ui_contract.require_gate', AsyncMock(return_value='fixture'))
    await apply_pool(1)
    for runner in ('capacity-a','capacity-b'):
        await services.runners.register(runner_id=runner,name=runner,socket_id=runner)
    async with AsyncClient(transport=ASGITransport(app=application),base_url='http://test',headers=admin_headers) as client:
        first=await client.post('/api/jobs',json={'runnerId':'capacity-a','filters':{}})
        assert first.status_code==201, first.text
        limited=await client.post('/api/jobs',json={'runnerId':'capacity-b','filters':{}})
        assert limited.status_code==409
        assert 'PARALLEL_LIMIT_REACHED' in limited.json()['detail']
        assert 'disconnected' not in limited.json()['detail'].lower()
        busy=await client.post('/api/jobs',json={'runnerId':'capacity-a','filters':{}})
        assert busy.status_code==409 and 'already processing' in busy.json()['detail']
        missing=await client.post('/api/jobs',json={'runnerId':'missing','filters':{}})
        assert missing.status_code==404 and 'offline' in missing.json()['detail']
    async with engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(db.jobs))==1
