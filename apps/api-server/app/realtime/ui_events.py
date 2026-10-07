import asyncio
import time
from uuid import UUID

from socketio.exceptions import TimeoutError as SocketIOTimeoutError

from app.models.job import JobStatus, can_transition
from app.realtime.server import sio
from app.security import access_token_expiry, authenticate_access_token
from app.services import services
from app.repositories.postgres import audit


CAPTCHA_FORWARD_TIMEOUT_SECONDS = 45
CAPTCHA_REFRESH_TIMEOUT_SECONDS = 20
RUNNER_OPTIONS_TIMEOUT_SECONDS = 115
_ui_token_expiry_tasks: dict[str, asyncio.Task] = {}
_ui_sessions: dict[str, str] = {}


async def _fail_captcha_submission(job_id: UUID, runner_id: str, error: str) -> None:
    """Record a runner-side CAPTCHA failure without overwriting a newer state."""
    current = await services.jobs.get(job_id)
    if not current or current.status != JobStatus.SUBMITTING:
        return
    if not can_transition(current.status, JobStatus.FAILED):
        return
    failed = await services.jobs.update_status(job_id, JobStatus.FAILED, error=error)
    if not failed:
        return
    await services.runners.release_job(runner_id, str(job_id))
    await sio.emit(
        "job:status",
        failed.model_dump(mode="json", by_alias=True),
        room=f"job:{job_id}",
        namespace="/ui",
    )


async def _forward_captcha_submission(job_id: UUID, runner_id: str, runner_socket_id: str,
                                      captcha_id: str, text1: str) -> None:
    """Forward only the text entered by the human operator."""
    try:
        acknowledgement = await sio.call('captcha:submit',
            {'jobId': str(job_id), 'captchaId': captcha_id, 'value': text1},
            to=runner_socket_id, namespace='/runner', timeout=CAPTCHA_FORWARD_TIMEOUT_SECONDS)
    except SocketIOTimeoutError:
        await _fail_captcha_submission(job_id, runner_id, 'Browser worker did not acknowledge CAPTCHA in time.')
        return
    except Exception as error:
        await _fail_captcha_submission(job_id, runner_id, f'Could not forward CAPTCHA: {error}')
        return
    if not acknowledgement or not acknowledgement.get('ok'):
        await _fail_captcha_submission(job_id, runner_id,
            (acknowledgement or {}).get('error', 'Browser worker rejected the submission.'))


@sio.event(namespace="/ui")
async def connect(_sid: str, _environ: dict, auth: dict | None) -> bool:
    auth = auth or {}
    token = str(auth.get("token", ""))
    user = await authenticate_access_token(token)
    expires_at = access_token_expiry(token)
    if not user:
        return False
    await sio.save_session(_sid, {"token": token, 'username': user['username']}, namespace="/ui")
    await sio.enter_room(_sid, 'reports:shared', namespace='/ui')
    _ui_sessions[_sid] = user["session_id"]
    previous_task = _ui_token_expiry_tasks.pop(_sid, None)
    if previous_task:
        previous_task.cancel()
    if expires_at is not None:
        _ui_token_expiry_tasks[_sid] = asyncio.create_task(_disconnect_after_expiry(_sid, expires_at))
    return True


async def _disconnect_after_expiry(sid: str, expires_at: int) -> None:
    try:
        await asyncio.sleep(max(0, expires_at - time.time()))
        await sio.disconnect(sid, namespace="/ui")
    except asyncio.CancelledError:
        return
    except Exception:  # The socket may have disconnected before its token expired.
        return
    finally:
        current_task = asyncio.current_task()
        if _ui_token_expiry_tasks.get(sid) is current_task:
            _ui_token_expiry_tasks.pop(sid, None)


@sio.event(namespace="/ui")
async def disconnect(sid: str) -> None:
    _ui_sessions.pop(sid, None)
    task = _ui_token_expiry_tasks.pop(sid, None)
    if task and task is not asyncio.current_task():
        task.cancel()


@sio.on("ui:subscribe-job", namespace="/ui")
async def subscribe_job(sid: str, payload: dict) -> dict:
    user = await authenticated_ui(sid)
    if not user:
        return {"ok": False, "error": "Authentication required."}
    try:
        job_id = UUID(str(payload["jobId"]))
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "Invalid job ID."}
    job = await services.jobs.get(job_id)
    if not job or (user["role"] != "admin" and job.owner_username != user["username"]):
        return {"ok": False, "error": "Job not found."}
    await sio.enter_room(sid, f"job:{job_id}", namespace="/ui")
    response = {
        "ok": True,
        "job": job.model_dump(mode="json", by_alias=True),
    }
    if job.status == JobStatus.WAITING_CAPTCHA and job.captcha_id and job.captcha_image_data_url:
        response["captcha"] = {
            "jobId": str(job.id),
            "captchaId": job.captcha_id,
            "imageDataUrl": job.captcha_image_data_url,
        }
    return response


@sio.on("ui:runner-options", namespace="/ui")
async def runner_options(_sid: str, payload: dict) -> dict:
    user = await authenticated_ui(_sid)
    if not user:
        return {"ok": False, "error": "Authentication required."}
    runner_id = str(payload.get("runnerId", "")).strip()
    request = payload.get("request")
    if not runner_id or not isinstance(request, dict):
        return {"ok": False, "error": "Invalid runner options request."}
    if request.get("type") not in {
        "GET_ALL_OPTIONS", "GET_STATE_OPTIONS", "GET_RTO_OPTIONS",
        "GET_X_AXIS_OPTIONS", "SEARCH_MAKERS",
    }:
        return {"ok": False, "error": "Unsupported runner options request."}
    runner = await services.runners.get(runner_id)
    if not runner:
        return {"ok": False, "error": "Runner is offline."}
    from app.db import engine, schema as db
    from sqlalchemy import select
    from app.repositories.postgres import now
    async with engine.connect() as connection:
        reserved = await connection.scalar(select(db.runner_planning_leases.c.runner_id).where(
            db.runner_planning_leases.c.runner_id == runner_id, db.runner_planning_leases.c.expires_at > now()))
    if reserved:
        return {'ok': False, 'error': 'Worker is preparing a filter preview.', 'code': 'RUNNER_BUSY', 'retryAfterMs': 1000}
    try:
        result = await sio.call(
            "runner:options",
            request,
            to=runner.socket_id,
            namespace="/runner",
            timeout=RUNNER_OPTIONS_TIMEOUT_SECONDS,
        )
        await audit(user['username'], 'runner.options', {'runnerId': runner_id, 'request': request, 'response': result})
        return result
    except SocketIOTimeoutError:
        return {"ok": False, "error": "Runner did not return VAHAN options in time."}


@sio.on("captcha:submitted", namespace="/ui")
async def submit_captcha(_sid: str, payload: dict) -> dict:
    user = await authenticated_ui(_sid)
    if not user:
        return {"ok": False, "error": "Authentication required."}
    try:
        job_id = UUID(str(payload["jobId"]))
        captcha_id = str(payload["captchaId"])
        text1 = str(payload.get("text1", payload.get("value", ""))).strip()
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "Invalid CAPTCHA submission."}
    if len(text1) != 6:
        return {"ok": False, "error": "CAPTCHA must contain exactly 6 characters."}

    job = await services.jobs.get(job_id)
    if not job or (user["role"] != "admin" and job.owner_username != user["username"]):
        return {"ok": False, "error": "Job not found."}
    if job.status != JobStatus.WAITING_CAPTCHA:
        return {"ok": False, "error": "Job is not waiting for CAPTCHA."}
    if job.captcha_id != captcha_id:
        return {"ok": False, "error": "CAPTCHA has changed or expired."}
    if not can_transition(job.status, JobStatus.SUBMITTING):
        return {"ok": False, "error": "Job cannot submit CAPTCHA in its current state."}

    runner = await services.runners.get(job.runner_id)
    if not runner:
        return {"ok": False, "error": "Runner is offline."}

    updated = await services.jobs.update_status(job_id, JobStatus.SUBMITTING,
        expected_status=JobStatus.WAITING_CAPTCHA, expected_captcha_id=captcha_id)
    if updated is None:
        return {"ok": False, "error": "Job changed before submission."}
    await sio.emit("job:status", updated.model_dump(mode="json", by_alias=True), room=f"job:{job_id}", namespace="/ui")
    # Filling the official form and verifying that VAHAN did not refresh the
    # CAPTCHA can take longer than a browser Socket.IO ACK timeout. Return the
    # UI ACK now; the background task will publish a real FAILED state if the
    # browser worker rejects or times out.
    sio.start_background_task(
        _forward_captcha_submission,
        job_id,
        job.runner_id,
        runner.socket_id,
        captcha_id,
        text1,
    )
    return {"ok": True, "accepted": True}


@sio.on("captcha:refresh", namespace="/ui")
async def refresh_captcha(_sid: str, payload: dict) -> dict:
    user = await authenticated_ui(_sid)
    if not user:
        return {"ok": False, "error": "Authentication required."}
    """Ask the browser worker to click VAHAN's official CAPTCHA refresh control."""
    try:
        job_id = UUID(str(payload["jobId"]))
        captcha_id = str(payload["captchaId"])
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "Invalid CAPTCHA refresh request."}

    job = await services.jobs.get(job_id)
    if not job or (user["role"] != "admin" and job.owner_username != user["username"]):
        return {"ok": False, "error": "Job not found."}
    if job.status != JobStatus.WAITING_CAPTCHA:
        return {"ok": False, "error": "Job is not waiting for CAPTCHA."}
    if job.captcha_id != captcha_id:
        return {"ok": False, "error": "CAPTCHA has changed or expired."}

    runner = await services.runners.get(job.runner_id)
    if not runner:
        return {"ok": False, "error": "Runner is offline."}
    try:
        acknowledgement = await sio.call(
            "captcha:refresh",
            {"jobId": str(job_id), "captchaId": captcha_id},
            to=runner.socket_id,
            namespace="/runner",
            timeout=CAPTCHA_REFRESH_TIMEOUT_SECONDS,
        )
    except SocketIOTimeoutError:
        return {"ok": False, "error": "Browser worker did not refresh CAPTCHA in time."}
    except Exception as error:  # pragma: no cover - runner transport boundary
        return {"ok": False, "error": f"Could not refresh CAPTCHA through browser worker: {error}"}

    if not acknowledgement or not acknowledgement.get("ok"):
        return {"ok": False, "error": (acknowledgement or {}).get("error", "Browser worker rejected CAPTCHA refresh.")}

    refreshed = await services.jobs.get(job_id)
    if not refreshed or refreshed.status != JobStatus.WAITING_CAPTCHA:
        return {"ok": False, "error": "CAPTCHA refresh did not complete."}
    if not refreshed.captcha_id or not refreshed.captcha_image_data_url:
        return {"ok": False, "error": "VAHAN did not return a CAPTCHA image."}
    return {
        "ok": True,
        "captcha": {
            "jobId": str(job_id),
            "captchaId": refreshed.captcha_id,
            "imageDataUrl": refreshed.captcha_image_data_url,
        },
    }


async def authenticated_ui(sid):
    try:
        session = await sio.get_session(sid, namespace="/ui")
        user = await authenticate_access_token(session.get("token", ""))
        if not user:
            await sio.disconnect(sid, namespace="/ui")
        return user
    except KeyError:
        return None

async def invalidate_session(session_id):
    for sid, stored_id in list(_ui_sessions.items()):
        if stored_id == session_id:
            await sio.disconnect(sid, namespace="/ui")

async def invalidate_user(username):
    for sid in list(_ui_sessions):
        try:
            session = await sio.get_session(sid, namespace='/ui')
            if session.get('username') == username:
                await sio.disconnect(sid, namespace='/ui')
        except KeyError:
            continue
