from __future__ import annotations

import asyncio
import logging
import re
from uuid import UUID
from pathlib import Path

from app.config import settings
from app.excel_storage import stored_excel_path
from app.models.job import JobStatus, ReportSource, can_transition
from app.excel_storage import write_no_data_marker
from app.realtime.server import sio
from app.services import services
from app.ocr import ocr_to_text
from app.realtime.ui_events import _forward_captcha_submission


_disconnect_tasks: dict[str, asyncio.Task] = {}
_logger = logging.getLogger(__name__)


async def _save_captcha_image(job_id: UUID, image_data_url: str) -> Path | dict:
    try:
        return await services.captcha_images.save(job_id, image_data_url)
    except ValueError:
        return {"ok": False, "error": "Invalid CAPTCHA image data."}
    except OSError:
        _logger.exception("Could not save CAPTCHA image for job %s", job_id)
        return {"ok": False, "error": "Could not save the CAPTCHA image in backend storage."}


async def _forward_captcha_refresh(job_id: UUID, socket_id: str, captcha_id: str) -> None:
    try:
        await sio.call(
            "captcha:refresh",
            {"jobId": str(job_id), "captchaId": captcha_id},
            to=socket_id,
            namespace="/runner",
            timeout=20,
        )
    except Exception:
        _logger.exception("Could not auto-refresh CAPTCHA through extension for job %s", job_id)


async def _auto_solve_captcha(job_id: UUID, runner_id: str, socket_id: str, captcha_id: str, image_path: Path) -> bool:
    try:
        text = await asyncio.to_thread(
            ocr_to_text.recognize,
            image_path,
            whitelist="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        )
    except Exception:
        _logger.exception("OCR failed for job %s", job_id)
        text = ""

    if text:
        text = text.strip()
        if len(text) != 6 or not re.match(r"^[a-zA-Z0-9]+$", text):
            sio.start_background_task(
                _forward_captcha_refresh,
                job_id,
                socket_id,
                captcha_id,
            )
            return True

        updated = await services.jobs.update_status(job_id, JobStatus.SUBMITTING)
        await sio.emit("job:status", updated.model_dump(mode="json", by_alias=True), room=f"job:{job_id}", namespace="/ui")
        sio.start_background_task(
            _forward_captcha_submission,
            job_id,
            runner_id,
            socket_id,
            captcha_id,
            text,
        )
        return True
    return False



async def _expire_disconnected_runner(runner_id: str, socket_id: str) -> None:
    try:
        await asyncio.sleep(settings.runner_disconnect_grace_seconds)
        runner = await services.runners.remove_by_socket(socket_id)
        if not runner:
            return
        if runner.current_job_id:
            job = await services.jobs.get(UUID(runner.current_job_id))
            if job and can_transition(job.status, JobStatus.FAILED):
                job = await services.jobs.update_status(job.id, JobStatus.FAILED, error="Runner disconnected.")
                await sio.emit("job:status", job.model_dump(mode="json", by_alias=True), room=f"job:{job.id}", namespace="/ui")
        await sio.emit("runner:offline", {"runnerId": runner.id}, namespace="/ui")
    finally:
        _disconnect_tasks.pop(runner_id, None)


def _registration(auth: dict | None) -> tuple[str, str, str | None, ReportSource] | None:
    auth = auth or {}
    runner_id = str(auth.get("runnerId", "")).strip()
    runner_name = str(auth.get("runnerName", runner_id)).strip()
    token = str(auth.get("token", ""))
    version = str(auth["version"]) if auth.get("version") else None
    try:
        source = ReportSource(auth.get("source", ReportSource.NEW))
    except ValueError:
        return None
    if not runner_id or not runner_name or token != settings.runner_token or source != ReportSource.NEW:
        return None
    return runner_id, runner_name, version, source


@sio.event(namespace="/runner")
async def connect(sid: str, _environ: dict, auth: dict | None) -> bool:
    registration = _registration(auth)
    if not registration:
        return False
    runner_id, name, version, source = registration
    pending_disconnect = _disconnect_tasks.pop(runner_id, None)
    if pending_disconnect:
        pending_disconnect.cancel()
    runner = await services.runners.register(
        runner_id=runner_id,
        name=name,
        socket_id=sid,
        version=version,
        source=source,
    )
    await sio.enter_room(sid, f"runner:{runner_id}", namespace="/runner")
    await sio.emit(
        "runner:online",
        runner.model_dump(mode="json", by_alias=True),
        namespace="/ui",
    )
    return True


@sio.event(namespace="/runner")
async def disconnect(sid: str) -> None:
    runner = await services.runners.mark_reconnecting(sid)
    if not runner:
        return
    _disconnect_tasks[runner.id] = asyncio.create_task(_expire_disconnected_runner(runner.id, sid))


@sio.on("runner:heartbeat", namespace="/runner")
async def heartbeat(sid: str, _payload: dict | None = None) -> dict:
    runner = await services.runners.get_by_socket(sid)
    if not runner or runner.source != ReportSource.NEW:
        return {"ok": False, "error": "Runner is not registered."}
    await services.runners.heartbeat(runner.id)
    return {"ok": True}


@sio.on("job:status", namespace="/runner")
async def job_status(sid: str, payload: dict) -> dict:
    runner = await services.runners.get_by_socket(sid)
    if not runner or runner.source != ReportSource.NEW:
        return {"ok": False, "error": "Runner is not registered."}
    try:
        job_id = UUID(str(payload["jobId"]))
        status = JobStatus(str(payload["status"]))
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "Invalid job status payload."}

    job = await services.jobs.get(job_id)
    if not job or job.runner_id != runner.id:
        return {"ok": False, "error": "Job does not belong to this runner."}
    if not can_transition(job.status, status):
        return {"ok": False, "error": f"Invalid job transition: {job.status} -> {status}."}
    if status == JobStatus.COMPLETED and not stored_excel_path(job.excel_file_name, job.session_id):
        return {"ok": False, "error": "Excel report has not been saved; job cannot be completed."}
    if status == JobStatus.NO_DATA and job.excel_file_name:
        return {"ok": False, "error": "A report file already exists; job cannot be marked as no data."}
    try:
        updated = await services.jobs.transition_status(
            job_id,
            status,
            error=payload.get("error"),
            no_data_writer=write_no_data_marker if status == JobStatus.NO_DATA else None,
        )
    except OSError as exc:
        return {"ok": False, "error": f"Could not save the no-data text file: {exc}"}
    if updated is None:
        return {"ok": False, "error": "Job status changed before this result was saved."}
    if status in {JobStatus.COMPLETED, JobStatus.NO_DATA, JobStatus.FAILED, JobStatus.CANCELLED}:
        await services.runners.release_job(runner.id, str(job_id))
    await sio.emit(
        "job:status",
        updated.model_dump(mode="json", by_alias=True),
        room=f"job:{job_id}",
        namespace="/ui",
    )
    return {"ok": True}


@sio.on("job:apply-clicked", namespace="/runner")
async def job_apply_clicked(sid: str, payload: dict) -> dict:
    """Count one Apply click only after the official VAHAN button accepted it."""
    runner = await services.runners.get_by_socket(sid)
    if not runner or runner.source != ReportSource.NEW:
        return {"ok": False, "error": "Runner is not registered."}
    try:
        job_id = UUID(str(payload["jobId"]))
        click_id = str(payload["clickId"]).strip()
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "Invalid Apply click payload."}
    if not click_id or len(click_id) > 128:
        return {"ok": False, "error": "Invalid Apply click identifier."}

    job = await services.jobs.get(job_id)
    if not job or job.runner_id != runner.id:
        return {"ok": False, "error": "Job does not belong to this runner."}
    updated = await services.jobs.record_successful_apply_click(job_id, click_id)
    if not updated:
        return {"ok": False, "error": "Job not found."}
    await sio.emit(
        "job:status",
        updated.model_dump(mode="json", by_alias=True),
        room=f"job:{job_id}",
        namespace="/ui",
    )
    return {"ok": True, "successfulApplyCount": updated.successful_apply_count}


@sio.on("captcha:required", namespace="/runner")
async def captcha_required(sid: str, payload: dict) -> dict:
    runner = await services.runners.get_by_socket(sid)
    if not runner or runner.source != ReportSource.NEW:
        return {"ok": False, "error": "Runner is not registered."}
    try:
        job_id = UUID(str(payload["jobId"]))
        captcha_id = str(payload["captchaId"])
        image_data_url = str(payload["imageDataUrl"])
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "Invalid CAPTCHA payload."}
    if not captcha_id or not image_data_url.startswith("data:image/"):
        return {"ok": False, "error": "Invalid CAPTCHA image."}
    if len(image_data_url) > 1_000_000:
        return {"ok": False, "error": "CAPTCHA image is too large."}

    job = await services.jobs.get(job_id)
    if not job or job.runner_id != runner.id:
        return {"ok": False, "error": "Job does not belong to this runner."}
    if not can_transition(job.status, JobStatus.WAITING_CAPTCHA):
        return {"ok": False, "error": "Job cannot request CAPTCHA in its current state."}
    storage_result = await _save_captcha_image(job_id, image_data_url)
    if isinstance(storage_result, dict):
        return storage_result
    await services.jobs.update_status(
        job_id,
        JobStatus.WAITING_CAPTCHA,
        captcha_id=captcha_id,
        captcha_image_data_url=image_data_url,
    )
    if await _auto_solve_captcha(job_id, runner.id, sid, captcha_id, storage_result):
        return {"ok": True}
    await sio.emit(
        "captcha:required",
        {
            "jobId": str(job_id),
            "captchaId": captcha_id,
            "imageDataUrl": image_data_url,
        },
        room=f"job:{job_id}",
        namespace="/ui",
    )
    return {"ok": True}


@sio.on("captcha:invalid", namespace="/runner")
async def captcha_invalid(sid: str, payload: dict) -> dict:
    runner = await services.runners.get_by_socket(sid)
    if not runner or runner.source != ReportSource.NEW:
        return {"ok": False, "error": "Runner is not registered."}
    try:
        job_id = UUID(str(payload["jobId"]))
        captcha_id = str(payload["captchaId"])
        image_data_url = str(payload["imageDataUrl"])
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "Invalid CAPTCHA payload."}
    if not captcha_id or not image_data_url.startswith("data:image/"):
        return {"ok": False, "error": "Invalid CAPTCHA image."}
    if len(image_data_url) > 1_000_000:
        return {"ok": False, "error": "CAPTCHA image is too large."}

    job = await services.jobs.get(job_id)
    if not job or job.runner_id != runner.id:
        return {"ok": False, "error": "Job does not belong to this runner."}
    if job.status not in {JobStatus.SUBMITTING, JobStatus.WAITING_RESULT}:
        return {"ok": False, "error": "Job is not waiting for a VAHAN result."}
    storage_result = await _save_captcha_image(job_id, image_data_url)
    if isinstance(storage_result, dict):
        return storage_result
    updated = await services.jobs.update_status(
        job_id,
        JobStatus.WAITING_CAPTCHA,
        captcha_id=captcha_id,
        captcha_image_data_url=image_data_url,
    )
    if await _auto_solve_captcha(job_id, runner.id, sid, captcha_id, storage_result):
        return {"ok": True}
    await sio.emit(
        "captcha:invalid",
        {
            "jobId": str(job_id),
            "captchaId": captcha_id,
            "imageDataUrl": image_data_url,
        },
        room=f"job:{job_id}",
        namespace="/ui",
    )
    await sio.emit(
        "job:status",
        updated.model_dump(mode="json", by_alias=True),
        room=f"job:{job_id}",
        namespace="/ui",
    )
    return {"ok": True}


@sio.on("captcha:refreshed", namespace="/runner")
async def captcha_refreshed(sid: str, payload: dict) -> dict:
    runner = await services.runners.get_by_socket(sid)
    if not runner or runner.source != ReportSource.NEW:
        return {"ok": False, "error": "Runner is not registered."}
    try:
        job_id = UUID(str(payload["jobId"]))
        captcha_id = str(payload["captchaId"])
        image_data_url = str(payload["imageDataUrl"])
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "Invalid CAPTCHA payload."}
    if not captcha_id or not image_data_url.startswith("data:image/"):
        return {"ok": False, "error": "Invalid CAPTCHA image."}
    if len(image_data_url) > 1_000_000:
        return {"ok": False, "error": "CAPTCHA image is too large."}

    job = await services.jobs.get(job_id)
    if not job or job.runner_id != runner.id:
        return {"ok": False, "error": "Job does not belong to this runner."}
    if job.status != JobStatus.WAITING_CAPTCHA:
        return {"ok": False, "error": "Job is not waiting for CAPTCHA."}
    storage_result = await _save_captcha_image(job_id, image_data_url)
    if isinstance(storage_result, dict):
        return storage_result
    updated = await services.jobs.update_status(
        job_id, JobStatus.WAITING_CAPTCHA,
        captcha_id=captcha_id, captcha_image_data_url=image_data_url,
    )
    if await _auto_solve_captcha(job_id, runner.id, sid, captcha_id, storage_result):
        return {"ok": True}
    await sio.emit(
        "captcha:refreshed",
        {"jobId": str(job_id), "captchaId": captcha_id, "imageDataUrl": image_data_url},
        room=f"job:{job_id}",
        namespace="/ui",
    )
    await sio.emit(
        "job:status",
        updated.model_dump(mode="json", by_alias=True),
        room=f"job:{job_id}",
        namespace="/ui",
    )
    return {"ok": True}
