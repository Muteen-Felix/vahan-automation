from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.config import settings
from app.security import issue_access_token, ABSOLUTE_TTL_SECONDS, IDLE_TIMEOUT_SECONDS, csrf_token
from app.services import services
from app.repositories.postgres import audit
from app.security_limits import consume, refund
from app import mfa
import asyncio
import secrets

_password_slots = asyncio.Semaphore(4)


router = APIRouter(prefix="/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)
    otp: str = Field(default='', max_length=64)
    browser_session: bool = Field(default=False, alias='browserSession')


@router.get("/status")
async def auth_status() -> dict:
    return {
        "configured": settings.ui_auth_configured and bool(await services.users.list()),
        "tokenTtlSeconds": ABSOLUTE_TTL_SECONDS,
        "idleTimeoutSeconds": IDLE_TIMEOUT_SECONDS,
        'tenantId': settings.tenant_id,
        'adminMfaRequired': settings.require_admin_mfa,
    }


@router.post("/login")
async def login(command: LoginRequest, response: Response, request: Request) -> dict:
    if not settings.ui_auth_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured on the API server.",
        )
    ip = getattr(request.state, 'security_client_ip', request.client.host if request.client else 'unknown')
    await consume('login:global', 120, 60)
    await consume(f'login:ip:{ip}', 20, 60)
    reservation = await consume(f'login:account:{command.username}', 5, 600)
    failed = False
    try:
        async with _password_slots:
            user = await services.users.authenticate(command.username, command.password)
        if not user:
            failed = True
            await audit(command.username, 'auth.login_failed', {'reason': 'credentials'})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="The username or password is incorrect.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        has_mfa = settings.require_admin_mfa and await mfa.enabled(user['username'])
        if user['role'] == 'admin' and settings.require_admin_mfa and not has_mfa:
            await audit(user['username'], 'auth.mfa_enrollment_required', {})
            return {'mfaSetupToken': mfa.setup_challenge(user), 'username': user['username'],
                    'accessToken': None, 'mfaRequired': True}
        if has_mfa and not await mfa.verify(user['username'], command.otp):
            # The password step deliberately omits a code. Only an incorrect
            # code submitted by the user consumes the account failure budget.
            failed = bool(command.otp)
            if failed:
                await audit(user['username'], 'auth.login_failed', {'reason': 'second_factor'})
            raise HTTPException(401, 'The username, password or verification code is incorrect.')
        return await establish_session(user, response, browser=command.browser_session or settings.production)
    finally:
        if not failed:
            await refund(reservation)


async def establish_session(user, response, *, browser=True):
    username = user['username']
    try:
        session = await services.users.create_session(username, expected_password_hash=user['password_hash'], expected_role=user['role'])
    except ValueError as error:
        raise HTTPException(401, 'Credentials changed. Please sign in again.') from error
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    user = await services.users.session_user(username, session)
    deadlines = session_deadlines(user)
    token = issue_access_token(username, session, expires_at=deadlines['expiresAt'])
    response.set_cookie(settings.session_cookie_name, token, httponly=True, secure=settings.cookie_secure,
                        samesite='strict', max_age=ABSOLUTE_TTL_SECONDS, path='/')
    await audit(username, 'auth.login_success', {'role': user['role']})
    return {
        "accessToken": None if browser else token,
        'sessionMarker': secrets.token_hex(16),
        'csrfToken': csrf_token(session),
        "tokenType": "Cookie" if browser else "Bearer",
        "expiresIn": ABSOLUTE_TTL_SECONDS,
        "idleTimeoutSeconds": IDLE_TIMEOUT_SECONDS,
        **deadlines,
        "username": username,
    }


def session_deadlines(user):
    if not user:
        raise HTTPException(401, 'Your session has expired. Please sign in again.')
    expires = int(user['session_expires_at'].timestamp())
    idle = int(user['session_last_activity_at'].timestamp()) + IDLE_TIMEOUT_SECONDS
    return {'expiresAt': expires, 'idleExpiresAt': min(expires, idle)}


@router.get("/me")
async def current_user(request: Request) -> dict[str, str | int]:
    username = getattr(request.state, "authenticated_user", None)
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    user = await services.users.session_user(username, request.state.token_session)
    return {"username": username, "role": request.state.authenticated_role,
            'tenantId': settings.tenant_id, 'csrfToken': csrf_token(request.state.token_session),
            'mfaEnabled': await mfa.enabled(username), **session_deadlines(user)}


@router.post('/activity')
async def session_activity(request: Request, response: Response):
    """Record deliberate UI interaction, never polling or transport heartbeats."""
    user = await services.users.session_user(request.state.authenticated_user, request.state.token_session, touch=True)
    response.headers['Cache-Control'] = 'no-store'
    return session_deadlines(user)


@router.post("/logout")
async def logout(request: Request, response: Response):
    from app.realtime.ui_events import invalidate_session
    await services.users.revoke(request.state.token_session)
    await invalidate_session(request.state.token_session)
    response.delete_cookie(settings.session_cookie_name, path='/', secure=settings.cookie_secure,
                           httponly=True, samesite='strict')
    await audit(request.state.authenticated_user, 'auth.logout', {})
    return {"ok": True}


class MfaEnrollment(BaseModel):
    challenge: str = Field(min_length=1, max_length=4096)
    code: str = Field(default='', max_length=6)


@router.post('/mfa/enroll')
async def mfa_enroll(command: MfaEnrollment):
    user = await mfa.setup_user(command.challenge)
    await consume(f'mfa-enroll:{user["username"]}', 3, 300)
    result = await mfa.enroll(user)
    await audit(user['username'], 'auth.mfa_enrollment_started', {})
    return result


@router.post('/mfa/confirm')
async def mfa_confirm(command: MfaEnrollment, response: Response):
    user = await mfa.setup_user(command.challenge)
    await consume(f'mfa-confirm:{user["username"]}', 5, 300)
    codes = await mfa.confirm(user, command.code)
    await audit(user['username'], 'auth.mfa_enabled', {})
    return {**await establish_session(user, response), 'recoveryCodes': codes}


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(alias='currentPassword', min_length=1, max_length=1024)
    new_password: str = Field(alias='newPassword', min_length=12, max_length=1024)


@router.post('/password')
async def change_password(command: ChangePasswordRequest, request: Request):
    if command.current_password == command.new_password:
        raise HTTPException(409, 'Choose a different new password.')
    try:
        await services.users.change_password(request.state.authenticated_user, command.new_password,
            current_password=command.current_password, keep_session=request.state.token_session)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    from app.realtime.ui_events import invalidate_user
    from app.repositories.postgres import audit
    await invalidate_user(request.state.authenticated_user, except_session=request.state.token_session)
    await audit(request.state.authenticated_user, 'user.password_changed', {'username': request.state.authenticated_user})
    return {'ok': True}
