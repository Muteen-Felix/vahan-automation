from contextlib import asynccontextmanager

import socketio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.config import settings
from app.realtime.server import sio
from app.security import runner_token_matches, authenticate_access_token
from app.security import csrf_token
from app.deployment_security import verify_deployment
from app import soc
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
        await connection.execute(text("SELECT case_id,retry_of_job_id,scenario_name,source FROM jobs LIMIT 0"))
    await verify_deployment()
    await services.users.bootstrap(settings.ui_auth_username, settings.ui_auth_password)
    await recover_after_restart()
    from app.worker_pool import initialize_pool
    await initialize_pool(reset_phase=True)
    from app.run_scheduler import run_scheduler
    scheduler_task = asyncio.create_task(run_scheduler())
    from app.network_guard import monitor
    network_task = asyncio.create_task(monitor())
    soc_task = asyncio.create_task(soc.forward_loop())
    try:
        yield
    finally:
        network_task.cancel()
        scheduler_task.cancel()
        soc_task.cancel()
        await asyncio.gather(scheduler_task, network_task, soc_task, return_exceptions=True)
        await engine.dispose()


fastapi_app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
    docs_url=None if settings.production else '/docs',
    redoc_url=None if settings.production else '/redoc',
    openapi_url=None if settings.production else '/openapi.json',
)
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Report-Row-Count"],
)
from app.request_limits import RequestLimits
fastapi_app.add_middleware(RequestLimits)


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
    return allowed_path and runner_token_matches(request.headers.get("x-vahan-runner-token"),
                                                request.headers.get('x-vahan-runner-id'))


@fastapi_app.middleware("http")
async def require_ui_authentication(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api/"):
        return await call_next(request)
    origin = request.headers.get('origin')
    if origin and origin not in settings.cors_origins:
        return JSONResponse(status_code=403, content={'detail': 'Origin is not permitted.'})
    if path in {"/api/health", "/api/ready", "/api/auth/status", "/api/auth/login",
                '/api/auth/mfa/enroll', '/api/auth/mfa/confirm'}:
        return await call_next(request)
    if _runner_auth_is_allowed(request):
        identity = request.headers.get('x-vahan-runner-id')
        if path.startswith('/api/runner-state/') and path.rsplit('/', 1)[-1] != identity:
            return JSONResponse(status_code=403, content={'detail': 'Worker identity does not match.'})
        if path.startswith('/api/jobs/'):
            from uuid import UUID
            try:
                job = await services.jobs.get(UUID(path.split('/')[3]))
            except ValueError:
                job = None
            if not job or job.runner_id != identity:
                return JSONResponse(status_code=403, content={'detail': 'Job is not assigned to this worker.'})
        request.state.authenticated_runner = True
        request.state.authenticated_runner_id = identity
        return await call_next(request)

    authorization = request.headers.get("authorization", "")
    scheme, _, credential = authorization.partition(" ")
    # UI activity is recorded explicitly; even background POSTs must not keep
    # an unattended dashboard session alive.
    from_cookie = not authorization and bool(request.cookies.get(settings.session_cookie_name))
    token = request.cookies.get(settings.session_cookie_name, '') if from_cookie else credential.strip()
    user = await authenticate_access_token(token) if from_cookie or scheme.lower() == "bearer" else None
    if user:
        request.state.authenticated_user = user["username"]
        request.state.authenticated_role = user["role"]
        request.state.token_session = user["session_id"]
        if from_cookie and request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            import hmac
            if not hmac.compare_digest(request.headers.get('x-csrf-token', ''), csrf_token(user['session_id'])):
                return JSONResponse(status_code=403, content={'detail': 'CSRF verification failed.'})
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
    from uuid import uuid4
    import socket
    ip = request.client.host if request.client else 'unknown'
    if settings.trusted_proxy_host:
        try:
            trusted = {v[4][0] for v in socket.getaddrinfo(settings.trusted_proxy_host, None)}
            if ip in trusted:
                ip = request.headers.get('x-real-ip', ip)[:64]
        except OSError:
            pass
    request.state.security_client_ip = ip
    request_id = str(uuid4())
    context = soc.request_context.set({'requestId': request_id, 'sourceIp': ip,
                                      'method': request.method, 'path': request.url.path[:512]})
    try:
        response = await call_next(request)
    except BaseException:
        soc.request_context.reset(context)
        raise
    response.headers['X-Request-ID'] = request_id
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api/') else 'no-cache'
    if request.url.path.startswith('/api/') and (request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} or
            response.status_code in {401, 403, 429} or '/export' in request.url.path or '/download' in request.url.path):
        if request.url.path not in {'/api/runner-logs'} and not request.url.path.startswith('/api/runner-state/'):
            try:
                actor = getattr(request.state, 'authenticated_user', None)
                if getattr(request.state, 'authenticated_runner', False):
                    actor = request.state.authenticated_runner_id
                name = 'http.denied' if response.status_code in {401, 403, 429} else (
                    'data.export' if request.method == 'GET' else 'http.mutation')
                await audit(actor, name, {'method': request.method, 'path': request.url.path,
                    'statusCode': response.status_code, 'durationMs': round((time.monotonic() - started) * 1000)})
            except Exception:
                soc.logger.error('{"event":"audit.persist_failed"}')
    soc.request_context.reset(context)
    return response


fastapi_app.include_router(api_router)


@fastapi_app.middleware('http')
async def database_backpressure(request: Request, call_next):
    from app.db.pressure import pressure_code
    try:
        return await call_next(request)
    except Exception as error:
        code = pressure_code(error)
        if not code:
            raise
        # Never log SQL parameters or automatically replay a possibly committed write.
        logging.getLogger(__name__).warning('%s on %s %s', code, request.method, request.url.path)
        headers = {'Retry-After': '3'}
        origin = request.headers.get('origin')
        if origin in settings.cors_origins:
            headers.update({'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Credentials': 'true'})
        return JSONResponse(status_code=503, headers=headers, content={
            'code': code,
            'detail': 'Database or report processing is temporarily busy. Please retry shortly.',
        })

application = socketio.ASGIApp(
    socketio_server=sio,
    other_asgi_app=fastapi_app,
)
if settings.production:
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    from urllib.parse import urlsplit
    hosts = {'127.0.0.1', 'localhost', 'api'} | {
        urlsplit(origin).hostname for origin in settings.cors_origins if urlsplit(origin).hostname}
    application = TrustedHostMiddleware(application, allowed_hosts=sorted(hosts))
