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
    if not settings.ui_auth_configured:
        raise RuntimeError("VAHAN_UI_AUTH_TOKEN_SECRET must contain at least 32 characters.")
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1 FROM users LIMIT 1"))
    await services.users.bootstrap(settings.ui_auth_username, settings.ui_auth_password)
    await recover_after_restart()
    from app.worker_pool import initialize_pool, reconcile_pool
    await initialize_pool(reset_phase=True)
    pool_task = asyncio.create_task(reconcile_pool())
    from app.run_scheduler import run_scheduler
    scheduler_task = asyncio.create_task(run_scheduler())
    from app.network_guard import monitor
    network_task = asyncio.create_task(monitor())
    try:
        yield
    finally:
        network_task.cancel()
        scheduler_task.cancel()
        pool_task.cancel()
        await asyncio.gather(scheduler_task, pool_task, network_task, return_exceptions=True)
        await engine.dispose()


fastapi_app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
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
        (method == "GET" and path in {"/api/ui-health/schedule","/api/ui-health/contract"})
        or (method == "POST" and path == "/api/ui-health/logs")
        or (method == "POST" and path.startswith("/api/jobs/") and (path.endswith("/upload-excel") or path.endswith("/main-report")))
        or (method == "POST" and path.startswith("/api/jobs/") and path.endswith("/report-result"))
        or (method == "POST" and path.startswith("/api/jobs/") and path.endswith("/artifacts"))
        or (method in {"GET", "PUT"} and path.startswith("/api/runner-state/"))
        or (method == 'POST' and path == '/api/runner-logs')
    )
    return allowed_path and runner_token_matches(request.headers.get("x-vahan-runner-token"))


@fastapi_app.middleware("http")
async def require_ui_authentication(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api/"):
        return await call_next(request)
    if path in {"/api/health", "/api/ready", "/api/auth/status", "/api/auth/login"}:
        return await call_next(request)
    if _runner_auth_is_allowed(request):
        request.state.authenticated_runner = True
        return await call_next(request)

    authorization = request.headers.get("authorization", "")
    scheme, _, credential = authorization.partition(" ")
    user = await authenticate_access_token(credential.strip()) if scheme.lower() == "bearer" else None
    if user:
        request.state.authenticated_user = user["username"]
        request.state.authenticated_role = user["role"]
        request.state.token_session = user["session_id"]
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
