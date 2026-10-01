from httpx import ASGITransport, AsyncClient

from app.main import application
from app.services import services


async def test_ui_health_schedule_defaults_to_three_days() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/ui-health/schedule")

    assert response.status_code == 200
    body = response.json()
    assert body["intervalDays"] == 3
    assert body["updatedAt"]
    assert body["nextCheckAt"]


async def test_ui_health_schedule_allows_the_loaded_extension_origin() -> None:
    extension_origin = "chrome-extension://ooplajjjjphdcaolokpaenmkjlbcmlhk"
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/ui-health/schedule",
            headers={"Origin": extension_origin},
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == extension_origin


async def test_ui_health_schedule_can_be_updated() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.put(
            "/api/ui-health/schedule",
            json={"intervalDays": 5},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intervalDays"] == 5
    assert body["nextCheckAt"] > body["updatedAt"]


async def test_ui_health_schedule_rejects_invalid_interval() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        too_short = await client.put("/api/ui-health/schedule", json={"intervalDays": 0})
        too_long = await client.put("/api/ui-health/schedule", json={"intervalDays": 366})

    assert too_short.status_code == 422
    assert too_long.status_code == 422


async def test_ui_health_run_now_requires_connected_runner() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/ui-health/run-now", json={})

    assert response.status_code == 409
    assert "runner" in response.json()["detail"].lower()


async def test_ui_health_log_can_be_saved_reviewed_and_downloaded() -> None:
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


async def test_create_job_requires_online_runner() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/jobs",
            json={"runnerId": "missing", "filters": {}},
        )

    assert response.status_code == 404


async def test_create_get_and_cancel_job() -> None:
    await services.runners.register(
        runner_id="runner-local-001",
        name="Test Chrome",
        socket_id="test-socket",
        version="0.1.0",
    )
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
