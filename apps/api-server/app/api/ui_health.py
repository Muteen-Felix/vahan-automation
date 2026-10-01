from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse

from app.models.ui_health import (
    UiHealthCheckNowRequest,
    UiHealthCheckNowResponse,
    UiHealthLogRequest,
    UiHealthLogResponse,
    UiHealthReportsResponse,
    UiHealthSchedule,
    UiHealthScheduleUpdate,
)
from app.models.runner import Runner, RunnerStatus
from app.realtime.server import sio
from app.services import services


router = APIRouter(prefix="/ui-health", tags=["ui-health"])


def _normalise_date(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date must use YYYY-MM-DD format.",
        ) from error


@router.get(
    "/schedule",
    response_model=UiHealthSchedule,
    response_model_by_alias=True,
)
async def get_ui_health_schedule() -> UiHealthSchedule:
    return await services.ui_health.get()


@router.put(
    "/schedule",
    response_model=UiHealthSchedule,
    response_model_by_alias=True,
)
async def update_ui_health_schedule(command: UiHealthScheduleUpdate) -> UiHealthSchedule:
    schedule = await services.ui_health.update(command.interval_days)
    await sio.emit(
        "ui-health:schedule-updated",
        schedule.model_dump(mode="json", by_alias=True),
        namespace="/runner",
    )
    return schedule


def _select_runner(runners: list[Runner], requested_runner_id: str | None) -> Runner | None:
    if requested_runner_id:
        return next((runner for runner in runners if runner.id == requested_runner_id), None)

    connected = [runner for runner in runners if runner.status != RunnerStatus.RECONNECTING]
    # Prefer an idle runner, but a busy runner can still open the isolated,
    # read-only health-check tab without interrupting the active report job.
    return (
        next((runner for runner in connected if runner.status == RunnerStatus.ONLINE and not runner.current_job_id), None)
        or next((runner for runner in connected if runner.status == RunnerStatus.ONLINE), None)
        or next((runner for runner in connected if runner.status == RunnerStatus.BUSY), None)
    )


@router.post(
    "/run-now",
    response_model=UiHealthCheckNowResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_ui_health_check_now(
    command: UiHealthCheckNowRequest | None = None,
) -> UiHealthCheckNowResponse:
    requested_runner_id = command.runner_id if command else None
    runner = _select_runner(await services.runners.list(), requested_runner_id)
    if runner is None:
        if requested_runner_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requested extension runner was not found.")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No extension runner is connected to run the check.",
        )
    if runner.status == RunnerStatus.RECONNECTING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The extension runner is reconnecting.")

    request_id = str(uuid4())
    requested_at = datetime.now(timezone.utc)
    await sio.emit(
        "ui-health:run-now",
        {
            "requestId": request_id,
            "requestedAt": requested_at.isoformat(),
            "trigger": "manual-web",
        },
        room=f"runner:{runner.id}",
        namespace="/runner",
    )
    return UiHealthCheckNowResponse(
        requestId=request_id,
        runnerId=runner.id,
        runnerName=runner.name,
        requestedAt=requested_at,
    )


@router.post(
    "/logs",
    response_model=UiHealthLogResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
)
async def receive_ui_health_log(command: UiHealthLogRequest) -> UiHealthLogResponse:
    result = await services.ui_health_logs.append(
        command.health_check,
        page_url=command.page_url,
    )
    response = UiHealthLogResponse.model_validate(result)
    await sio.emit(
        "ui-health:log-received",
        {
            **response.model_dump(mode="json", by_alias=True),
            "status": str(command.health_check.get("status") or "CHECK_ERROR"),
            "checkedAt": str(command.health_check.get("checkedAt") or ""),
            "trigger": str(command.health_check.get("trigger") or ""),
        },
        namespace="/ui",
    )
    return response


@router.get(
    "/reports",
    response_model=UiHealthReportsResponse,
    response_model_by_alias=True,
)
async def list_ui_health_reports(
    date_filter: str | None = Query(
        default=None,
        alias="date",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    ),
) -> UiHealthReportsResponse:
    reports = await services.ui_health_logs.list_reports(_normalise_date(date_filter))
    return UiHealthReportsResponse.model_validate(reports)


@router.get("/reports/{file_name}/download")
async def download_ui_health_report(file_name: str) -> FileResponse:
    report_path = await services.ui_health_logs.resolve_report(file_name)
    if report_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report file not found.")
    return FileResponse(
        report_path,
        media_type="text/csv",
        filename=report_path.name,
    )
