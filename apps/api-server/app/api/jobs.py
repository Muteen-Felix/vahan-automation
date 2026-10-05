from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Query, Request, status

from app.access import owner_filter, require_owner
from app.models.job import CreateJobRequest, Job, JobStatus, ReportSource
from app.models.runner import RunnerStatus
from app.realtime.server import sio
from app.services import services
from app.models.report_result import ReportResultRequest
from app.repositories.report_results import commit_report_result, get_report_result

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post('/{job_id}/report-result')
async def save_report_result(job_id: UUID, command: ReportResultRequest, request: Request,
    runner_id: str | None = Header(default=None, alias='X-VAHAN-RUNNER-ID')):
    if not getattr(request.state, 'authenticated_runner', False) or not runner_id:
        raise HTTPException(403, 'Only the assigned browser runner can save a result.')
    try:
        job = await commit_report_result(job_id, runner_id, command)
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error
    except ValueError as error:
        raise HTTPException(404 if str(error) == 'Job not found.' else 409, str(error)) from error
    from app.realtime.report_notifications import notify_report_saved
    await notify_report_saved(job)
    return {'ok': True, 'status': job.status.value, 'jobId': str(job_id)}


@router.get('/{job_id}/report-result')
async def read_report_result(job_id: UUID, request: Request,
    offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=1000)):
    job = await services.jobs.get(job_id)
    if not job:
        raise HTTPException(404, 'Job not found.')
    require_owner(request, job.owner_username)
    result = await get_report_result(job_id, offset, limit)
    if result is None:
        raise HTTPException(404, 'Report result not found.')
    return result


@router.post(
    "",
    response_model=Job,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
)
async def create_job(command: CreateJobRequest, request: Request) -> Job:
    if command.source != ReportSource.NEW:
        raise HTTPException(status_code=410, detail="The legacy VAHAN report source is no longer supported.")
    runner = await services.runners.get(command.runner_id)
    if not runner:
        raise HTTPException(status_code=404, detail="Runner is offline or does not exist.")
    if runner.source != ReportSource.NEW:
        raise HTTPException(status_code=409, detail="This runner is not supported for report execution.")
    if runner.status == RunnerStatus.RECONNECTING:
        raise HTTPException(status_code=409, detail="Runner is reconnecting.")
    if runner.current_job_id:
        raise HTTPException(status_code=409, detail="Runner is already processing another job.")

    session_id = command.session_id or uuid4()
    retry_of = None
    if command.retry_of_job_id:
        retry_of = await services.jobs.get(command.retry_of_job_id)
        if not retry_of:
            raise HTTPException(404, "Original failed job not found.")
        require_owner(request, retry_of.owner_username)
        if retry_of.owner_username != request.state.authenticated_user:
            raise HTTPException(409, "Retry must belong to the current user.")
        if retry_of.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
            raise HTTPException(409, "Only a failed or stopped job can be retried.")
        if command.session_id and command.session_id != retry_of.session_id:
            raise HTTPException(409, "Retry must remain in the original report session.")
        if command.filters != retry_of.filters or command.source != retry_of.source:
            raise HTTPException(409, "Retry must use exactly the original filters and source.")
        if (command.update_kind != retry_of.update_kind or command.update_run_id != retry_of.update_run_id
                or command.update_task_id != retry_of.update_task_id):
            raise HTTPException(409, "Retry must preserve the Maker update task.")
        session_id = retry_of.session_id

    job = Job(
        runnerId=command.runner_id,
        sessionId=session_id,
        filters=command.filters,
        scenarioName=command.scenario_name,
        source=command.source,
        updateKind=command.update_kind,
        updateRunId=command.update_run_id,
        updateTaskId=command.update_task_id,
        status=JobStatus.ASSIGNED,
        ownerUsername=request.state.authenticated_user,
        retryOfJobId=retry_of.id if retry_of else None,
        caseId=(retry_of.case_id or retry_of.id) if retry_of else None,
    )
    try:
        job = await services.jobs.assign(job)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    if job is None:
        raise HTTPException(status_code=409, detail="Runner was assigned another job or disconnected.")

    await sio.emit(
        "job:assigned",
        {
            "jobId": str(job.id),
            "filters": job.filters.runner_payload(),
            "scenarioName": job.scenario_name,
            "source": job.source.value,
        },
        room=f"runner:{command.runner_id}",
        namespace="/runner",
    )
    return job


@router.get("/{job_id}", response_model=Job, response_model_by_alias=True)
async def get_job(job_id: UUID, request: Request) -> Job:
    job = await services.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    require_owner(request, job.owner_username)
    return job


@router.post("/{job_id}/cancel", response_model=Job, response_model_by_alias=True)
async def cancel_job(job_id: UUID, request: Request) -> Job:
    job = await services.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    require_owner(request, job.owner_username)
    if job.status in {JobStatus.COMPLETED, JobStatus.NO_DATA, JobStatus.FAILED, JobStatus.CANCELLED}:
        raise HTTPException(status_code=409, detail="Job is already in a terminal state.")

    updated = await services.jobs.transition_status(job_id, JobStatus.CANCELLED)
    if updated is None:
        raise HTTPException(status_code=409, detail="Job is already in a terminal state.")
    await services.runners.release_job(job.runner_id, str(job.id))
    await sio.emit(
        "job:cancelled",
        {"jobId": str(job_id)},
        room=f"runner:{job.runner_id}",
        namespace="/runner",
    )
    await sio.emit(
        "job:status",
        updated.model_dump(mode="json", by_alias=True),
        room=f"job:{job_id}",
        namespace="/ui",
    )
    return updated


@router.get("", response_model=list[Job], response_model_by_alias=True)
async def list_jobs(request: Request):
    return await services.jobs.list_all(owner_filter(request))
