from contextlib import asynccontextmanager

import socketio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.config import settings
from app.realtime.server import sio
from app.security import runner_token_matches, authenticate_access_token
from app.services import services
from app.db import engine
from app.repositories.postgres import recover_after_restart
from sqlalchemy import text
import asyncio, logging, time
from app.repositories.postgres import audit


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.validate_startup()
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1 FROM users LIMIT 1"))
        if settings.environment == 'production':
            elevated = await connection.scalar(text('SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls FROM pg_roles WHERE rolname=current_user'))
            can_create = await connection.scalar(text("SELECT has_schema_privilege(current_user,'public','CREATE')"))
            owns_objects = await connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user))"))
            if elevated or can_create or owns_objects:
                raise RuntimeError('Production API must use the restricted runtime database role, separate from migrations.')
    await services.users.bootstrap(settings.ui_auth_username, settings.ui_auth_password)
    await recover_after_restart()
    from app.worker_pool import initialize_pool
    await initialize_pool(reset_phase=True)
    from app.run_scheduler import run_scheduler
    scheduler_task = asyncio.create_task(run_scheduler())
    from app.network_guard import monitor
    network_task = asyncio.create_task(monitor())
    try:
        yield
    finally:
        network_task.cancel()
        scheduler_task.cancel()
        await asyncio.gather(scheduler_task, network_task, return_exceptions=True)
        await engine.dispose()


fastapi_app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
    docs_url=None if settings.environment == 'production' else '/docs',
    redoc_url=None if settings.environment == 'production' else '/redoc',
    openapi_url=None if settings.environment == 'production' else '/openapi.json',
)
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Report-Row-Count"],
)


def _runner_auth_is_allowed(request: Request) -> bool:
    path = request.url.path
    method = request.method.upper()
    allowed_path = (
        (method == "GET" and path == "/api/ui-health/contract")
        or (method == "POST" and path == "/api/ui-health/logs")
        or (method == "POST" and path.startswith("/api/jobs/") and path.endswith("/main-report"))
        or (method == "POST" and path.startswith("/api/jobs/") and path.endswith("/report-result"))
        or (method == "POST" and path.startswith("/api/jobs/") and path.endswith("/artifacts"))
        or (method in {"GET", "PUT"} and path.startswith("/api/runner-state/"))
        or (method == 'POST' and path == '/api/runner-logs')
        or (method == 'POST' and path == '/api/runner/queue/claim')
        or (method == 'POST' and path == '/api/runner/ocr/start')
    )
    return allowed_path and runner_token_matches(request.headers.get("x-vahan-runner-token"))


@fastapi_app.middleware("http")
async def require_ui_authentication(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api/"):
        return await call_next(request)
    if path in {"/api/health", "/api/ready", "/api/auth/status", "/api/auth/login"}:
        return await call_next(request)
    # Retired endpoints are absent for every caller, including old clients
    # that no longer have a valid dashboard session.
    if path.rstrip('/') in {'/api/ui-health/schedule', '/api/ui-health/run-now'} or (
            path.rstrip('/') == '/api/maker-updates' or path.startswith('/api/maker-updates/')):
        return JSONResponse(status_code=404, content={'detail': 'Not Found'})
    if _runner_auth_is_allowed(request):
        request.state.authenticated_runner = True
        return await call_next(request)

    authorization = request.headers.get("authorization", "")
    scheme, _, credential = authorization.partition(" ")
    # UI activity is recorded explicitly; even background POSTs must not keep
    # an unattended dashboard session alive.
    user = await authenticate_access_token(credential.strip()) if scheme.lower() == "bearer" else None
    if user:
        request.state.authenticated_user = user["username"]
        request.state.authenticated_role = user["role"]
        request.state.token_session = user["session_id"]
        from app.access import member_api_allowed
        if user['role'] != 'admin' and not member_api_allowed(request.method, path):
            return JSONResponse(status_code=403, content={'detail': 'Bạn không có quyền truy cập chức năng này.'})
        return await call_next(request)

    if not settings.ui_auth_configured:
        return JSONResponse(
            status_code=503,
            content={"detail": "Authentication is not configured on the API server."},
        )
    return JSONResponse(
        status_code=401,
        content={"detail": "Authentication required or access token is invalid."},
        headers={"WWW-Authenticate": "Bearer"},
    )


@fastapi_app.get("/", tags=["health"])
async def root() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@fastapi_app.middleware('http')
async def audit_mutations(request: Request, call_next):
    started = time.monotonic()
    response = await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers.setdefault('Cache-Control', 'no-store')
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    if request.url.path.startswith('/api/') and request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        if request.url.path not in {'/api/runner-logs'} and not request.url.path.startswith('/api/runner-state/'):
            try:
                actor = getattr(request.state, 'authenticated_user', None)
                if getattr(request.state, 'authenticated_runner', False):
                    actor = request.headers.get('x-vahan-runner-id')
                await audit(actor, 'http.mutation', {'method': request.method, 'path': request.url.path,
                    'statusCode': response.status_code, 'durationMs': round((time.monotonic() - started) * 1000)})
            except Exception:
                logging.getLogger(__name__).exception('Could not persist the request audit.')
    return response


fastapi_app.include_router(api_router)

application = socketio.ASGIApp(
    socketio_server=sio,
    other_asgi_app=fastapi_app,
)
