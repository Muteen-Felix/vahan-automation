import asyncio
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.main import application
from app.models.job import Job, JobStatus
from app.services import services


async def test_ocr_starts_are_not_capped_across_workers(admin_headers, monkeypatch):
    runner_token = f"test-runner-{uuid4().hex}"
    monkeypatch.setattr("app.main.runner_token_matches", lambda candidate: candidate == runner_token)
    challenges = []
    for _ in range(25):
        runner_id = f"ocr-unlimited-{uuid4().hex}"
        captcha_id = f"captcha-{uuid4().hex}"
        job = await services.jobs.create(Job(runnerId=runner_id, ownerUsername="test-admin",
            filters={}, status=JobStatus.WAITING_CAPTCHA, captchaId=captcha_id))
        await services.runners.register(runner_id=runner_id, name="OCR test", socket_id=runner_id)
        await services.runners.set_job(runner_id, str(job.id))
        challenges.append((runner_id, job.id, captcha_id))

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        responses = await asyncio.gather(*(client.post("/api/runner/ocr/start",
            headers={"X-VAHAN-RUNNER-TOKEN": runner_token, "X-VAHAN-RUNNER-ID": runner_id},
            json={"jobId": str(job_id), "captchaId": captcha_id})
            for runner_id, job_id, captcha_id in challenges))

    assert all(response.status_code == 200 for response in responses)
    assert all(response.json() == {"allowed": True} for response in responses)
    final_jobs = await asyncio.gather(*(services.jobs.get(job_id) for _, job_id, _ in challenges))
    assert all(job and job.status == JobStatus.WAITING_CAPTCHA for job in final_jobs)


async def test_ocr_start_still_validates_runner_and_current_challenge(admin_headers, monkeypatch):
    runner_id = f"ocr-owner-{uuid4().hex}"
    job = await services.jobs.create(Job(runnerId=runner_id, ownerUsername="test-admin",
        filters={}, status=JobStatus.WAITING_CAPTCHA, captchaId="current"))
    await services.runners.register(runner_id=runner_id, name="OCR test", socket_id="ocr-owner-socket")
    await services.runners.set_job(runner_id, str(job.id))
    runner_token = f"test-runner-{uuid4().hex}"
    monkeypatch.setattr("app.main.runner_token_matches", lambda candidate: candidate == runner_token)
    payload = {"jobId": str(job.id), "captchaId": "current"}
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post("/api/runner/ocr/start", headers=admin_headers, json=payload)
        assert response.status_code == 403
        wrong_headers = {"X-VAHAN-RUNNER-TOKEN": runner_token, "X-VAHAN-RUNNER-ID": "other-runner"}
        assert (await client.post("/api/runner/ocr/start", headers=wrong_headers, json=payload)).status_code == 403
        owner_headers = {**wrong_headers, "X-VAHAN-RUNNER-ID": runner_id}
        stale = {**payload, "captchaId": "stale"}
        assert (await client.post("/api/runner/ocr/start", headers=owner_headers, json=stale)).status_code == 409
