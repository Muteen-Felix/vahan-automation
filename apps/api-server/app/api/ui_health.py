from datetime import date, datetime, timezone
from uuid import uuid4
import asyncio
from sqlalchemy import insert,select
from app.db import engine,schema as db
from app.repositories.postgres import now
from app.repositories import ui_contract
from app.repositories.filter_profiles import PreflightUnavailable, reserve_preflight_runners
from app.models.filter_profile import StrictModel
from app.access import require_admin
from pydantic import Field

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import Response

from app.models.ui_health import (
    UiHealthLogRequest,
    UiHealthLogResponse,
    UiHealthReportsResponse,
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
    runner_ids:list[str]=Field(alias='runnerIds',min_length=1)


@router.get('/contract')
async def current_contract():
    return await ui_contract.current()


@router.get('/status')
async def contract_status():
    await ui_contract.reclassify_legacy_availability_preflights()
    state=await ui_contract.current()
    async with engine.connect() as c:
        latest=(await c.execute(select(db.ui_preflight_checks).order_by(db.ui_preflight_checks.c.created_at.desc()).limit(1))).mappings().first()
    return {**state,'latestPreflight':dict(latest) if latest else None,'gateGeneration':await ui_contract.gate_generation()}


@router.post('/preflight')
async def preflight(command:PreflightInput,request:Request):
    ids=list(dict.fromkeys(command.runner_ids))
    if len(ids)!=len(command.runner_ids):raise HTTPException(400,'Worker IDs must be unique.')
    from app.worker_pool import pool_value
    async with engine.connect() as connection:
        concurrency = (await pool_value(connection))['desiredCount']
    check_id=str(uuid4());semaphore=asyncio.Semaphore(min(2, max(1, concurrency)))
    # Evidence is only valid at the gate generation it was started in (retire/invalidate bump it).
    start_generation=await ui_contract.gate_generation()
    waiting=False

    def deferred(runner_id,code,title):
        return {'allowed':False,'waiting':True,'runnerId':runner_id,'reports':[{'code':code,'title':title}]}

    async def inspect(runner_id,reservations):
        socket_id,_token=reservations[runner_id]
        last=None
        for attempt in range(2):
            request_id=str(uuid4())
            # Issued under the worker reservation, so a larger sequence means a later check.
            check_seq=await ui_contract.next_check_seq()
            try:
                result=await sio.call('ui-health:preflight',{'requestId':request_id,'trigger':'preflight','checkSeq':check_seq},to=socket_id,namespace='/runner',timeout=55)
            except Exception as error:
                return deferred(runner_id,'WORKER_NO_RESPONSE',
                    f'{runner_id} did not answer the website check. The check will retry automatically.')
            if isinstance(result,dict) and result.get('code') in {'RUNNER_BUSY','WORKER_OFFLINE'}:
                return deferred(runner_id,result.get('code'),'The worker is finishing another operation. The check will retry automatically.')
            if not isinstance(result,dict) or not result.get('ok'):
                return deferred(runner_id,'PREFLIGHT_NO_ACK',
                    f'{runner_id} did not return a completed SQL-backed website check. The check will retry automatically.')
            try:
                async with engine.connect() as c:
                    evidence=await c.scalar(select(db.ui_health_checks.c.payload).where(db.ui_health_checks.c.id==request_id))
            except Exception:
                return deferred(runner_id,'PREFLIGHT_SQL_UNAVAILABLE',
                    'The SQL evidence could not be read. The website check will retry automatically.')
            last=((evidence or {}).get('healthCheck') or {}).get('contractValidation')
            if not isinstance(last,dict) or last.get('runnerId')!=runner_id:
                return deferred(runner_id,'PREFLIGHT_NO_SQL_EVIDENCE',
                    f'{runner_id} did not provide matching SQL-validated website evidence. The check will retry automatically.')
            if last.get('allowed'):
                return {**last,'attempts':attempt+1}
        return {**last,'attempts':2}

    async def check(runner_id):
        async with semaphore:
            try:
                # The connected pool can be larger than the task concurrency.
                # Reserve only workers currently being checked, while requiring
                # matching SQL evidence for the entire requested pool below.
                async with reserve_preflight_runners([runner_id],request.state.authenticated_user) as reservations:
                    return await inspect(runner_id,reservations)
            except PreflightUnavailable as error:
                return deferred(runner_id,error.code,str(error))

    reports=await asyncio.gather(*(check(runner) for runner in ids))
    state=await ui_contract.current()
    for report in reports:
        if report.get('allowed') and report.get('versionId')!=state['versionId']:
            report.update(allowed=False,reports=[{'code':'SQL_CONTRACT_VERSION_CHANGED','title':'Workers observed different DOM versions. Recheck all selected workers before loading Maker data.'}])
    waiting=waiting or any(report.get('waiting') for report in reports)
    allowed=not waiting and not state['blocked'] and all(report.get('allowed') and report.get('versionId')==state['versionId'] for report in reports)
    status_value='PASS' if allowed else 'WAITING' if waiting and not state['blocked'] and not any(not report.get('allowed') and not report.get('waiting') for report in reports) else 'BLOCKED'
    if await ui_contract.gate_generation()!=start_generation:
        # The gate was retired/invalidated while workers were being checked: this evidence belongs
        # to an older generation. Never report it as allowed.
        allowed=False;waiting=True;status_value='WAITING'
        for report in reports:
            if report.get('allowed'):report.update(allowed=False,waiting=True,reports=[{'code':'GATE_GENERATION_CHANGED','title':'The gate was reset while the website check ran. The check will retry automatically.'}])
    async with engine.begin() as c:
        await c.execute(insert(db.ui_preflight_checks).values(id=check_id,owner_username=request.state.authenticated_user,
            runner_ids=ids,version_id=state['versionId'],status=status_value,reports=reports,created_at=now(),
            gate_generation=start_generation))
    response={'allowed':allowed,'preflightId':check_id,'revision':state['revision'],'versionId':state['versionId'],'reports':reports}
    if status_value=='WAITING':
        response.update(status='WAITING',retryAfterMs=5000)
        await sio.emit('ui-health:waiting',response,namespace='/ui')
        raise HTTPException(409,{'code':'PREFLIGHT_WAITING','message':'Waiting for all selected workers to be online and idle. No website change was recorded; the check will retry automatically.','retryAfterMs':5000,'diagnostics':response})
    if not allowed:
        await sio.emit('ui-health:blocked',response,namespace='/ui')
        raise HTTPException(409,{'code':'UI_HEALTH_BLOCKED','message':'Preflight failed; no Maker data or tasks were loaded. Open UI Health and copy the error for dev.','diagnostics':response})
    await sio.emit('ui-health:verified',response,namespace='/ui')
    return response


class GateReason(StrictModel):
    reason:str=Field(min_length=1,max_length=500)


def _gate_http_error(error):
    return HTTPException(error.status_code,{'code':error.code,'message':error.message})


async def _publish_gate_state():
    state=await ui_contract.current()
    await sio.emit('ui-health:blocked' if state['blocked'] else 'ui-health:verified',state,namespace='/ui')
    return state


@router.post('/admin/runner-errors/{runner_id}/retire')
async def admin_retire_runner_error(runner_id:str,command:GateReason,request:Request):
    """Retire the stored error of a worker that is gone. Admin only; every precondition is
    verified inside the transaction and the audit event is written in that same transaction."""
    require_admin(request)
    try:
        result=await ui_contract.retire_runner_error(request.state.authenticated_user,runner_id,command.reason)
    except ui_contract.GateOpError as error:
        raise _gate_http_error(error) from error
    state=await _publish_gate_state()
    return {**result,'blocked':state['blocked'],'blockedRunnerIds':state['blockedRunnerIds']}


@router.post('/admin/gates/invalidate')
async def admin_invalidate_gates(command:GateReason,request:Request):
    """Make every existing PASS preflight unusable (before a rollback). Admin only, audited."""
    require_admin(request)
    try:
        result=await ui_contract.invalidate_gates(request.state.authenticated_user,command.reason)
    except ui_contract.GateOpError as error:
        raise _gate_http_error(error) from error
    await _publish_gate_state()
    return result
