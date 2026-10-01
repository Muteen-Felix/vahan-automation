from contextlib import asynccontextmanager

import socketio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.config import settings
from app.realtime.server import sio
from app.security import runner_token_matches, verify_access_token


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


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
)


def _runner_auth_is_allowed(request: Request) -> bool:
    path = request.url.path
    method = request.method.upper()
    allowed_path = (
        (method == "GET" and path == "/api/ui-health/schedule")
        or (method == "POST" and path == "/api/ui-health/logs")
        or (method == "POST" and path.startswith("/api/jobs/") and path.endswith("/upload-excel"))
    )
    return allowed_path and runner_token_matches(request.headers.get("x-vahan-runner-token"))


@fastapi_app.middleware("http")
async def require_ui_authentication(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api/"):
        return await call_next(request)
    if path in {"/api/health", "/api/auth/status", "/api/auth/login"}:
        return await call_next(request)
    if _runner_auth_is_allowed(request):
        request.state.authenticated_runner = True
        return await call_next(request)

    authorization = request.headers.get("authorization", "")
    scheme, _, credential = authorization.partition(" ")
    username = verify_access_token(credential.strip()) if scheme.lower() == "bearer" else None
    if username:
        request.state.authenticated_user = username
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


fastapi_app.include_router(api_router)

application = socketio.ASGIApp(
    socketio_server=sio,
    other_asgi_app=fastapi_app,
)
