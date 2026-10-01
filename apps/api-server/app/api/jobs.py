from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status

from app.excel_storage import report_session_dir
from app.models.job import CreateJobRequest, Job, JobStatus, ReportSource
from app.models.runner import RunnerStatus
from app.realtime.server import sio
from app.services import services

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post(
    "",
    response_model=Job,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
)
async def create_job(command: CreateJobRequest) -> Job:
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
    if report_session_dir(session_id, create=True) is None:
        raise HTTPException(status_code=500, detail="Could not create a folder for this run's Excel reports.")

    job = Job(
        runnerId=command.runner_id,
        sessionId=session_id,
        filters=command.filters,
        scenarioName=command.scenario_name,
        source=command.source,
        status=JobStatus.ASSIGNED,
    )
    job = await services.jobs.create(job)
    await services.runners.set_job(command.runner_id, str(job.id))

    await sio.emit(
        "job:assigned",
        {
            "jobId": str(job.id),
            "filters": job.filters.extension_payload(),
            "scenarioName": job.scenario_name,
            "source": job.source.value,
        },
        room=f"runner:{command.runner_id}",
        namespace="/runner",
    )
    return job


@router.get("/{job_id}", response_model=Job, response_model_by_alias=True)
async def get_job(job_id: UUID) -> Job:
    job = await services.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@router.post("/{job_id}/cancel", response_model=Job, response_model_by_alias=True)
async def cancel_job(job_id: UUID) -> Job:
    job = await services.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status in {JobStatus.COMPLETED, JobStatus.NO_DATA, JobStatus.FAILED, JobStatus.CANCELLED}:
        raise HTTPException(status_code=409, detail="Job is already in a terminal state.")

    updated = await services.jobs.transition_status(job_id, JobStatus.CANCELLED)
    if updated is None:
        raise HTTPException(status_code=409, detail="Job is already in a terminal state.")
    await services.runners.set_job(job.runner_id, None)
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
