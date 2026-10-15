"""Main-table upload contract: no duplicate report files are produced."""
import asyncio
from dataclasses import replace
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook
from sqlalchemy import func, select

from app.api import excel as excel_api
from app.config import settings
from app.db import engine, schema as db
from app.main import application
from app.models.job import Job, JobStatus
from app.realtime.runner_events import job_status
from app.repositories import file_store
from app.services import services

RUNNER_HEADERS = {"X-VAHAN-RUNNER-ID": "test-runner", "X-VAHAN-RUNNER-TOKEN": settings.runner_token}
FILTERS = {"states": ["Fixture State"], "rtos": ["Office - TS1"], "fromYear": "2025", "toYear": "2025", "yAxis": "Maker"}


def workbook_bytes():
    workbook = Workbook()
    workbook.active.append(["Maker", "JAN", "FEB", "TOTAL"])
    workbook.active.append(["Fixture Maker", 5, 7, 12])
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


async def pending_job():
    job = await services.jobs.create(Job(runnerId="test-runner", ownerUsername="test-admin",
        status=JobStatus.WAITING_RESULT, scenarioName="Fixture report", filters=FILTERS))
    await services.runners.register(runner_id="test-runner", name="Fixture", socket_id="test-socket")
    await services.runners.set_job("test-runner", str(job.id))
    return job


async def upload(client, job_id, content, headers=None, **data):
    return await client.post(f"/api/jobs/{job_id}/main-report", headers=headers or RUNNER_HEADERS,
        files={"file": ("report.xlsx", content, "application/octet-stream")}, data=data)


async def assert_no_commit(job):
    assert (await services.jobs.get(job.id)).main_report_saved_at is None
    async with engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(db.report_update_history)
            .where(db.report_update_history.c.job_id == str(job.id))) == 0


async def test_upload_commits_main_table_and_releases_worker(admin_headers):
    job = await pending_job()
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test", headers=admin_headers) as client:
        response = await upload(client, job.id, workbook_bytes(), observedAt="2025-03-02T08:00:00+07:00")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "COMPLETED"
        result = await client.get(f"/api/jobs/{job.id}/report-result")
        assert result.json()["scope"] == "main-table"
        assert result.json()["states"] == FILTERS["states"]
        annual = await client.get("/api/annual-reports", params={"year": 2025})
        assert annual.json()["rows"][0]["months"][:2] == [5, 7]
        # Legacy downloads describe stored historic files only.
        assert (await client.get(f"/api/jobs/{job.id}/excel")).status_code == 404
        assert (await client.get("/api/jobs/reports")).json() == []
    stored = await services.jobs.get(job.id)
    assert stored.main_report_checksum
    assert stored.excel_file_name is None
    assert (await services.runners.get("test-runner")).current_job_id is None
    async with engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(db.stored_files)) == 0


@pytest.mark.parametrize("content", [b"<html>error</html>", b"", b"PK-not-a-workbook"])
async def test_upload_rejects_invalid_or_empty_file(content):
    job = await pending_job()
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await upload(client, job.id, content)
    assert response.status_code == 400
    await assert_no_commit(job)


async def test_upload_rejects_malformed_workbook_xml():
    job = await pending_job()
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", "<broken")
        archive.writestr("[Content_Types].xml", "<broken")
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await upload(client, job.id, buffer.getvalue())
    assert response.status_code == 400
    await assert_no_commit(job)


async def test_job_cannot_complete_without_saved_main_report():
    job = await pending_job()
    response = await job_status("test-socket", {"jobId": str(job.id), "status": "COMPLETED"})
    assert response["ok"] is False
    assert (await services.jobs.get(job.id)).status == JobStatus.WAITING_RESULT


async def test_raw_no_data_status_cannot_skip_confirmed_result():
    job = await pending_job()
    response = await job_status("test-socket", {"jobId": str(job.id), "status": "NO_DATA"})
    assert response["ok"] is False and "report-result" in response["error"]
    assert (await services.jobs.get(job.id)).status == JobStatus.WAITING_RESULT
    await assert_no_commit(job)


async def test_no_data_commits_context_without_report_copy(admin_headers):
    job = await pending_job()
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test", headers=admin_headers) as client:
        response = await client.post(f"/api/jobs/{job.id}/report-result", headers=RUNNER_HEADERS,
            json={"result": "NO_RECORD", "message": "No record found", "observedAt": "2025-03-02T08:00:00+07:00", "pageUrl": "https://fixture.test/report", "tables": []})
        assert response.status_code == 200, response.text
        stored = await services.jobs.get(job.id)
        assert stored.status == JobStatus.NO_DATA and stored.main_report_saved_at
        assert stored.filters.states == FILTERS["states"] and stored.filters.rtos == FILTERS["rtos"]
        assert stored.no_data_file_name is None
        assert (await client.get(f"/api/jobs/{job.id}/no-data")).status_code == 404
    assert (await services.runners.get("test-runner")).current_job_id is None


async def test_cancelled_job_rejects_late_empty_result_and_upload(admin_headers):
    job = await pending_job()
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test", headers=admin_headers) as client:
        assert (await client.post(f"/api/jobs/{job.id}/cancel")).status_code == 200
        assert (await upload(client, job.id, workbook_bytes())).status_code == 409
    assert (await job_status("test-socket", {"jobId": str(job.id), "status": "NO_DATA"}))["ok"] is False
    await assert_no_commit(job)


async def test_upload_nonexistent_job():
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        assert (await upload(client, uuid4(), workbook_bytes())).status_code == 404


async def test_repeat_and_concurrent_uploads_commit_once(admin_headers):
    job = await pending_job()
    content = workbook_bytes()
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test", headers=admin_headers) as client:
        first, second = await asyncio.gather(upload(client, job.id, content), upload(client, job.id, content))
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        assert (await upload(client, job.id, content)).json() == first.json()
        wrong = {**RUNNER_HEADERS, "X-VAHAN-RUNNER-ID": "another-runner"}
        assert (await upload(client, job.id, content, wrong)).status_code == 403
        next_job = await services.jobs.create(Job(runnerId="test-runner", status=JobStatus.ASSIGNED, filters={}))
        await services.runners.set_job("test-runner", str(next_job.id))
        assert await job_status("test-socket", {"jobId": str(job.id), "status": "COMPLETED"}) == {"ok": True}
        assert (await services.runners.get("test-runner")).current_job_id == str(next_job.id)
    async with engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(db.report_update_history)) == 1


async def test_upload_limit_and_naive_timestamp_reject_before_commit(monkeypatch):
    job = await pending_job()
    content = workbook_bytes()
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        naive = await upload(client, job.id, content, observedAt="2025-03-02T08:00:00")
        assert naive.status_code == 422
        monkeypatch.setattr(excel_api, "settings", replace(settings, max_excel_upload_bytes=1))
        assert (await upload(client, job.id, content)).status_code == 413
    await assert_no_commit(job)


async def test_cancellation_during_workbook_validation_leaves_no_report(monkeypatch):
    job = await pending_job()
    original = file_store.asyncio.to_thread
    async def cancel_during_validation(function, *args):
        result = await original(function, *args)
        if function is file_store.extract_file:
            await services.jobs.transition_status(job.id, JobStatus.CANCELLED)
        return result
    monkeypatch.setattr(file_store.asyncio, "to_thread", cancel_during_validation)
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        assert (await upload(client, job.id, workbook_bytes())).status_code == 409
    await assert_no_commit(job)
