from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.models.job import JobStatus
from app.repositories.ocr_rate_limit import reserve_ocr_start
from app.realtime.server import sio
from app.services import services
from app.models.job import ReportSource

router = APIRouter(prefix="/runner/ocr", tags=["runner OCR"])


class OcrStartRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: UUID = Field(alias="jobId")
    captcha_id: str = Field(alias="captchaId", min_length=1, max_length=128)


@router.post("/start")
async def begin_ocr(command: OcrStartRequest, request: Request,
    runner_id: str | None = Header(default=None, alias="X-VAHAN-RUNNER-ID")):
    if not getattr(request.state, "authenticated_runner", False) or not runner_id:
        raise HTTPException(403, "Only an authenticated browser runner can start CAPTCHA OCR.")
    runner = await services.runners.get(runner_id)
    if not runner or runner.source != ReportSource.NEW:
        raise HTTPException(403, "Runner is not registered for report execution.")
    job = await services.jobs.get(command.job_id)
    if not job or job.runner_id != runner_id or runner.current_job_id != str(command.job_id):
        raise HTTPException(404, "OCR job not found for this runner.")
    if job.status != JobStatus.WAITING_CAPTCHA or job.captcha_id != command.captcha_id:
        raise HTTPException(409, "The CAPTCHA challenge changed before OCR could start.")

    decision = await reserve_ocr_start(job.id, command.captcha_id)
    if decision.allowed:
        return {"allowed": True, "remaining": decision.remaining}
    if decision.duplicate:
        return {"allowed": False, "code": "OCR_ALREADY_STARTED",
            "error": "OCR has already started for this CAPTCHA challenge."}

    retry_after = decision.retry_after_seconds
    wait_minutes = max(1, (retry_after + 59) // 60)
    wait_label = f"{wait_minutes} minute" if wait_minutes == 1 else f"{wait_minutes} minutes"
    message = ("OCR_RATE_LIMIT: System-wide OCR limit reached (20 starts per 10 minutes). "
        f"This job was stopped. Try again in about {wait_label}.")
    updated = await services.jobs.update_status(job.id, JobStatus.FAILED, error=message,
        expected_status=JobStatus.WAITING_CAPTCHA, expected_captcha_id=command.captcha_id)
    if updated is None:
        raise HTTPException(409, "Job status changed before the OCR limit could stop it.")
    from app.scheduler_wakeup import wake_scheduler
    wake_scheduler()
    await sio.emit("job:status", updated.model_dump(mode="json", by_alias=True),
        room=f"job:{job.id}", namespace="/ui")
    await sio.emit("job:error", {"jobId": str(job.id), "code": "OCR_RATE_LIMIT", "message": message},
        namespace="/ui")
    return {"allowed": False, "code": "OCR_RATE_LIMIT", "error": message,
        "retryAfterSeconds": retry_after}
