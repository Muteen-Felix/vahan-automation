from uuid import UUID
from pathlib import Path
import json
import re
from fastapi import APIRouter, HTTPException, UploadFile, Header, Request, Form
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
    jobs = {str(j.id): j for j in await services.jobs.list_all(owner_filter(request))}
    reports = []
    for file in await services.files.list(owner_filter(request), kind='excel'):
        job = jobs.get(file['job_id'])
        if not job or job.status != JobStatus.COMPLETED:
            continue
        reports.append(dict(jobId=str(job.id), scenarioName=job.scenario_name or file['name'],
            fileName=file['name'], fileSize=file['size'], createdAt=job.created_at.isoformat(),
            sessionFolder=str(job.session_id), downloadUrl=f'/api/jobs/{job.id}/excel', source=job.source.value))
    return reports

@router.get('/reports/sessions')
async def list_exported_report_sessions(request: Request, deleted: bool = False):
    query = select(db.report_sessions).where(
        db.report_sessions.c.deleted_at.is_not(None) if deleted else db.report_sessions.c.deleted_at.is_(None))
    owner = owner_filter(request)
    if owner is not None:
        query = query.where(db.report_sessions.c.owner_username == owner)
    async with engine.connect() as connection:
        session_records = {row['id']: row for row in (await connection.execute(query)).mappings()}
    files = {(f['job_id'], f['kind']): f for f in await services.files.list(owner_filter(request))}
    sessions = {}
    attempts = sorted((job for job in await services.jobs.list_all(owner_filter(request))
        if str(job.session_id) in session_records), key=lambda j: (j.created_at, str(j.id)))
    attempts_by_id = {job.id: job for job in attempts}
    legacy_roots = {}
    legacy_case_ids = {}
    for job in attempts:
        if job.case_id is None and job.retry_of_job_id is None:
            # Older matrix runs did not save retry links. Each office/filter set
            # occurs once per session; repeated identical attempts are retries.
            key = (job.session_id, job.source, job.scenario_name,
                json.dumps(job.filters.model_dump(mode='json'), sort_keys=True))
            legacy_case_ids[job.id] = legacy_roots.setdefault(key, job.id)
    latest_cases = {}
    for job in attempts:
        session_id = str(job.session_id)
        session = sessions.setdefault(session_id, dict(sessionId=session_id, sessionFolder=session_id,
            startedAt=job.created_at.isoformat(), updatedAt=job.updated_at.isoformat(),
            deletedAt=session_records[session_id]['deleted_at'].isoformat() if deleted else None, jobs=[]))
        session['startedAt'] = min(session['startedAt'], job.created_at.isoformat())
        session['updatedAt'] = max(session['updatedAt'], job.updated_at.isoformat())
        # Keep all attempts in storage, but count each logical case only once.
        case_id = job.case_id or job.id
        case_id = legacy_case_ids.get(case_id, case_id)
        latest_cases[(session_id, case_id)] = job
    for (session_id, case_id), job in latest_cases.items():
        session = sessions[session_id]
        original = attempts_by_id.get(case_id, job)
        kind = 'excel' if job.status == JobStatus.COMPLETED else 'no-data' if job.status == JobStatus.NO_DATA else None
        file = files.get((str(job.id), kind))
        session['jobs'].append(dict(jobId=str(job.id), scenarioName=job.scenario_name or 'VAHAN report',
            state=job.filters.states[0] if job.filters.states else '', rto=job.filters.rtos[0] if job.filters.rtos else '',
            source=job.source.value, status=job.status.value, error=job.error,
            filters=job.filters.model_dump(mode='json', by_alias=True), fileName=file['name'] if file else None,
            fileType=('excel' if kind == 'excel' else 'text') if file else None,
            fileSize=file['size'] if file else 0, filePath=f"postgresql:{file['id']}" if file else None,
            createdAt=original.created_at.isoformat(), updatedAt=job.updated_at.isoformat(),
            downloadUrl=f'/api/jobs/{job.id}/{kind}' if file else None))
    for session in sessions.values():
        jobs = session['jobs']
        session.update(jobCount=len(jobs), completedCount=sum(j['status'] == 'COMPLETED' for j in jobs),
            noDataCount=sum(j['status'] == 'NO_DATA' for j in jobs), failedCount=sum(j['status'] == 'FAILED' for j in jobs),
            cancelledCount=sum(j['status'] == 'CANCELLED' for j in jobs),
            activeCount=sum(j['status'] not in {'COMPLETED', 'NO_DATA', 'FAILED', 'CANCELLED'} for j in jobs),
            fileCount=sum(bool(j['downloadUrl']) for j in jobs), totalFileSize=sum(j['fileSize'] for j in jobs),
            sources=sorted({j['source'] for j in jobs}))
        jobs.sort(key=lambda j: j['createdAt'])
    return sorted(sessions.values(), key=lambda s: s['startedAt'], reverse=True)


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
    return {'ok': True, 'sessionId': str(session_id)}

@router.post('/reports/verify')
async def verify_exported_reports(command: VerifyReportsRequest, request: Request):
    jobs = {str(j.id): j for j in await services.jobs.list_all(owner_filter(request))}
    files = await services.files.list(owner_filter(request), 'excel')
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
