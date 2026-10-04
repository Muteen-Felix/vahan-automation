from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.config import settings
from app.security import issue_access_token
from app.services import services


router = APIRouter(prefix="/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


@router.get("/status")
async def auth_status() -> dict[str, bool | int | None]:
    return {
        "configured": settings.ui_auth_configured and bool(await services.users.list()),
        "tokenTtlSeconds": None,
    }


@router.post("/login")
async def login(command: LoginRequest, response: Response) -> dict[str, str | int | None]:
    if not settings.ui_auth_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured on the API server.",
        )
    if not await services.users.authenticate(command.username, command.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The username or password is incorrect.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return {
        "accessToken": issue_access_token(command.username, await services.users.create_session(command.username)),
        "tokenType": "Bearer",
        "expiresIn": None,
        "username": command.username,
    }


@router.post("/renew")
async def renew_session(request: Request, response: Response) -> dict[str, str | int | None]:
    """Replace a still-valid legacy expiring token with a non-expiring token."""
    username = getattr(request.state, "authenticated_user", None)
    if not isinstance(username, str) or not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return {
        "accessToken": issue_access_token(username, request.state.token_session),
        "tokenType": "Bearer",
        "expiresIn": None,
        "username": username,
    }


@router.get("/me")
async def current_user(request: Request) -> dict[str, str]:
    username = getattr(request.state, "authenticated_user", None)
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    return {"username": username, "role": request.state.authenticated_role}


@router.post("/logout")
async def logout(request: Request):
    from app.realtime.ui_events import invalidate_session
    await services.users.revoke(request.state.token_session)
    await invalidate_session(request.state.token_session)
    return {"ok": True}
