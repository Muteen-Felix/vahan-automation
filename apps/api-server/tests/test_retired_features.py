from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook
from sqlalchemy import func, select

from app.db import engine, schema as db
from app.main import application
from app.models.job import Job, JobStatus
from app.models.report_result import ReportResultRequest
from app.repositories.file_store import PostgresFileStore
from app.repositories.postgres import now
from app.repositories.report_results import commit_report_result
from app.services import services


@pytest.mark.parametrize('legacy', [
    {'updateKind': 'GLOBAL'}, {'updateKind': 'DISCOVER'}, {'updateKind': 'REFRESH'},
    {'updateRunId': '00000000-0000-0000-0000-000000000001'}, {'updateTaskId': 'retired-task'},
    {'update_kind': 'GLOBAL'}, {'update_run_id': '00000000-0000-0000-0000-000000000001'},
])
async def test_maker_update_jobs_cannot_be_created_via_normal_job_endpoint(legacy, admin_headers):
    async with AsyncClient(transport=ASGITransport(app=application), base_url='http://test', headers=admin_headers) as client:
        response = await client.post('/api/jobs', json={'runnerId': 'retired-fixture', 'filters': {}, **legacy})
    assert response.status_code == 422
    assert 'Maker Update has been removed' in response.text
    assert await services.jobs.list_all() == []


@pytest.mark.parametrize('kind', ['GLOBAL', 'DISCOVER', 'REFRESH'])
async def test_legacy_maker_attempt_cannot_mutate_main_report_or_history(kind, admin_token):
    job = await services.jobs.create(Job(runnerId='old-maker-worker', ownerUsername='test-admin',
        updateKind=kind, status=JobStatus.WAITING_RESULT, filters={'states': ['Fixture'], 'rtos': ['Office - TS1']}))
    command = ReportResultRequest(result='NO_RECORD', message='No record found', observedAt=now(),
        pageUrl='https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en')
    with pytest.raises(ValueError, match='Maker Update has been removed'):
        await commit_report_result(job.id, job.runner_id, command)
    workbook = Workbook(); workbook.active.append(['Maker', 'JAN', 'TOTAL']); workbook.active.append(['Fixture', 5, 5])
    data = BytesIO(); workbook.save(data); workbook.close()
    with pytest.raises(ValueError, match='Maker Update has been removed'):
        await PostgresFileStore().commit_excel(job.id, 'old-maker.xlsx', data.getvalue(), runner_id=job.runner_id)
    assert (await services.jobs.get(job.id)).status == JobStatus.WAITING_RESULT
    async with engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(db.report_update_history)) == 0
        assert await connection.scalar(select(func.count()).select_from(db.main_reports)) == 0
