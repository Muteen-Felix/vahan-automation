"""Bound historic reads without dropping attempts inside a selected session."""
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from app.db import engine, schema as db
from app.main import application
from app.models.job import Job, JobStatus
from app.repositories.postgres import now
from app.services import services


async def test_report_session_pages_preserve_complete_sessions(admin_headers):
    jobs = []
    for index in range(3):
        jobs.append(await services.jobs.create(Job(runnerId='history', ownerUsername='test-admin',
            status=JobStatus.FAILED, scenarioName=f'History {index}', filters={})))
    retry = await services.jobs.create(Job(runnerId='history', ownerUsername='test-admin',
        sessionId=jobs[-1].session_id, retryOfJobId=jobs[-1].id, status=JobStatus.NO_DATA,
        scenarioName=jobs[-1].scenario_name, filters={}))
    async with AsyncClient(transport=ASGITransport(app=application), base_url='http://test', headers=admin_headers) as client:
        first = await client.get('/api/jobs/reports/sessions?limit=2')
        second = await client.get('/api/jobs/reports/sessions?offset=2&limit=2')
        assert first.status_code == second.status_code == 200
        assert len(first.json()) == 2 and len(second.json()) == 1
        assert not ({s['sessionId'] for s in first.json()} & {s['sessionId'] for s in second.json()})
        selected = next(s for s in first.json() if s['sessionId'] == str(retry.session_id))
        assert selected['jobCount'] == 1 and selected['noDataCount'] == 1
        assert selected['jobs'][0]['jobId'] == str(retry.id)
        assert (await client.get('/api/jobs/reports/sessions?limit=21')).status_code == 422
        assert (await client.get('/api/jobs/reports/sessions?offset=-1')).status_code == 422


async def test_historic_file_paging_verification_and_filtered_repository_reads(admin_headers):
    jobs = []
    for index in range(3):
        job = await services.jobs.create(Job(runnerId='history', ownerUsername='test-admin',
            status=JobStatus.COMPLETED, scenarioName=f'Legacy {index}', filters={}))
        jobs.append(job)
        async with engine.begin() as connection:
            await connection.execute(insert(db.stored_files).values(id=str(uuid4()), job_id=str(job.id),
                owner_username='test-admin', kind='excel', name=f'legacy-{index}.xlsx',
                mime_type='application/octet-stream', size=3, sha256='0'*64, content=b'old',
                metadata={}, created_at=now()))
    async with AsyncClient(transport=ASGITransport(app=application), base_url='http://test', headers=admin_headers) as client:
        first = await client.get('/api/jobs/reports?limit=2')
        second = await client.get('/api/jobs/reports?offset=2&limit=2')
        assert len(first.json()) == 2 and len(second.json()) == 1
        assert not ({f['jobId'] for f in first.json()} & {f['jobId'] for f in second.json()})
        assert (await client.get('/api/jobs/reports?limit=1001')).status_code == 422
        matched = await client.post('/api/jobs/reports/verify', json={
            'fileNames':['legacy-0.xlsx','missing.xlsx'], 'sessionIds':{'legacy-0.xlsx':str(jobs[0].session_id)}})
        assert matched.json() == {'files':{'legacy-0.xlsx':3,'missing.xlsx':0}}
        wrong = await client.post('/api/jobs/reports/verify', json={
            'fileNames':['legacy-0.xlsx'], 'sessionIds':{'legacy-0.xlsx':str(jobs[1].session_id)}})
        assert wrong.json() == {'files':{'legacy-0.xlsx':0}}
        assert (await client.get('/api/jobs/reports/file/legacy-0.xlsx')).content == b'old'
    assert len(await services.jobs.list_all('test-admin', session_ids=[str(jobs[0].session_id)])) == 1
    assert await services.jobs.list_all('test-admin', job_ids=[]) == []
    assert await services.jobs.list_all('other-owner', job_ids=[str(jobs[0].id)]) == []
    assert len(await services.files.list('test-admin', names=['legacy-0.xlsx'])) == 1
    assert await services.files.list('test-admin', job_ids=[]) == []
    assert await services.files.list('other-owner', names=['legacy-0.xlsx']) == []
