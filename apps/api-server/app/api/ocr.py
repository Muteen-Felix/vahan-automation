from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.models.job import JobStatus, ReportSource
from app.services import services

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

    return {"allowed": True}
