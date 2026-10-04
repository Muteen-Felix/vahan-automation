from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from app.config import settings


def credentials_match(username: str, password: str) -> bool:
    username_matches = secrets.compare_digest(username.encode(), settings.ui_auth_username.encode())
    password_matches = secrets.compare_digest(password.encode(), settings.ui_auth_password.encode())
    return settings.ui_auth_configured and username_matches and password_matches


def issue_access_token(username: str, session_id: str | None = None) -> str:
    now = int(time.time())
    payload = {
        "sub": username,
        "iat": now,
        "aud": "vahan-rpa-ui",
        "typ": "access",
    }
    if session_id:
        payload["sid"] = session_id
    encoded_payload = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).rstrip(b"=")
    signature = hmac.new(
        settings.ui_auth_token_secret.encode("utf-8"),
        encoded_payload,
        hashlib.sha256,
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=")
    return f"{encoded_payload.decode()}.{encoded_signature.decode()}"


def _verified_payload(token: str) -> dict[str, Any] | None:
    if not settings.ui_auth_configured:
        return None
    try:
        encoded_payload_text, encoded_signature_text = token.split(".", 1)
        encoded_payload = encoded_payload_text.encode("ascii")
        encoded_signature = encoded_signature_text.encode("ascii")
        expected_signature = base64.urlsafe_b64encode(
            hmac.new(
                settings.ui_auth_token_secret.encode("utf-8"),
                encoded_payload,
                hashlib.sha256,
            ).digest()
        ).rstrip(b"=")
        if not hmac.compare_digest(encoded_signature, expected_signature):
            return None
        payload_bytes = base64.urlsafe_b64decode(encoded_payload + b"=" * (-len(encoded_payload) % 4))
        payload: Any = json.loads(payload_bytes)
        if not isinstance(payload, dict):
            return None
        username = payload.get("sub")
        expires_at = payload.get("exp")
        if (
            payload.get("aud") != "vahan-rpa-ui"
            or payload.get("typ") != "access"
            or not isinstance(username, str)
            or ("exp" in payload and (type(expires_at) is not int or expires_at <= int(time.time())))
        ):
            return None
        return payload
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
        return None


def verify_access_token(token: str) -> str | None:
    payload = _verified_payload(token)
    username = payload.get("sub") if payload else None
    return username if isinstance(username, str) else None


def access_token_expiry(token: str) -> int | None:
    payload = _verified_payload(token)
    expires_at = payload.get("exp") if payload else None
    return expires_at if isinstance(expires_at, int) else None


def runner_token_matches(candidate: str | None) -> bool:
    if not candidate or len(settings.runner_token) < 24 or settings.runner_token == 'change-me':
        return False
    return secrets.compare_digest(candidate.encode(), settings.runner_token.encode())


async def authenticate_access_token(token: str):
    from app.services import services
    payload = _verified_payload(token)
    if not payload or not isinstance(payload.get("sid"), str):
        return None
    user = await services.users.session_user(payload["sub"], payload["sid"])
    return {**user, "session_id": payload["sid"]} if user else None
