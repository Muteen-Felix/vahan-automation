"""Real authenticated worker HTTP claims against an isolated SQL queue."""
import asyncio
from uuid import uuid4
from httpx import ASGITransport, AsyncClient

from app.api.batch_queue import QueueTaskInput
from app.config import settings
from app.main import application
from app.repositories.batch_queue import BatchQueueRepository
from app.repositories.ui_contract import bind_gate
from app.services import services
from app.worker_pool import apply_pool


def worker_headers(runner_id):
    return {'X-VAHAN-RUNNER-TOKEN':settings.runner_token,'X-VAHAN-RUNNER-ID':runner_id}


async def queue_fixture():
    session=uuid4()
    workers=[f'worker-{uuid4()}' for _ in range(4)]
    for worker in workers:
        await services.runners.register(runner_id=worker,name='Fixture',socket_id=worker)
    await apply_pool(2)
    await BatchQueueRepository().start(session,'test-admin',[
        QueueTaskInput(name=f'Office {i}',filters={'states':['State'],'rtos':[f'Office {i}']}) for i in range(12)],2)
    return session,workers


async def test_worker_claim_requires_bound_sql_preflight(admin_headers):
    session,workers=await queue_fixture()
    async with AsyncClient(transport=ASGITransport(app=application),base_url='http://test') as client:
        response=await client.post('/api/runner/queue/claim',headers=worker_headers(workers[0]),json={'sessionId':str(session)})
        assert response.status_code==200 and response.json()['type']=='gate_required'
    assert not await services.jobs.list_all()


async def test_parallel_http_claims_obey_capacity_and_recover_lost_response(admin_headers,approve_workers):
    session,workers=await queue_fixture()
    await bind_gate(session,await approve_workers(workers))
    async with AsyncClient(transport=ASGITransport(app=application),base_url='http://test') as client:
        responses=await asyncio.gather(*(client.post('/api/runner/queue/claim',headers=worker_headers(worker),json={'sessionId':str(session)}) for worker in workers))
        assert all(response.status_code==200 for response in responses)
        assigned=[(worker,response.json()) for worker,response in zip(workers,responses) if response.json()['type']=='assigned']
        assert len(assigned)==2 and len({item['jobId'] for _,item in assigned})==2
        worker,first=assigned[0]
        recovered=await client.post('/api/runner/queue/claim',headers=worker_headers(worker),json={'sessionId':str(session)})
        assert recovered.json()['recovered'] is True
        assert recovered.json()['jobId']==first['jobId']
    assert len(await services.jobs.list_all())==2


async def test_worker_claim_cannot_use_dashboard_auth_or_omit_identity(admin_headers):
    async with AsyncClient(transport=ASGITransport(app=application),base_url='http://test') as client:
        assert (await client.post('/api/runner/queue/claim',headers=admin_headers)).status_code==401
        assert (await client.post('/api/runner/queue/claim',headers={'X-VAHAN-RUNNER-TOKEN':settings.runner_token})).status_code==401
