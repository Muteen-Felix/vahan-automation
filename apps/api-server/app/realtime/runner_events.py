from __future__ import annotations

import asyncio
import logging
import re
from uuid import UUID
from pathlib import Path

from app.config import settings
from app.security import runner_token_matches
from app.models.job import JobStatus, ReportSource, can_transition
from app.models.filter_execution import FilterExecution
from app.realtime.server import sio
from app.services import services
from app.scheduler_wakeup import wake_scheduler


_disconnect_tasks: dict[str, asyncio.Task] = {}
_logger = logging.getLogger(__name__)


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
        wake_scheduler()
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
    if not runner_id or len(runner_id) > 128 or not runner_name or not runner_token_matches(token, runner_id) or source != ReportSource.NEW or auth.get("engine") != "playwright":
        return None
    return runner_id, runner_name, version, source


@sio.event(namespace="/runner")
async def connect(sid: str, _environ: dict, auth: dict | None) -> bool:
    registration = _registration(auth)
    if not registration:
        from app.repositories.postgres import audit
        await audit(None, 'security.worker_denied', {'reason': 'credential_or_identity'})
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
    from app.repositories.postgres import audit
    await audit(runner_id, 'worker.registered', {'engine': 'playwright'})
    await sio.enter_room(sid, f"runner:{runner_id}", namespace="/runner")
    await sio.emit(
        "runner:online",
        runner.model_dump(mode="json", by_alias=True),
        namespace="/ui",
    )
    wake_scheduler()
    return True


@sio.event(namespace="/runner")
async def disconnect(sid: str) -> None:
    runner = await services.runners.mark_reconnecting(sid)
    if not runner:
        return
    wake_scheduler()
    _disconnect_tasks[runner.id] = asyncio.create_task(_expire_disconnected_runner(runner.id, sid))


@sio.on("runner:heartbeat", namespace="/runner")
async def heartbeat(sid: str, _payload: dict | None = None) -> dict:
    runner = await services.runners.get_by_socket(sid)
    if not runner or runner.source != ReportSource.NEW:
        return {"ok": False, "error": "Runner is not registered."}
    if not await services.runners.heartbeat(sid):
        return {"ok": False, "error": "Runner connection changed."}
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
    if status == JobStatus.COMPLETED and not job.report_table_count and not await services.files.for_job(job.id, "excel"):
        return {"ok": False, "error": "Neither report tables nor Excel have been saved; job cannot be completed."}
    if status == JobStatus.NO_DATA and job.excel_file_name:
        return {"ok": False, "error": "A report file already exists; job cannot be marked as no data."}
    try:
        updated = await services.jobs.transition_status(
            job_id,
            status,
            error=payload.get("error"),
        )
    except OSError as exc:
        return {"ok": False, "error": f"Could not save the no-data text file: {exc}"}
    if updated is None:
        return {"ok": False, "error": "Job status changed before this result was saved."}
    if status in {JobStatus.COMPLETED, JobStatus.NO_DATA, JobStatus.FAILED, JobStatus.CANCELLED}:
        await services.runners.release_job(runner.id, str(job_id))
        wake_scheduler()
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
        return {"ok": False, "error": "Apply was not recorded: job is not submitting or its status changed.",
                "code": "JOB_APPLY_STATE_CONFLICT"}
    await sio.emit(
        "job:status",
        updated.model_dump(mode="json", by_alias=True),
        room=f"job:{job_id}",
        namespace="/ui",
    )
    return {"ok": True, "successfulApplyCount": updated.successful_apply_count}


@sio.on('job:filters-verified', namespace='/runner')
async def job_filters_verified(sid: str, payload: dict) -> dict:
    runner = await services.runners.get_by_socket(sid)
    if not runner or runner.source != ReportSource.NEW:
        return {'ok': False, 'error': 'Runner is not registered.'}
    try:
        job_id = UUID(str(payload['jobId']))
        phase = payload['phase']
        if phase not in {'filled', 'before-apply'}:
            raise ValueError('Invalid verification phase.')
        execution = FilterExecution.model_validate(payload['execution'])
        updated = await services.jobs.record_filter_execution(job_id, runner.id, phase, execution)
    except (KeyError, TypeError, ValueError) as error:
        return {'ok': False, 'error': f'Filter verification rejected: {error}'}
    if updated is None:
        return {'ok': False, 'error': 'Job changed before the verified filters were saved.'}
    return {'ok': True}


@sio.on("captcha:required", namespace="/runner")
async def captcha_required(sid: str, payload: dict) -> dict:
    runner = await services.runners.get_by_socket(sid)
    if not runner or runner.source != ReportSource.NEW:
        return {"ok": False, "error": "Runner is not registered."}
    try:
        job_id = UUID(str(payload["jobId"]))
        captcha_id = str(payload["captchaId"])
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "Invalid CAPTCHA payload."}
    if not captcha_id or len(captcha_id) > 128:
        return {"ok": False, "error": "Invalid CAPTCHA ID."}

    job = await services.jobs.get(job_id)
    if not job or job.runner_id != runner.id:
        return {"ok": False, "error": "Job does not belong to this runner."}
    if not can_transition(job.status, JobStatus.WAITING_CAPTCHA):
        return {"ok": False, "error": "Job cannot request CAPTCHA in its current state."}
    updated = await services.jobs.update_status(
        job_id,
        JobStatus.WAITING_CAPTCHA,
        captcha_id=captcha_id,
        captcha_image_data_url="",
        expected_status=job.status,
    )
    if updated is None:
        return {"ok": False, "error": "Job changed before CAPTCHA was saved."}
    await sio.emit(
        "captcha:required",
        {
            "jobId": str(job_id),
            "captchaId": captcha_id,
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
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "Invalid CAPTCHA payload."}
    if not captcha_id or len(captcha_id) > 128:
        return {"ok": False, "error": "Invalid CAPTCHA ID."}

    job = await services.jobs.get(job_id)
    if not job or job.runner_id != runner.id:
        return {"ok": False, "error": "Job does not belong to this runner."}
    if job.status not in {JobStatus.SUBMITTING, JobStatus.WAITING_RESULT}:
        return {"ok": False, "error": "Job is not waiting for a VAHAN result."}
    updated = await services.jobs.update_status(
        job_id,
        JobStatus.WAITING_CAPTCHA,
        captcha_id=captcha_id,
        captcha_image_data_url="",
        expected_status=job.status,
        expected_captcha_id=job.captcha_id,
    )
    if updated is None:
        return {"ok": False, "error": "Job changed before invalid CAPTCHA was saved."}
    await sio.emit(
        "captcha:invalid",
        {
            "jobId": str(job_id),
            "captchaId": captcha_id,
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
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "Invalid CAPTCHA payload."}
    if not captcha_id or len(captcha_id) > 128:
        return {"ok": False, "error": "Invalid CAPTCHA ID."}

    job = await services.jobs.get(job_id)
    if not job or job.runner_id != runner.id:
        return {"ok": False, "error": "Job does not belong to this runner."}
    if job.status != JobStatus.WAITING_CAPTCHA:
        return {"ok": False, "error": "Job is not waiting for CAPTCHA."}
    updated = await services.jobs.update_status(
        job_id, JobStatus.WAITING_CAPTCHA,
        captcha_id=captcha_id, captcha_image_data_url="",
        expected_status=JobStatus.WAITING_CAPTCHA,
        expected_captcha_id=job.captcha_id,
    )
    if updated is None:
        return {"ok": False, "error": "CAPTCHA changed before the refresh was saved."}
    await sio.emit(
        "captcha:refreshed",
        {"jobId": str(job_id), "captchaId": captcha_id},
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


@sio.on("runner:recover", namespace="/runner")
async def runner_recover(sid: str, payload: dict) -> dict:
    runner = await services.runners.get_by_socket(sid)
    if not runner:
        return {"ok": False, "error": "Runner is not registered."}
    if runner.current_job_id:
        job = await services.jobs.get(UUID(runner.current_job_id))
        if job and can_transition(job.status, JobStatus.FAILED) and payload.get("activeJobId") != str(job.id):
            job = await services.jobs.update_status(job.id, JobStatus.FAILED, error="Browser worker restarted. Retry the report explicitly.")
            await sio.emit("job:status", job.model_dump(mode="json", by_alias=True), room=f"job:{job.id}", namespace="/ui")
        if not job or job.status in {JobStatus.COMPLETED, JobStatus.NO_DATA, JobStatus.FAILED, JobStatus.CANCELLED}:
            await services.runners.release_job(runner.id, runner.current_job_id)
    current = await services.runners.get(runner.id)
    return {"ok": True, "activeJobId": current.current_job_id if current else None}


@sio.on('network:problem', namespace='/runner')
async def network_problem(sid: str, _payload: dict):
    runner = await services.runners.get_by_socket(sid)
    if not runner:
        return {'ok': False, 'error': 'Runner is not registered.'}
    from app.network_guard import probe, record
    online, error = await probe()
    if not online:
        await record(False, error)
    return {'ok': True, 'online': online}
