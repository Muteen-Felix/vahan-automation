from uuid import UUID
from pathlib import Path
import json
import re
from fastapi import APIRouter, HTTPException, UploadFile, Header, Request, Form, Query
from typing import Annotated
from fastapi.responses import Response
from pydantic import BaseModel, Field, AwareDatetime
from sqlalchemy import select, update
from app.db import engine, schema as db
from app.repositories.postgres import now, TERMINAL
from app.access import owner_filter, require_owner
from app.config import settings
from app.models.job import JobStatus
from app.services import services

router = APIRouter(prefix='/jobs', tags=['reports'])

def attachment(file):
    from urllib.parse import quote
    return Response(file['content'], media_type=file['mime_type'], headers={
        'Content-Disposition': f"attachment; filename*=UTF-8''{quote(file['name'])}",
        'X-Content-SHA256': file['sha256'], 'Cache-Control': 'private, no-store'})

async def read_upload(file):
    content = bytearray()
    while chunk := await file.read(256 * 1024):
        content.extend(chunk)
        if len(content) > settings.max_excel_upload_bytes:
            raise HTTPException(413, 'File exceeds the 50 MB upload limit.')
    if not content:
        raise HTTPException(400, 'File is empty.')
    return bytes(content)

def _sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|\r\n\t]', '_', name).strip() or 'report'

def _generate_excel_filename(job, uploaded_filename=None):
    if job.scenario_name and job.scenario_name.startswith('Maker Month Wise Data  of '):
        return f'{_sanitize_filename(job.scenario_name)}.xlsx'
    stem = job.scenario_name or Path(uploaded_filename or 'report.xlsx').stem
    return f'{_sanitize_filename(stem)}_{str(job.id)[:8]}.xlsx'

class VerifyReportsRequest(BaseModel):
    file_names: list[str] = Field(alias='fileNames', max_length=500)
    session_ids: dict[str, UUID] = Field(default_factory=dict, alias='sessionIds')

@router.get('/reports')
async def list_exported_reports(request: Request):
    files = await services.files.list(owner_filter(request), kind='excel')
    jobs = {str(j.id): j for j in await services.jobs.list_all(owner_filter(request), job_ids=[f['job_id'] for f in files])} if files else {}
    reports = []
    for file in files:
        job = jobs.get(file['job_id'])
        if not job or job.status != JobStatus.COMPLETED:
            continue
        reports.append(dict(jobId=str(job.id), scenarioName=job.scenario_name or file['name'],
            fileName=file['name'], fileSize=file['size'], createdAt=job.created_at.isoformat(),
            sessionFolder=str(job.session_id), downloadUrl=f'/api/jobs/{job.id}/excel', source=job.source.value))
    return reports

@router.get('/reports/sessions')
async def list_exported_report_sessions(request: Request, deleted: bool = False,
    offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=200)] = 100):
    from app.repositories.report_sessions import read_sessions
    return await read_sessions(owner_filter(request), deleted=deleted, offset=offset, limit=limit)


@router.get('/reports/sessions/{session_id}')
async def read_exported_report_session(session_id: UUID, request: Request,
    offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=500)] = 100):
    from app.repositories.report_sessions import read_sessions
    records = await read_sessions(owner_filter(request), session_id=session_id,
                                  job_offset=offset, job_limit=limit)
    if not records:
        raise HTTPException(404, 'Report session not found.')
    return records[0]


@router.delete('/reports/sessions/{session_id}')
async def delete_report_session(session_id: UUID, request: Request):
    async with engine.begin() as connection:
        session = (await connection.execute(select(db.report_sessions).where(
            db.report_sessions.c.id == str(session_id)).with_for_update())).mappings().first()
        if not session:
            raise HTTPException(404, 'Report session not found.')
        require_owner(request, session['owner_username'])
        if session['deleted_at'] is not None:
            return {'ok': True, 'sessionId': str(session_id)}
        active_job = await connection.scalar(select(db.jobs.c.id).where(
            db.jobs.c.session_id == str(session_id), db.jobs.c.status.not_in([status.value for status in TERMINAL])).limit(1))
        active_batch = await connection.scalar(select(db.user_state.c.username).where(
            db.user_state.c.username == session['owner_username'],
            db.user_state.c.key == 'vahanStateRtoBatchRecoveryV1',
            db.user_state.c.value['sessionId'].as_string() == str(session_id),
            db.user_state.c.value['status'].as_string() == 'running').limit(1))
        if active_job or active_batch:
            raise HTTPException(409, 'Stop this session before deleting it.')
        await connection.execute(update(db.report_sessions).where(db.report_sessions.c.id == str(session_id)).values(deleted_at=now()))
    from app.db.read_cache import invalidate_report_sessions
    invalidate_report_sessions()
    return {'ok': True, 'sessionId': str(session_id)}



@router.post('/reports/sessions/{session_id}/restore')
async def restore_report_session(session_id: UUID, request: Request):
    async with engine.begin() as connection:
        session = (await connection.execute(select(db.report_sessions).where(
            db.report_sessions.c.id == str(session_id)).with_for_update())).mappings().first()
        if not session:
            raise HTTPException(404, 'Report session not found.')
        require_owner(request, session['owner_username'])
        await connection.execute(update(db.report_sessions).where(db.report_sessions.c.id == str(session_id)).values(deleted_at=None))
    from app.db.read_cache import invalidate_report_sessions
    invalidate_report_sessions()
    return {'ok': True, 'sessionId': str(session_id)}


@router.post('/reports/verify')
async def verify_exported_reports(command: VerifyReportsRequest, request: Request):
    files = await services.files.list(owner_filter(request), 'excel')
    jobs = {str(j.id): j for j in await services.jobs.list_all(owner_filter(request), job_ids=[f['job_id'] for f in files])} if files else {}
    result = {}
    for name in command.file_names:
        matches = [f for f in files if f['name'] == name and f['job_id'] in jobs
            and (name not in command.session_ids or jobs[f['job_id']].session_id == command.session_ids[name])]
        result[name] = max((f['size'] for f in matches), default=0)
    return {'files': result}

@router.get('/reports/file/{file_name}')
async def download_stored_report(file_name: str, request: Request):
    matches = [f for f in await services.files.list(owner_filter(request), 'excel') if f['name'] == file_name]
    if not matches:
        raise HTTPException(404, 'Report not found.')
    if len(matches) > 1:
        raise HTTPException(409, 'Multiple reports share this name. Download using the job or file ID.')
    return attachment(await services.files.get(matches[0]['id']))

@router.post('/{job_id}/upload-excel', deprecated=True)
@router.post('/{job_id}/main-report')
async def upload_excel(job_id: UUID, file: UploadFile, request: Request,
    runner_id: str | None = Header(default=None, alias='X-VAHAN-RUNNER-ID'),
    observed_at: AwareDatetime | None = Form(None, alias='observedAt'),
    page_url: str = Form('', alias='pageUrl')):
    job = await services.jobs.get(job_id)
    if not job:
        raise HTTPException(404, 'Job not found.')
    if not runner_id or runner_id != job.runner_id:
        raise HTTPException(403, 'This runner is not assigned to the job.')
    if not getattr(request.state, 'authenticated_runner', False):
        require_owner(request, job.owner_username)
    content = await read_upload(file)
    try:
        saved = await services.files.commit_excel(job_id, _generate_excel_filename(job, file.filename), content,
            observed_at=observed_at, page_url=page_url, runner_id=runner_id)
        from app.realtime.report_notifications import notify_report_saved
        job = await services.jobs.get(job_id)
        await notify_report_saved(job)
        return saved
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error
    except ValueError as error:
        raise HTTPException(409 if 'Job' in str(error) or 'already' in str(error) else 400, str(error)) from error
    except Exception as error:
        from zipfile import BadZipFile
        if isinstance(error, (BadZipFile, KeyError)):
            raise HTTPException(400, 'Invalid Excel workbook.') from error
        raise

@router.get('/{job_id}/excel')
async def download_excel(job_id: UUID, request: Request):
    return await download_job_file(job_id, 'excel', request)

@router.get('/{job_id}/no-data')
async def download_no_data_file(job_id: UUID, request: Request):
    return await download_job_file(job_id, 'no-data', request)

async def download_job_file(job_id, kind, request):
    job = await services.jobs.get(job_id)
    if not job:
        raise HTTPException(404, 'Job not found.')
    require_owner(request, job.owner_username)
    file = await services.files.for_job(job_id, kind)
    if not file:
        raise HTTPException(404, 'Report file not found.')
    return attachment(file)
