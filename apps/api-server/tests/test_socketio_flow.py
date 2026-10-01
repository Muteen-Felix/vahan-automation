import asyncio
import socket
from collections.abc import AsyncIterator

import pytest_asyncio
import socketio
import uvicorn
from httpx import AsyncClient

from app.config import settings
from app.main import application


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest_asyncio.fixture
async def live_server_url() -> AsyncIterator[str]:
    port = _free_port()
    config = uvicorn.Config(
        application,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.02)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)


async def test_runner_job_and_captcha_round_trip(live_server_url: str) -> None:
    runner = socketio.AsyncClient()
    ui = socketio.AsyncClient()
    assigned = asyncio.Event()
    captcha_visible = asyncio.Event()
    captcha_forwarded = asyncio.Event()
    captcha_refresh_forwarded = asyncio.Event()
    captcha_invalid_visible = asyncio.Event()
    captcha_refreshed_visible = asyncio.Event()
    captcha_failed_visible = asyncio.Event()
    assigned_payload: dict = {}
    failed_payload: dict = {}

    @runner.on("job:assigned", namespace="/runner")
    async def on_assigned(payload: dict) -> None:
        assigned_payload.update(payload)
        assigned.set()

    @ui.on("captcha:required", namespace="/ui")
    async def on_captcha(_payload: dict) -> None:
        captcha_visible.set()

    @runner.on("captcha:submit", namespace="/runner")
    async def on_captcha_submitted(_payload: dict) -> None:
        captcha_forwarded.set()
        return {"ok": True}

    @runner.on("captcha:refresh", namespace="/runner")
    async def on_captcha_refresh(payload: dict) -> dict:
        assert payload["captchaId"] == "captcha-sequence-refreshed"
        captcha_refresh_forwarded.set()
        acknowledgement = await runner.call(
            "captcha:refreshed",
            {
                "jobId": payload["jobId"],
                "captchaId": "captcha-sequence-manual-refresh",
                "imageDataUrl": "data:image/png;base64,iVBORw0KGgo=",
            },
            namespace="/runner",
            timeout=2,
        )
        assert acknowledgement["ok"] is True
        return {"ok": True}

    @runner.on("runner:options", namespace="/runner")
    async def on_runner_options(payload: dict) -> dict:
        assert payload["type"] == "GET_ALL_OPTIONS"
        return {"ok": True, "options": {"states": ["Delhi"]}}

    @ui.on("captcha:invalid", namespace="/ui")
    async def on_captcha_invalid(_payload: dict) -> None:
        captcha_invalid_visible.set()

    @ui.on("captcha:refreshed", namespace="/ui")
    async def on_captcha_refreshed(_payload: dict) -> None:
        captcha_refreshed_visible.set()

    @ui.on("job:status", namespace="/ui")
    async def on_job_status(payload: dict) -> None:
        if payload.get("status") == "FAILED":
            failed_payload.update(payload)
            captcha_failed_visible.set()

    try:
        await runner.connect(
            live_server_url,
            namespaces=["/runner"],
            transports=["websocket"],
            auth={
                "runnerId": "runner-e2e",
                "runnerName": "E2E Chrome",
                "version": "0.1.0",
                "token": settings.runner_token,
            },
        )
        await ui.connect(
            live_server_url,
            namespaces=["/ui"],
            transports=["websocket"],
        )

        options_response = await ui.call(
            "ui:runner-options",
            {"runnerId": "runner-e2e", "request": {"type": "GET_ALL_OPTIONS"}},
            namespace="/ui",
            timeout=2,
        )
        assert options_response == {"ok": True, "options": {"states": ["Delhi"]}}

        async with AsyncClient(base_url=live_server_url) as client:
            response = await client.post(
                "/api/jobs",
                json={
                    "runnerId": "runner-e2e",
                    "filters": {"states": ["Delhi"], "autoApply": True},
                },
            )
        assert response.status_code == 201
        job_id = response.json()["id"]
        await asyncio.wait_for(assigned.wait(), timeout=2)
        assert assigned_payload["jobId"] == job_id

        subscription = await ui.call(
            "ui:subscribe-job",
            {"jobId": job_id},
            namespace="/ui",
            timeout=2,
        )
        assert subscription["ok"] is True

        for status in ("OPENING_VAHAN", "CAPTURING_CAPTCHA"):
            acknowledgement = await runner.call(
                "job:status", {"jobId": job_id, "status": status},
                namespace="/runner", timeout=2,
            )
            assert acknowledgement["ok"] is True

        captcha_id = "captcha-sequence-1"
        acknowledgement = await runner.call(
            "captcha:required",
            {
                "jobId": job_id,
                "captchaId": captcha_id,
                "imageDataUrl": "data:image/png;base64,iVBORw0KGgo=",
            },
            namespace="/runner",
            timeout=2,
        )
        assert acknowledgement["ok"] is True
        await asyncio.wait_for(captcha_visible.wait(), timeout=2)

        captcha_id = "captcha-sequence-refreshed"
        acknowledgement = await runner.call(
            "captcha:refreshed",
            {
                "jobId": job_id,
                "captchaId": captcha_id,
                "imageDataUrl": "data:image/png;base64,iVBORw0KGgo=",
            },
            namespace="/runner",
            timeout=2,
        )
        assert acknowledgement["ok"] is True
        await asyncio.wait_for(captcha_refreshed_visible.wait(), timeout=2)

        recovered = await ui.call(
            "ui:subscribe-job", {"jobId": job_id}, namespace="/ui", timeout=2,
        )
        assert recovered["captcha"]["captchaId"] == captcha_id
        assert recovered["captcha"]["imageDataUrl"].startswith("data:image/")

        refreshed = await ui.call(
            "captcha:refresh",
            {"jobId": job_id, "captchaId": captcha_id},
            namespace="/ui",
            timeout=2,
        )
        assert refreshed["ok"] is True
        assert refreshed["captcha"]["captchaId"] == "captcha-sequence-manual-refresh"
        await asyncio.wait_for(captcha_refresh_forwarded.wait(), timeout=2)
        captcha_id = "captcha-sequence-manual-refresh"

        acknowledgement = await ui.call(
            "captcha:submitted",
            {
                "jobId": job_id,
                "captchaId": captcha_id,
                "value": "A1B2C3",
            },
            namespace="/ui",
            timeout=2,
        )
        assert acknowledgement["ok"] is True
        await asyncio.wait_for(captcha_forwarded.wait(), timeout=2)

        acknowledgement = await runner.call(
            "captcha:invalid",
            {
                "jobId": job_id,
                "captchaId": "captcha-sequence-2",
                "imageDataUrl": "data:image/png;base64,iVBORw0KGgo=",
            },
            namespace="/runner",
            timeout=2,
        )
        assert acknowledgement["ok"] is True
        await asyncio.wait_for(captcha_invalid_visible.wait(), timeout=2)

        async def reject_captcha(_payload: dict) -> dict:
            return {"ok": False, "error": "VAHAN tab was closed."}

        runner.on("captcha:submit", handler=reject_captcha, namespace="/runner")
        rejected = await ui.call(
            "captcha:submitted",
            {"jobId": job_id, "captchaId": "captcha-sequence-2", "value": "Z9Y8X7"},
            namespace="/ui", timeout=2,
        )
        assert rejected == {"ok": True, "accepted": True}
        await asyncio.wait_for(captcha_failed_visible.wait(), timeout=2)
        assert failed_payload["error"] == "VAHAN tab was closed."
    finally:
        if ui.connected:
            await ui.disconnect()
        if runner.connected:
            await runner.disconnect()


async def test_ui_health_schedule_update_reaches_runner(live_server_url: str) -> None:
    runner = socketio.AsyncClient()
    schedule_updated = asyncio.Event()
    received_schedule: dict = {}

    @runner.on("ui-health:schedule-updated", namespace="/runner")
    async def on_schedule_updated(payload: dict) -> None:
        received_schedule.update(payload)
        schedule_updated.set()

    try:
        await runner.connect(
            live_server_url,
            namespaces=["/runner"],
            transports=["websocket"],
            auth={
                "runnerId": "schedule-runner",
                "runnerName": "Schedule Chrome",
                "version": "0.1.0",
                "token": settings.runner_token,
            },
        )
        async with AsyncClient(base_url=live_server_url) as client:
            response = await client.put(
                "/api/ui-health/schedule",
                json={"intervalDays": 11},
            )

        assert response.status_code == 200
        await asyncio.wait_for(schedule_updated.wait(), timeout=2)
        assert received_schedule["intervalDays"] == 11
        assert received_schedule["nextCheckAt"] > received_schedule["updatedAt"]
    finally:
        if runner.connected:
            await runner.disconnect()


async def test_ui_health_manual_check_request_reaches_runner(live_server_url: str) -> None:
    runner = socketio.AsyncClient()
    request_received = asyncio.Event()
    received_payload: dict = {}

    @runner.on("ui-health:run-now", namespace="/runner")
    async def on_manual_check(payload: dict) -> None:
        received_payload.update(payload)
        request_received.set()

    try:
        await runner.connect(
            live_server_url,
            namespaces=["/runner"],
            transports=["websocket"],
            auth={
                "runnerId": "manual-check-runner",
                "runnerName": "Manual Check Chrome",
                "version": "0.1.0",
                "token": settings.runner_token,
            },
        )
        async with AsyncClient(base_url=live_server_url) as client:
            response = await client.post("/api/ui-health/run-now", json={})

        assert response.status_code == 202
        body = response.json()
        assert body["runnerId"] == "manual-check-runner"
        assert body["runnerName"] == "Manual Check Chrome"
        await asyncio.wait_for(request_received.wait(), timeout=2)
        assert received_payload["requestId"] == body["requestId"]
        assert received_payload["trigger"] == "manual-web"
    finally:
        if runner.connected:
            await runner.disconnect()


async def test_ui_health_log_received_is_broadcast_to_web_ui(live_server_url: str) -> None:
    ui = socketio.AsyncClient()
    log_received = asyncio.Event()
    received_payload: dict = {}

    @ui.on("ui-health:log-received", namespace="/ui")
    async def on_log_received(payload: dict) -> None:
        received_payload.update(payload)
        log_received.set()

    try:
        await ui.connect(live_server_url, namespaces=["/ui"], transports=["websocket"])
        async with AsyncClient(base_url=live_server_url) as client:
            response = await client.post(
                "/api/ui-health/logs",
                json={
                    "healthCheck": {
                        "status": "PASS",
                        "trigger": "manual-web",
                        "startedAt": "2026-04-01T08:00:00.000Z",
                        "checkedAt": "2026-04-01T08:00:01.000Z",
                        "contract": {"contractVersion": "v1", "signature": "socket-test"},
                    },
                    "pageUrl": "https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en",
                },
            )

        assert response.status_code == 201
        await asyncio.wait_for(log_received.wait(), timeout=2)
        assert received_payload["status"] == "PASS"
        assert received_payload["trigger"] == "manual-web"
        assert received_payload["fileName"].endswith(".csv")
    finally:
        if ui.connected:
            await ui.disconnect()
