import asyncio
import time
from uuid import UUID

from socketio.exceptions import TimeoutError as SocketIOTimeoutError

from app.models.job import JobStatus, can_transition
from app.realtime.server import sio
from app.security import access_token_expiry, verify_access_token
from app.services import services
from app.ocr import ocr_to_text


CAPTCHA_FORWARD_TIMEOUT_SECONDS = 45
CAPTCHA_REFRESH_TIMEOUT_SECONDS = 20
_ui_token_expiry_tasks: dict[str, asyncio.Task] = {}


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
    await services.runners.set_job(runner_id, None)
    await sio.emit(
        "job:status",
        failed.model_dump(mode="json", by_alias=True),
        room=f"job:{job_id}",
        namespace="/ui",
    )


async def _forward_captcha_submission(
    job_id: UUID,  # UUID của công việc đang chờ gửi mã CAPTCHA.
    runner_id: str,  # ID của extension runner để cập nhật lỗi nếu gửi thất bại.
    runner_socket_id: str,  # Socket ID của extension nhận sự kiện.
    captcha_id: str,  # ID ảnh CAPTCHA mà người dùng đã nhập mã.
    text1: str,  # Giá trị CAPTCHA nhận từ giao diện qua biến text1.
) -> None:  # Hàm chạy nền, không trả về dữ liệu.
    """Chuyển mã CAPTCHA tới extension ngoài thời gian chờ phản hồi của giao diện."""  # Nêu mục đích của hàm.
    try:  # Bắt đầu gửi mã và chờ extension xác nhận đã xử lý.
        acknowledgement = await sio.call(  # Gửi sự kiện Socket.IO và chờ phản hồi từ extension.
            "captcha:submit",  # Tên sự kiện mà extension đang lắng nghe.
            {  # Tạo dữ liệu gửi kèm sự kiện.
                "jobId": str(job_id),  # Gửi ID công việc dưới dạng chuỗi.
                "captchaId": captcha_id,  # Gửi ID CAPTCHA để đối chiếu ảnh hiện hành.
                "value": ocr_to_text.OCR_RESULT or text1,  # Gán kết quả OCR hoặc text1 vào trường value.
            },  # Kết thúc dữ liệu sự kiện.
            to=runner_socket_id,  # Chỉ gửi tới đúng kết nối của extension runner.
            namespace="/runner",  # Gửi trên namespace dành cho runner.
            timeout=CAPTCHA_FORWARD_TIMEOUT_SECONDS,  # Giới hạn thời gian chờ extension phản hồi.
        )  # Hoàn tất lệnh gửi sự kiện và nhận xác nhận.
    except SocketIOTimeoutError:  # Xử lý trường hợp extension không phản hồi đúng hạn.
        await _fail_captcha_submission(  # Đánh dấu công việc thất bại và thông báo lỗi lên giao diện.
            job_id,  # Chỉ rõ công việc cần cập nhật trạng thái.
            runner_id,  # Chỉ rõ runner liên quan đến lỗi.
            "The extension did not complete the CAPTCHA action within the allowed time.",  # Timeout reason.
        )  # Hoàn tất cập nhật lỗi cho công việc.
        return  # Dừng hàm vì đã xử lý xong lỗi timeout.
    except Exception as error:  # pragma: no cover - xử lý dự phòng cho lỗi trong tác vụ nền.
        await _fail_captcha_submission(  # Đánh dấu công việc thất bại khi phát sinh lỗi khác.
            job_id,  # Chỉ rõ công việc cần cập nhật trạng thái.
            runner_id,  # Chỉ rõ runner liên quan đến lỗi.
            f"Could not send CAPTCHA to the extension: {error}",  # Record the error for review.
        )  # Hoàn tất cập nhật lỗi cho công việc.
        return  # Dừng hàm sau khi lỗi đã được xử lý.

    if acknowledgement and acknowledgement.get("ok"):  # Kiểm tra extension có xác nhận xử lý thành công không.
        return  # Kết thúc bình thường khi extension xác nhận thành công.
    error = (acknowledgement or {}).get("error", "The extension rejected the CAPTCHA submission.")  # Use the returned or default error.
    await _fail_captcha_submission(job_id, runner_id, error)  # Cập nhật trạng thái thất bại và gửi lỗi lên giao diện.


@sio.event(namespace="/ui")
async def connect(_sid: str, _environ: dict, auth: dict | None) -> bool:
    auth = auth or {}
    token = str(auth.get("token", ""))
    username = verify_access_token(token)
    expires_at = access_token_expiry(token)
    if not username:
        return False
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
    task = _ui_token_expiry_tasks.pop(sid, None)
    if task and task is not asyncio.current_task():
        task.cancel()


@sio.on("ui:subscribe-job", namespace="/ui")
async def subscribe_job(sid: str, payload: dict) -> dict:
    try:
        job_id = UUID(str(payload["jobId"]))
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "Invalid job ID."}
    job = await services.jobs.get(job_id)
    if not job:
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
    try:
        return await sio.call(
            "runner:options",
            request,
            to=runner.socket_id,
            namespace="/runner",
            timeout=20,
        )
    except SocketIOTimeoutError:
        return {"ok": False, "error": "Runner did not return VAHAN options in time."}


@sio.on("captcha:submitted", namespace="/ui")
async def submit_captcha(_sid: str, payload: dict) -> dict:
    try:
        job_id = UUID(str(payload["jobId"]))
        captcha_id = str(payload["captchaId"])
        text1 = str(payload.get("text1", payload.get("value", ""))).strip()
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "Invalid CAPTCHA submission."}
    if len(text1) != 6:
        return {"ok": False, "error": "CAPTCHA must contain exactly 6 characters."}

    job = await services.jobs.get(job_id)
    if not job:
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

    updated = await services.jobs.update_status(job_id, JobStatus.SUBMITTING)
    await sio.emit("job:status", updated.model_dump(mode="json", by_alias=True), room=f"job:{job_id}", namespace="/ui")
    # Filling the official form and verifying that VAHAN did not refresh the
    # CAPTCHA can take longer than a browser Socket.IO ACK timeout. Return the
    # UI ACK now; the background task will publish a real FAILED state if the
    # extension rejects or times out.
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
    """Ask the extension to click VAHAN's official CAPTCHA refresh control."""
    try:
        job_id = UUID(str(payload["jobId"]))
        captcha_id = str(payload["captchaId"])
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "Invalid CAPTCHA refresh request."}

    job = await services.jobs.get(job_id)
    if not job:
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
        return {"ok": False, "error": "Extension did not refresh CAPTCHA in time."}
    except Exception as error:  # pragma: no cover - runner transport boundary
        return {"ok": False, "error": f"Could not refresh CAPTCHA through extension: {error}"}

    if not acknowledgement or not acknowledgement.get("ok"):
        return {"ok": False, "error": (acknowledgement or {}).get("error", "Extension rejected CAPTCHA refresh.")}

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
