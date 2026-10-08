from datetime import date, datetime, timezone
from uuid import uuid4
import asyncio
from sqlalchemy import insert,select
from app.db import engine,schema as db
from app.repositories.postgres import now
from app.repositories import ui_contract
from app.repositories.filter_profiles import reserve_options_runner
from app.models.filter_profile import StrictModel
from pydantic import Field

from fastapi import APIRouter, HTTPException, Query, Request, status
from app.access import require_admin
from fastapi.responses import Response

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
async def update_ui_health_schedule(command: UiHealthScheduleUpdate, request: Request) -> UiHealthSchedule:
    require_admin(request)
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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requested browser runner was not found.")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No browser runner is connected to run the check.",
        )
    if runner.status == RunnerStatus.RECONNECTING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The browser runner is reconnecting.")

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
async def receive_ui_health_log(command: UiHealthLogRequest, request: Request) -> UiHealthLogResponse:
    validation=None
    if 'observedControls' in command.health_check:
        identity=request.headers.get('x-vahan-runner-id')
        if not getattr(request.state,'authenticated_runner',False) or identity!=command.runner_id or not await services.runners.get(identity):
            raise HTTPException(403,'Only the authenticated runner can submit DOM evidence.')
        validation=await ui_contract.evaluate(command.health_check,command.runner_id)
        command.health_check.update({key:validation[key] for key in ('status','reports','errorCount')})
        command.health_check['contractValidation']=validation
        if not validation['allowed']:
            command.health_check['error']='UI_HEALTH_BLOCKED: '+str(validation['reports'][0]['title'])
    result = await services.ui_health_logs.append(
        command.health_check,
        page_url=command.page_url,
    )
    response = UiHealthLogResponse.model_validate({**result,'validation':validation})
    # Publish after committing the SQL log so refresh/Copy error includes it.
    if validation:
        state=await ui_contract.current()
        await sio.emit('ui-health:blocked' if state['blocked'] else 'ui-health:verified',state,namespace='/ui')
    if command.health_check.get('trigger') == 'scheduled':
        await services.ui_health.record_check()
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
async def download_ui_health_report(file_name: str) -> Response:
    report_path = await services.ui_health_logs.resolve_report(file_name)
    if report_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report file not found.")
    return Response(report_path, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{file_name}"'})


class PreflightInput(StrictModel):
    runner_ids:list[str]=Field(alias='runnerIds',min_length=1,max_length=10)


@router.get('/contract')
async def current_contract():
    return await ui_contract.current()


@router.get('/status')
async def contract_status():
    state=await ui_contract.current()
    async with engine.connect() as c:
        latest=(await c.execute(select(db.ui_preflight_checks).order_by(db.ui_preflight_checks.c.created_at.desc()).limit(1))).mappings().first()
    return {**state,'latestPreflight':dict(latest) if latest else None}


@router.post('/preflight')
async def preflight(command:PreflightInput,request:Request):
    ids=list(dict.fromkeys(command.runner_ids))
    if len(ids)!=len(command.runner_ids):raise HTTPException(400,'Worker IDs must be unique.')
    known={runner.id for runner in await services.runners.list()}
    check_id=str(uuid4());semaphore=asyncio.Semaphore(2)
    async def check(runner_id):
        async with semaphore:
            if runner_id not in known:
                return {'allowed':False,'runnerId':runner_id,'reports':[{'code':'WORKER_NOT_REGISTERED','title':'The selected worker is not registered; retry after it is connected.'}]}
            try:
                async with reserve_options_runner(runner_id,request.state.authenticated_user) as (socket_id,token):
                    last=None
                    for attempt in range(2):
                        request_id=str(uuid4())
                        try:
                            result=await sio.call('ui-health:preflight',{'requestId':request_id,'trigger':'preflight'},to=socket_id,namespace='/runner',timeout=55)
                            async with engine.connect() as c:
                                evidence=await c.scalar(select(db.ui_health_checks.c.payload).where(db.ui_health_checks.c.id==request_id))
                            last=((evidence or {}).get('healthCheck') or {}).get('contractValidation')
                            if not isinstance(result,dict) or not result.get('ok') or not last or last.get('runnerId')!=runner_id:
                                last={'allowed':False,'runnerId':runner_id,'reports':[{'code':'PREFLIGHT_NO_ACK','title':'Worker did not return SQL-validated health evidence.'}]}
                            if last.get('allowed'):return {**last,'attempts':attempt+1}
                        except Exception as error:
                            last={'allowed':False,'runnerId':runner_id,'reports':[{'code':'PREFLIGHT_FAILED','title':str(error) or type(error).__name__}]}
                    return {**last,'attempts':2}
            except Exception as error:
                return {'allowed':False,'runnerId':runner_id,'reports':[{'code':'PREFLIGHT_FAILED','title':str(error)}]}
    reports=await asyncio.gather(*(check(runner) for runner in ids))
    state=await ui_contract.current()
    for report in reports:
        if report.get('allowed') and report.get('versionId')!=state['versionId']:
            report.update(allowed=False,reports=[{'code':'SQL_CONTRACT_VERSION_CHANGED','title':'Workers observed different DOM versions. Recheck all selected workers before loading Maker data.'}])
    allowed=not state['blocked'] and all(report.get('allowed') and report.get('versionId')==state['versionId'] for report in reports)
    async with engine.begin() as c:
        await c.execute(insert(db.ui_preflight_checks).values(id=check_id,owner_username=request.state.authenticated_user,
            runner_ids=ids,version_id=state['versionId'],status='PASS' if allowed else 'BLOCKED',reports=reports,created_at=now()))
    response={'allowed':allowed,'preflightId':check_id,'revision':state['revision'],'versionId':state['versionId'],'reports':reports}
    if not allowed:
        await sio.emit('ui-health:blocked',response,namespace='/ui')
        raise HTTPException(409,{'code':'UI_HEALTH_BLOCKED','message':'Preflight failed; no Maker data or tasks were loaded. Open UI Health and copy the error for dev.','diagnostics':response})
    await sio.emit('ui-health:verified',response,namespace='/ui')
    return response
