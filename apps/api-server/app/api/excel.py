import asyncio
import re
import zipfile
from pathlib import Path
from uuid import UUID, uuid4
from weakref import WeakValueDictionary

import aiofiles
from fastapi import APIRouter, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.excel_storage import report_session_dir, session_folder_name, stored_excel_path, stored_no_data_path
from app.models.job import Job, JobStatus, ReportSource
from app.services import services

router = APIRouter(prefix="/jobs", tags=["excel"])

_report_dir = Path(settings.excel_report_dir)
_upload_locks: WeakValueDictionary[UUID, asyncio.Lock] = WeakValueDictionary()


def _validate_workbook(path: Path) -> None:
    try:
        if not zipfile.is_zipfile(path):
            raise HTTPException(status_code=400, detail="The uploaded file is not a valid Excel workbook.")
        with zipfile.ZipFile(path) as workbook:
            if "xl/workbook.xml" not in workbook.namelist() or workbook.testzip() is not None:
                raise HTTPException(status_code=400, detail="The uploaded Excel workbook is damaged.")
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise HTTPException(status_code=400, detail="The uploaded Excel workbook is damaged or unsupported.") from exc


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|\r\n\t]', "_", name).strip()
    return cleaned or "report"


def _generate_excel_filename(job: Job, uploaded_filename: str | None = None) -> str:
    if job.scenario_name and job.scenario_name.startswith("Maker Month Wise Data  of ") and job.filters.states and job.filters.rtos:
        return f"{_sanitize_filename(job.scenario_name)}.xlsx"
    dt = job.created_at.astimezone() if job.created_at.tzinfo else job.created_at
    timestamp = dt.strftime("%Y%m%d_%H%M%S")

    if job.scenario_name:
        base_name = _sanitize_filename(job.scenario_name)
    elif uploaded_filename and uploaded_filename != "report.xlsx":
        clean_stem = _sanitize_filename(Path(uploaded_filename).stem)
        base_name = clean_stem
    else:
        base_name = f"report_{str(job.id)[:8]}"

    return f"{base_name}_{timestamp}_{str(job.id)[:8]}.xlsx"


class VerifyReportsRequest(BaseModel):
    file_names: list[str] = Field(alias="fileNames", max_length=500)
    session_ids: dict[str, UUID] = Field(default_factory=dict, alias="sessionIds")


def _excel_path(job: Job) -> Path:
    if job.excel_file_name:
        path = stored_excel_path(job.excel_file_name, job.session_id)
        if path:
            return path
    # Backward compatibility fallback
    return _report_dir / f"{job.id}.xlsx"


@router.get("/reports", status_code=status.HTTP_200_OK)
async def list_exported_reports() -> list[dict]:
    jobs = await services.jobs.list_all()
    reports = []
    for job in jobs:
        if job.status == JobStatus.COMPLETED and stored_excel_path(job.excel_file_name, job.session_id):
            reports.append({
                "jobId": str(job.id),
                "scenarioName": job.scenario_name or job.excel_file_name,
                "fileName": job.excel_file_name,
                "fileSize": job.excel_file_size or 0,
                "createdAt": job.created_at.isoformat(),
                "sessionFolder": str(path.parent.relative_to(_report_dir)) if (path := stored_excel_path(job.excel_file_name, job.session_id)) else session_folder_name(job.session_id),
                "downloadUrl": f"/api/jobs/{job.id}/excel",
                "source": job.source.value,
            })
    reports.sort(key=lambda r: r["createdAt"], reverse=True)
    return reports


@router.get("/reports/sessions", status_code=status.HTTP_200_OK)
async def list_exported_report_sessions() -> list[dict]:
    """Return report jobs grouped by their run session, including no-data and failed cases."""
    jobs = await services.jobs.list_all()
    sessions: dict[str, dict] = {}
    folder_names: dict[str, str | None] = {}
    terminal_statuses = {JobStatus.COMPLETED, JobStatus.NO_DATA, JobStatus.FAILED, JobStatus.CANCELLED}

    for job in jobs:
        session_id = str(job.session_id)
        if session_id not in folder_names:
            folder_names[session_id] = session_folder_name(job.session_id)
        folder_name = folder_names[session_id]
        session = sessions.setdefault(session_id, {
            "sessionId": session_id,
            "sessionFolder": folder_name,
            "startedAt": job.created_at.isoformat(),
            "updatedAt": job.updated_at.isoformat(),
            "jobs": [],
        })
        session["startedAt"] = min(session["startedAt"], job.created_at.isoformat())
        session["updatedAt"] = max(session["updatedAt"], job.updated_at.isoformat())

        artifact_path: Path | None = None
        file_name: str | None = None
        file_type: str | None = None
        download_url: str | None = None
        if job.status == JobStatus.COMPLETED and job.excel_file_name:
            artifact_path = stored_excel_path(job.excel_file_name, job.session_id)
            if artifact_path:
                file_name = job.excel_file_name
                file_type = "excel"
                download_url = f"/api/jobs/{job.id}/excel"
        elif job.status == JobStatus.NO_DATA and job.no_data_file_name:
            artifact_path = stored_no_data_path(job)
            if artifact_path:
                file_name = job.no_data_file_name
                file_type = "text"
                download_url = f"/api/jobs/{job.id}/no-data"

        file_size = 0
        relative_file_path: str | None = None
        if artifact_path:
            try:
                file_size = artifact_path.stat().st_size
                relative_file_path = artifact_path.relative_to(_report_dir).as_posix()
            except (OSError, ValueError):
                artifact_path = None
                file_name = None
                file_type = None
                download_url = None
                file_size = 0

        filters = job.filters.model_dump(by_alias=True, exclude_none=True)
        session["jobs"].append({
            "jobId": str(job.id),
            "scenarioName": job.scenario_name or file_name or "VAHAN report",
            "state": job.filters.states[0] if job.filters.states else "",
            "rto": job.filters.rtos[0] if job.filters.rtos else "",
            "source": job.source.value,
            "status": job.status.value,
            "error": job.error,
            "filters": filters,
            "fileName": file_name,
            "fileType": file_type,
            "fileSize": file_size,
            "filePath": relative_file_path,
            "createdAt": job.created_at.isoformat(),
            "updatedAt": job.updated_at.isoformat(),
            "downloadUrl": download_url,
        })

    result = []
    for session in sessions.values():
        session_jobs = session["jobs"]
        session["jobs"].sort(key=lambda item: (item["createdAt"], item["state"], item["rto"]))
        status_counts = {status.value: 0 for status in JobStatus}
        for item in session_jobs:
            status_counts[item["status"]] += 1
        session.update({
            "jobCount": len(session_jobs),
            "completedCount": status_counts[JobStatus.COMPLETED.value],
            "noDataCount": status_counts[JobStatus.NO_DATA.value],
            "failedCount": status_counts[JobStatus.FAILED.value],
            "cancelledCount": status_counts[JobStatus.CANCELLED.value],
            "activeCount": sum(count for name, count in status_counts.items()
                                if JobStatus(name) not in terminal_statuses),
            "fileCount": sum(1 for item in session_jobs if item["downloadUrl"]),
            "totalFileSize": sum(item["fileSize"] for item in session_jobs),
            "sources": sorted({item["source"] for item in session_jobs}),
        })
        result.append(session)

    result.sort(key=lambda item: item["startedAt"], reverse=True)
    return result


@router.post("/reports/verify")
async def verify_exported_reports(request: VerifyReportsRequest) -> dict:
    return {"files": {
        name: (path.stat().st_size if (path := stored_excel_path(name, request.session_ids.get(name))) else 0)
        for name in request.file_names
    }}


@router.get("/reports/file/{file_name}")
async def download_stored_report(file_name: str) -> FileResponse:
    path = stored_excel_path(file_name)
    if not path:
        raise HTTPException(status_code=404, detail="Excel file not found.")
    return FileResponse(
        path=path,
        filename=file_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.post(
    "/{job_id}/upload-excel",
    status_code=status.HTTP_200_OK,
)
async def upload_excel(
    job_id: UUID,
    file: UploadFile,
    runner_id: str | None = Header(default=None, alias="X-VAHAN-RUNNER-ID"),
) -> dict:
    # A lost HTTP response can make the runner upload the same captured bytes
    # again. Serialize per job and return its first saved report on retries.
    lock = _upload_locks.setdefault(job_id, asyncio.Lock())
    async with lock:
        try:
            return await _save_excel(job_id, file, runner_id)
        except OSError as exc:
            raise HTTPException(status_code=500, detail="Could not save the Excel report to disk. Check storage and permissions.") from exc


async def _save_excel(job_id: UUID, file: UploadFile, runner_id: str | None) -> dict:
    job = await services.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.source != ReportSource.NEW:
        raise HTTPException(status_code=410, detail="The legacy VAHAN report source is no longer supported.")
    if not runner_id or runner_id != job.runner_id:
        raise HTTPException(status_code=403, detail="This runner is not assigned to the job.")
    if job.status in {JobStatus.WAITING_RESULT, JobStatus.COMPLETED} and job.excel_file_name:
        saved_path = stored_excel_path(job.excel_file_name, job.session_id)
        if saved_path:
            return {"ok": True, "fileName": job.excel_file_name, "sizeBytes": saved_path.stat().st_size}
    if job.status != JobStatus.WAITING_RESULT:
        raise HTTPException(status_code=409, detail="Job is not waiting for an Excel report.")

    if file.content_type and file.content_type not in {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    }:
        raise HTTPException(status_code=400, detail="Only .xlsx files are accepted.")

    session_dir = report_session_dir(job.session_id, create=True)
    if session_dir is None:
        raise HTTPException(status_code=500, detail="Could not create a folder for this run's Excel reports.")
    is_matrix_report = bool(job.scenario_name and job.scenario_name.startswith("Maker Month Wise Data  of "))
    state = job.filters.states[0] if is_matrix_report and job.filters.states and job.filters.rtos else None
    state_folder = _sanitize_filename(state).strip(". ") if state else ""
    destination_dir = session_dir / (state_folder or "Unknown State") if state else session_dir
    destination_dir.mkdir(parents=True, exist_ok=True)
    file_name = _generate_excel_filename(job, file.filename)
    dest = destination_dir / file_name
    if dest.exists():
        stem = Path(file_name).stem
        suffix = 2
        while dest.exists():
            file_name = f"{stem} ({suffix}).xlsx"
            dest = destination_dir / file_name
            suffix += 1
    temporary = destination_dir / f".{job.id}.{uuid4().hex}.tmp"

    size = 0
    try:
        async with aiofiles.open(temporary, "wb") as out:
            while chunk := await file.read(256 * 1024):
                size += len(chunk)
                if size > settings.max_excel_upload_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds {settings.max_excel_upload_bytes // (1024 * 1024)} MB limit.",
                    )
                await out.write(chunk)
        if not size:
            raise HTTPException(status_code=400, detail="Excel file is empty.")
        await asyncio.to_thread(_validate_workbook, temporary)
        latest = await services.jobs.get(job_id)
        if not latest or latest.status != JobStatus.WAITING_RESULT:
            raise HTTPException(status_code=409, detail="Job was stopped before the Excel report was saved.")
        temporary.replace(dest)
        latest = await services.jobs.get(job_id)
        if not latest or latest.status != JobStatus.WAITING_RESULT:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=409, detail="Job was stopped before the Excel report was saved.")
    finally:
        temporary.unlink(missing_ok=True)
    saved = await services.jobs.set_excel_file(job_id, file_name=file_name, file_size=size)
    if saved is None:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="Job was stopped before the Excel report was saved.")

    return {"ok": True, "fileName": file_name, "sizeBytes": size}


@router.get("/{job_id}/excel")
async def download_excel(job_id: UUID) -> FileResponse:
    job = await services.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    path = _excel_path(job)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Excel file not found for this job.")

    return FileResponse(
        path=path,
        filename=job.excel_file_name or f"{job_id}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/{job_id}/no-data")
async def download_no_data_file(job_id: UUID) -> FileResponse:
    job = await services.jobs.get(job_id)
    if not job or job.status != JobStatus.NO_DATA:
        raise HTTPException(status_code=404, detail="No-data report not found.")
    path = stored_no_data_path(job)
    if path is None:
        raise HTTPException(status_code=404, detail="No-data text file not found.")
    return FileResponse(path=path, filename=job.no_data_file_name, media_type="text/plain; charset=utf-8")
