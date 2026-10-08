import json
from uuid import UUID
from fastapi import APIRouter, Request, HTTPException, UploadFile, Query, Header
from pydantic import BaseModel, Field
from sqlalchemy import select, update, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from cryptography.fernet import Fernet
from app.access import owner_filter, require_owner, require_admin
from app.config import settings
from app.db import engine
from app.db import schema as db
from app.repositories.postgres import now, audit
from app.services import services
from app.api.excel import attachment, read_upload

router = APIRouter(tags=['persistent-data'])

class StateValue(BaseModel):
    value: object

class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=128, pattern=r'^[a-zA-Z0-9_.@-]+$')
    password: str = Field(min_length=12, max_length=1024)
    role: str = Field(default='user', pattern=r'^(admin|user)$')
    profile: dict = Field(default_factory=dict)

class UserUpdate(BaseModel):
    active: bool | None = None
    profile: dict | None = None

class RunnerLog(BaseModel):
    level: str = Field(default='error', pattern=r'^(info|warning|error)$')
    message: str = Field(min_length=1, max_length=8000)
    job_id: UUID | None = Field(default=None, alias='jobId')

@router.post('/runner-logs', status_code=201)
async def runner_log(command: RunnerLog, request: Request,
                     identity: str | None = Header(None, alias='X-VAHAN-RUNNER-ID')):
    if not getattr(request.state, 'authenticated_runner', False) or not identity or not await services.runners.get(identity):
        raise HTTPException(403, 'Runner is not connected.')
    await audit(identity, 'runner.log', command.model_dump(mode='json', by_alias=True))
    return {'ok': True}

@router.get('/audit')
async def audit_history(request: Request, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    require_admin(request)
    async with engine.connect() as connection:
        return [dict(row) for row in (await connection.execute(select(db.audit_events)
            .order_by(db.audit_events.c.created_at.desc()).offset(offset).limit(limit))).mappings()]

@router.get('/users')
async def users(request: Request):
    require_admin(request)
    return await services.users.list()

@router.post('/users', status_code=201)
async def create_user(command: UserCreate, request: Request):
    require_admin(request)
    try:
        await services.users.create(command.username, command.password, command.role, command.profile)
    except IntegrityError as error:
        raise HTTPException(409, 'Username already exists.') from error
    return {'username': command.username, 'role': command.role, 'profile': command.profile}

class ResetPasswordRequest(BaseModel):
    password: str = Field(min_length=12, max_length=1024)


@router.post('/users/{username}/password')
async def reset_password(username: str, command: ResetPasswordRequest, request: Request):
    require_admin(request)
    if username == request.state.authenticated_user:
        raise HTTPException(409, 'Use Change password for your own account.')
    try:
        await services.users.change_password(username, command.password)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    from app.realtime.ui_events import invalidate_user
    await invalidate_user(username)
    await audit(request.state.authenticated_user, 'user.password_reset', {'username': username})
    return {'ok': True}


@router.patch('/users/{username}')
async def update_user(username: str, command: UserUpdate, request: Request):
    require_admin(request)
    async with engine.begin() as connection:
        # Serialize admin deactivation and preserve at least one active admin.
        rows = (await connection.execute(select(db.users).with_for_update())).mappings().all()
        user = next((r for r in rows if r['username'] == username), None)
        if not user:
            raise HTTPException(404, 'User not found.')
        if command.active is False and user['role'] == 'admin' and user['active']:
            if sum(r['active'] and r['role'] == 'admin' for r in rows) <= 1:
                raise HTTPException(409, 'At least one active administrator is required.')
        await connection.execute(update(db.users).where(db.users.c.username == username).values(**command.model_dump(exclude_none=True)))
        if command.active is False:
            await connection.execute(update(db.auth_sessions).where(db.auth_sessions.c.username == username).values(revoked=True))
    if command.active is False:
        from app.realtime.ui_events import invalidate_user
        await invalidate_user(username)
    return {'ok': True}

@router.get('/user-state')
async def state(request: Request):
    return await services.users.state(request.state.authenticated_user)

@router.put('/user-state/{key}')
async def put_state(key: str, command: StateValue, request: Request):
    if len(key) > 128 or 'token' in key.lower() or 'password' in key.lower():
        raise HTTPException(400, 'Invalid state key.')
    if len(json.dumps(command.value).encode()) > 5 * 1024 * 1024:
        raise HTTPException(413, 'State value exceeds 5 MB.')
    await services.users.put_state(request.state.authenticated_user, key, command.value)
    return {'ok': True}

@router.get('/files')
async def files(request: Request):
    return await services.files.list(owner_filter(request))

@router.post('/files', status_code=201)
async def upload(file: UploadFile, request: Request):
    name = (file.filename or 'upload').replace('\\', '/').split('/')[-1]
    try:
        return await services.files.put(name=name, content=await read_upload(file), kind='upload',
            mime_type=file.content_type or 'application/octet-stream', owner=request.state.authenticated_user, extract=True)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error

@router.post('/jobs/{job_id}/artifacts', status_code=201)
async def runner_artifact(job_id: UUID, file: UploadFile, request: Request,
    identity: str | None = Header(None, alias='X-VAHAN-RUNNER-ID')):
    job = await services.jobs.get(job_id)
    if not job or identity != job.runner_id or not getattr(request.state, 'authenticated_runner', False):
        raise HTTPException(403, 'Artifact runner does not match the job.')
    name = (file.filename or 'artifact').replace('\\', '/').split('/')[-1]
    return await services.files.put(name=name, content=await read_upload(file), kind='screenshot',
        mime_type=file.content_type or 'application/octet-stream', job=job)

async def accessible_file(file_id, request, include_content=False):
    file = await services.files.get(file_id, include_content=include_content)
    if not file:
        raise HTTPException(404, 'File not found.')
    require_owner(request, file['owner_username'])
    return file

@router.get('/files/{file_id}/download')
async def download(file_id: UUID, request: Request):
    return attachment(await accessible_file(file_id, request, True))

@router.get('/files/{file_id}/rows')
async def rows(file_id: UUID, request: Request, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    await accessible_file(file_id, request)
    raise HTTPException(410, 'File row copies have been retired. Use the main report table.')

async def runner_state_access(runner_id, header, request):
    if not getattr(request.state, 'authenticated_runner', False) or header != runner_id or not await services.runners.get(runner_id):
        raise HTTPException(403, 'Runner is not connected.')
    if not settings.browser_state_key:
        raise HTTPException(503, 'Browser state encryption is not configured.')
    return Fernet(settings.browser_state_key.encode())

@router.get('/runner-state/{runner_id}')
async def get_browser_state(runner_id: str, request: Request, identity: str | None = Header(None, alias='X-VAHAN-RUNNER-ID')):
    cipher = await runner_state_access(runner_id, identity, request)
    async with engine.connect() as connection:
        value = await connection.scalar(select(db.browser_states.c.encrypted_state).where(db.browser_states.c.runner_id == runner_id))
    return {'state': json.loads(cipher.decrypt(value)) if value else None}

@router.put('/runner-state/{runner_id}')
async def put_browser_state(runner_id: str, command: StateValue, request: Request, identity: str | None = Header(None, alias='X-VAHAN-RUNNER-ID')):
    cipher = await runner_state_access(runner_id, identity, request)
    value = json.dumps(command.value).encode()
    if len(value) > 5 * 1024 * 1024:
        raise HTTPException(413, 'Browser state exceeds 5 MB.')
    async with engine.begin() as connection:
        await connection.execute(pg_insert(db.browser_states).values(runner_id=runner_id, encrypted_state=cipher.encrypt(value), updated_at=now())
            .on_conflict_do_update(index_elements=[db.browser_states.c.runner_id], set_={'encrypted_state': cipher.encrypt(value), 'updated_at': now()}))
    return {'ok': True}
