import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select

from app.db import engine, schema as db
from app.main import application
from app.models.job import Job, JobStatus
from app.repositories.ocr_rate_limit import OCR_START_LIMIT, OCR_WINDOW_KEY, reserve_ocr_start
from app.repositories.ocr_rate_limit import OcrStartDecision
from app.services import services


async def _clear_ocr_window():
    async with engine.begin() as connection:
        await connection.execute(db.app_settings.delete().where(db.app_settings.c.key == OCR_WINDOW_KEY))


async def test_ocr_limit_is_atomic_and_shared_across_concurrent_workers():
    await _clear_ocr_window()
    decisions = await asyncio.gather(*(reserve_ocr_start(uuid4(), f"captcha-{index}")
        for index in range(OCR_START_LIMIT + 5)))
    assert sum(decision.allowed for decision in decisions) == OCR_START_LIMIT
    assert sum(not decision.allowed and not decision.duplicate for decision in decisions) == 5
    async with engine.connect() as connection:
        stored = await connection.scalar(select(db.app_settings.c.value)
            .where(db.app_settings.c.key == OCR_WINDOW_KEY))
    assert len(stored["starts"]) == OCR_START_LIMIT


async def test_expired_ocr_starts_do_not_consume_the_current_window():
    await _clear_ocr_window()
    old = datetime.now(timezone.utc) - timedelta(minutes=11)
    async with engine.begin() as connection:
        await connection.execute(insert(db.app_settings).values(key=OCR_WINDOW_KEY, value={
            "starts": [{"key": f"old-{index}", "startedAt": old.isoformat()}
                       for index in range(OCR_START_LIMIT)]
        }))
    decision = await reserve_ocr_start(uuid4(), "new-captcha")
    assert decision.allowed and decision.remaining == OCR_START_LIMIT - 1


async def test_ocr_window_and_deduplication_survive_api_connection_restart():
    job_id = uuid4()
    assert (await reserve_ocr_start(job_id, "same-challenge")).allowed
    await engine.dispose()
    duplicate = await reserve_ocr_start(job_id, "same-challenge")
    assert not duplicate.allowed and duplicate.duplicate
    for index in range(OCR_START_LIMIT - 1):
        assert (await reserve_ocr_start(uuid4(), str(index))).allowed
    await engine.dispose()
    assert not (await reserve_ocr_start(uuid4(), "after-restart")).allowed


async def test_quota_failure_cannot_overwrite_a_concurrent_submission(monkeypatch):
    runner_id = f"ocr-race-{uuid4().hex}"
    job = await services.jobs.create(Job(runnerId=runner_id, ownerUsername="test-admin",
        filters={}, status=JobStatus.WAITING_CAPTCHA, captchaId="original"))
    await services.runners.register(runner_id=runner_id, name="OCR test", socket_id="ocr-race-socket")
    await services.runners.set_job(runner_id, str(job.id))
    monkeypatch.setattr("app.main.runner_token_matches", lambda candidate: candidate == "test-runner-token")
    async def quota_exhausted(*_args):
        await services.jobs.transition_status(job.id, JobStatus.SUBMITTING)
        return OcrStartDecision(allowed=False, retry_after_seconds=60)
    monkeypatch.setattr("app.api.ocr.reserve_ocr_start", quota_exhausted)
    headers = {"X-VAHAN-RUNNER-TOKEN": "test-runner-token", "X-VAHAN-RUNNER-ID": runner_id}
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post("/api/runner/ocr/start", headers=headers,
            json={"jobId": str(job.id), "captchaId": "original"})
    assert response.status_code == 409
    assert (await services.jobs.get(job.id)).status == JobStatus.SUBMITTING


async def test_ocr_endpoint_rejects_ui_token_and_mismatched_runner(admin_headers, monkeypatch):
    runner_id = f"ocr-owner-{uuid4().hex}"
    job = await services.jobs.create(Job(runnerId=runner_id, ownerUsername="test-admin",
        filters={}, status=JobStatus.WAITING_CAPTCHA, captchaId="current"))
    await services.runners.register(runner_id=runner_id, name="OCR test", socket_id="ocr-owner-socket")
    await services.runners.set_job(runner_id, str(job.id))
    monkeypatch.setattr("app.main.runner_token_matches", lambda candidate: candidate == "test-runner-token")
    payload = {"jobId": str(job.id), "captchaId": "current"}
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post("/api/runner/ocr/start", headers=admin_headers, json=payload)
        assert response.status_code == 403
        wrong_headers = {"X-VAHAN-RUNNER-TOKEN": "test-runner-token", "X-VAHAN-RUNNER-ID": "other-runner"}
        assert (await client.post("/api/runner/ocr/start", headers=wrong_headers, json=payload)).status_code == 403
        owner_headers = {**wrong_headers, "X-VAHAN-RUNNER-ID": runner_id}
        stale = {**payload, "captchaId": "stale"}
        assert (await client.post("/api/runner/ocr/start", headers=owner_headers, json=stale)).status_code == 409
    async with engine.connect() as connection:
        assert await connection.scalar(select(db.app_settings.c.value)
            .where(db.app_settings.c.key == OCR_WINDOW_KEY)) is None


async def test_exhausted_ocr_limit_fails_job_with_visible_reason(admin_headers, monkeypatch):
    await _clear_ocr_window()
    for index in range(OCR_START_LIMIT):
        assert (await reserve_ocr_start(uuid4(), f"used-{index}")).allowed
    job_id = uuid4()
    captcha_id = "current-captcha"
    runner_id = f"ocr-limit-{uuid4().hex}"
    job = await services.jobs.create(Job(id=job_id, runnerId=runner_id, ownerUsername="test-admin",
        filters={}, status=JobStatus.WAITING_CAPTCHA, captchaId=captcha_id))
    await services.runners.register(runner_id=runner_id, name="OCR test", socket_id="ocr-limit-socket")
    await services.runners.set_job(runner_id, str(job.id))
    monkeypatch.setattr("app.main.runner_token_matches", lambda candidate: candidate == "test-runner-token")
    emit = AsyncMock()
    monkeypatch.setattr("app.api.ocr.sio.emit", emit)
    headers = {"X-VAHAN-RUNNER-TOKEN": "test-runner-token", "X-VAHAN-RUNNER-ID": runner_id}
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post("/api/runner/ocr/start", headers=headers,
            json={"jobId": str(job_id), "captchaId": captcha_id})
    assert response.status_code == 200
    body = response.json()
    assert body["allowed"] is False and body["code"] == "OCR_RATE_LIMIT"
    assert "20 starts per 10 minutes" in body["error"]
    updated = await services.jobs.get(job_id)
    assert updated.status == JobStatus.FAILED and updated.error == body["error"]
    assert (await services.runners.get(runner_id)).current_job_id is None
    assert emit.await_count == 2
    assert emit.await_args_list[0].args[0] == "job:status"
    assert emit.await_args_list[0].kwargs["room"] == f"job:{job_id}"
    assert emit.await_args_list[1].args[0] == "job:error"
    assert emit.await_args_list[1].args[1]["code"] == "OCR_RATE_LIMIT"
