from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4
from app.models.job import Job

import pytest
from sqlalchemy import select
from sqlalchemy import text

from httpx import ASGITransport, AsyncClient

from app.main import application, fastapi_app
from app.models.ui_health import UiHealthSchedule
from app.db import engine, schema as db
from app.repositories.postgres import PostgresStateStore
from app.services import services


async def test_job_history_is_paginated(admin_headers):
    for index in range(105):
        await services.jobs.create(Job(runnerId='fixture',ownerUsername='test-admin',scenarioName=f'Case {index}',filters={}))
    async with AsyncClient(transport=ASGITransport(app=application),base_url='http://test',headers=admin_headers) as client:
        first=await client.get('/api/jobs')
        second=await client.get('/api/jobs?offset=100&limit=100')
        assert first.status_code==second.status_code==200
        assert len(first.json())==100 and len(second.json())==5
        assert not ({job['id'] for job in first.json()} & {job['id'] for job in second.json()})
        assert (await client.get('/api/jobs?limit=1001')).status_code==422
        assert (await client.get('/api/jobs?offset=-1')).status_code==422


async def test_readiness_requires_current_migration():
    async with engine.connect() as connection:
        original=await connection.scalar(text('SELECT version_num FROM alembic_version'))
    async with AsyncClient(transport=ASGITransport(app=application),base_url='http://test') as client:
        assert (await client.get('/api/ready')).status_code==200
        try:
            async with engine.begin() as connection:
                await connection.execute(text("UPDATE alembic_version SET version_num='old_revision'"))
            stale=await client.get('/api/ready')
            assert stale.status_code==503 and 'migration' in stale.json()['detail']
        finally:
            async with engine.begin() as connection:
                await connection.execute(text('UPDATE alembic_version SET version_num=:revision'),{'revision':original})
        assert (await client.get('/api/ready')).status_code==200


def test_removed_methods_are_absent_and_legacy_read_remains() -> None:
    paths = fastapi_app.openapi()["paths"]

    assert "get" in paths["/api/ui-health/schedule"]
    assert "put" not in paths["/api/ui-health/schedule"]
    assert "/api/jobs/{job_id}/upload-excel" not in paths
    assert "post" in paths["/api/ui-health/run-now"]
    assert "post" in paths["/api/jobs/{job_id}/main-report"]


async def test_ui_health_schedule_remains_readable(admin_headers) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
        headers=admin_headers,
    ) as client:
        response = await client.get(
            "/api/ui-health/schedule",
            headers=admin_headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intervalDays"] == 3
    assert datetime.fromisoformat(body["nextCheckAt"]) - datetime.fromisoformat(body["updatedAt"]) == timedelta(days=3)
    assert body["updatedAt"]
    assert body["nextCheckAt"] > body["updatedAt"]
    async with engine.connect() as connection:
        assert await connection.scalar(select(db.app_settings.c.value)
            .where(db.app_settings.c.key == "ui-health-schedule")) is None


async def test_legacy_schedule_returns_saved_value_without_modifying_it(admin_headers):
    schedule = UiHealthSchedule(intervalDays=7, updatedAt="2026-10-01T00:00:00Z", nextCheckAt="2026-10-08T00:00:00Z")
    stored = schedule.model_dump(mode="json", by_alias=True)
    await PostgresStateStore().put("ui-health-schedule", stored)
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test", headers=admin_headers) as client:
        first = await client.get("/api/ui-health/schedule")
        second = await client.get("/api/ui-health/schedule")
        removed = await client.put("/api/ui-health/schedule", json={"intervalDays": 5})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == stored
    assert removed.status_code == 405
    assert await PostgresStateStore().get("ui-health-schedule") == stored


@pytest.mark.parametrize("role,status", [(None,401),("user",403),("admin",202)])
async def test_run_now_enforces_admin_and_preserves_runner_routing(role,status,admin_headers,monkeypatch):
    await services.runners.register(runner_id="manual-runner", name="Manual", socket_id="manual-socket")
    emit = AsyncMock()
    monkeypatch.setattr("app.api.ui_health.sio.emit", emit)
    if role == "user":
        monkeypatch.setattr("app.main.authenticate_access_token", AsyncMock(return_value={
            "username":"member", "role":"user", "session_id":"fixture"}))
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post("/api/ui-health/run-now", json={}, headers=admin_headers if role else {})
    assert response.status_code == status
    if role == "admin":
        assert response.json()["runnerId"] == "manual-runner"
        assert emit.await_args.kwargs["room"] == "runner:manual-runner"
        assert emit.await_args.args[1]["requestId"] == response.json()["requestId"]
    else:
        emit.assert_not_awaited()


async def test_run_now_missing_reconnecting_and_busy_workers(admin_headers,monkeypatch):
    await services.runners.register(runner_id="manual-runner", name="Manual", socket_id="manual-socket")
    monkeypatch.setattr("app.api.ui_health.sio.emit", AsyncMock())
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test", headers=admin_headers) as client:
        assert (await client.post("/api/ui-health/run-now", json={"runnerId":"missing"})).status_code == 404
        await services.runners.mark_reconnecting("manual-socket")
        assert (await client.post("/api/ui-health/run-now", json={"runnerId":"manual-runner"})).status_code == 409
        await services.runners.heartbeat("manual-socket")
        # Manual checks use an isolated browser context and may inspect a busy worker.
        await services.jobs.create(Job(
            id=uuid4(), runnerId="manual-runner", filters={}))
        jobs=await services.jobs.list_all()
        await services.runners.set_job("manual-runner",str(jobs[0].id))
        assert (await client.post("/api/ui-health/run-now", json={"runnerId":"manual-runner"})).status_code == 202


async def test_removed_upload_alias_is_unavailable_to_admin_and_runner(admin_headers):
    from app.config import settings
    async with AsyncClient(transport=ASGITransport(app=application),base_url="http://test") as client:
        path=f"/api/jobs/{uuid4()}/upload-excel"
        assert (await client.post(path,headers=admin_headers)).status_code == 404
        assert (await client.post(path,headers={"X-VAHAN-RUNNER-TOKEN":settings.runner_token})).status_code == 401


async def test_ui_health_run_now_requires_connected_runner(admin_headers) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
        headers=admin_headers,
    ) as client:
        response = await client.post(
            "/api/ui-health/run-now",
            json={},
            headers=admin_headers,
        )

    assert response.status_code == 409
    assert "runner" in response.json()["detail"].lower()


async def test_ui_health_log_can_be_saved_reviewed_and_downloaded(admin_headers) -> None:
    payload = {
        "healthCheck": {
            "status": "UI_DRIFT",
            "trigger": "alarm",
            "startedAt": "2026-09-17T08:00:00.000Z",
            "checkedAt": "2026-09-17T08:00:01.200Z",
            "contract": {
                "contractVersion": "v1",
                "signature": "signature-a",
                "path": "/analytics/vahanpublicreport",
                "controls": [],
            },
            "report": {
                "code": "UI_DRIFT_REQUIRED_CONTROL",
                "title": "Control bắt buộc bị thiếu",
                "step": "scheduled-health-check",
                "target": "Fuel",
                "expected": "Fuel tồn tại",
                "actual": "Fuel bị thiếu",
                "diagnostics": {"selector": "#vehicleFuel"},
                "action": "Kiểm tra adapter",
            },
        },
        "pageUrl": "https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en",
    }

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
        headers=admin_headers,
    ) as client:
        saved = await client.post("/api/ui-health/logs", json=payload)
        assert saved.status_code == 201
        saved_body = saved.json()
        assert saved_body["fileName"] == "report-2026-09-17-to-2026-09-17.csv"

        reviewed = await client.get("/api/ui-health/reports", params={"date": "2026-09-17"})
        downloaded = await client.get(
            f"/api/ui-health/reports/{saved_body['fileName']}/download"
        )

    assert reviewed.status_code == 200
    reviewed_body = reviewed.json()
    assert reviewed_body["selectedDate"] == "2026-09-17"
    assert reviewed_body["availableDates"][0]["uiDrift"] == 1
    assert reviewed_body["rows"][0]["error_code"] == "UI_DRIFT_REQUIRED_CONTROL"
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("text/csv")
    assert downloaded.content.startswith(b"\xef\xbb\xbf")


async def test_health() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_create_job_requires_online_runner(admin_headers) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
        headers=admin_headers,
    ) as client:
        response = await client.post(
            "/api/jobs",
            json={"runnerId": "missing", "filters": {}},
        )

    assert response.status_code == 404


async def test_create_get_and_cancel_job(admin_headers, approve_workers) -> None:
    await services.runners.register(
        runner_id="runner-local-001",
        name="Test Chrome",
        socket_id="test-socket",
        version="0.1.0",
    )
    await approve_workers(["runner-local-001"])
    payload = {
        "runnerId": "runner-local-001",
        "filters": {
            "states": ["Delhi"],
            "categoryGroups": ["Two Wheeler"],
            "autoApply": False,
            "autoExport": True,
        },
    }

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
        headers=admin_headers,
    ) as client:
        created = await client.post("/api/jobs", json=payload)
        assert created.status_code == 201
        body = created.json()
        assert body["status"] == "ASSIGNED"
        assert body["filters"]["categoryGroups"] == ["Two Wheeler"]

        fetched = await client.get(f"/api/jobs/{body['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["id"] == body["id"]

        cancelled = await client.post(f"/api/jobs/{body['id']}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "CANCELLED"

    runner = await services.runners.get("runner-local-001")
    assert runner is not None
    assert runner.current_job_id is None
