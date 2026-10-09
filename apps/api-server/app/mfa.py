"""Encrypted TOTP enrollment, replay prevention and one-use recovery codes."""
import base64
from datetime import timedelta
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import quote

from cryptography.fernet import Fernet
import pyotp
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from fastapi import HTTPException
from app.config import settings
from app.db import engine, schema as db
from app.repositories.postgres import now


def fingerprint(password_hash):
    return hmac.new(settings.ui_auth_token_secret.encode(),
                    f'mfa:{settings.tenant_id}:{password_hash}'.encode(), hashlib.sha256).hexdigest()


def setup_challenge(user):
    body = {'sub': user['username'], 'tenant': settings.tenant_id, 'typ': 'mfa-setup',
            'exp': int(time.time()) + 300, 'pwd': fingerprint(user['password_hash'])}
    payload = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b'=')
    signature = hmac.new(settings.ui_auth_token_secret.encode(), payload, hashlib.sha256).digest()
    return payload.decode() + '.' + base64.urlsafe_b64encode(signature).rstrip(b'=').decode()


async def setup_user(token):
    from app.services import services
    try:
        encoded, signature = token.split('.')
        expected = base64.urlsafe_b64encode(hmac.new(settings.ui_auth_token_secret.encode(),
                    encoded.encode(), hashlib.sha256).digest()).rstrip(b'=').decode()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        value = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
        if value.get('typ') != 'mfa-setup' or value.get('tenant') != settings.tenant_id or value['exp'] <= time.time():
            raise ValueError()
        user = await services.users.get(value['sub'])
        if not user or not user['active'] or user['role'] != 'admin' or not hmac.compare_digest(
                value['pwd'], fingerprint(user['password_hash'])):
            raise ValueError()
        return user
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise HTTPException(401, 'Enrollment expired. Sign in again.') from None


def cipher():
    if not settings.mfa_key:
        raise HTTPException(503, 'MFA encryption is not configured.')
    return Fernet(settings.mfa_key.encode())


async def enabled(username):
    async with engine.connect() as connection:
        return bool(await connection.scalar(select(db.user_mfa.c.secret).where(db.user_mfa.c.username == username)))


async def enroll(user):
    secret = pyotp.random_base32()
    encrypted = cipher().encrypt(secret.encode())
    async with engine.begin() as connection:
        await lock_enrollment_user(connection, user)
        statement = insert(db.user_mfa).values(username=user['username'], pending_secret=encrypted,
                    pending_expires_at=now() + timedelta(minutes=5), recovery_hashes=[])
        await connection.execute(statement.on_conflict_do_update(index_elements=[db.user_mfa.c.username],
                    set_={'pending_secret': encrypted, 'pending_expires_at': now() + timedelta(minutes=5)},
                    where=db.user_mfa.c.secret.is_(None)))
        active = await connection.scalar(select(db.user_mfa.c.secret).where(db.user_mfa.c.username == user['username']))
        if active:
            raise HTTPException(409, 'MFA is already enabled. Use a recovery code if necessary.')
    return {'secret': secret, 'uri': pyotp.TOTP(secret).provisioning_uri(
            name=user['username'], issuer_name=f'VAHAN {settings.tenant_id}')}


def matching_counter(secret, value):
    if not value.isdigit() or len(value) != 6:
        return None
    otp = pyotp.TOTP(secret)
    current = int(time.time()) // otp.interval
    for counter in [current, current - 1, current + 1]:
        if hmac.compare_digest(otp.generate_otp(counter), value):
            return counter
    return None


def recovery_hash(value):
    normalized = value.replace('-', '').replace(' ', '').upper()
    return hmac.new(settings.ui_auth_token_secret.encode(),
                    f'recovery:{settings.tenant_id}:{normalized}'.encode(), hashlib.sha256).hexdigest()


async def confirm(user, value):
    codes = [secrets.token_hex(10).upper() for _ in range(10)]
    async with engine.begin() as connection:
        await lock_enrollment_user(connection, user)
        row = (await connection.execute(select(db.user_mfa).where(db.user_mfa.c.username == user['username'])
                .with_for_update())).mappings().first()
        if not row or row['secret'] or not row['pending_expires_at'] or row['pending_expires_at'] <= now():
            raise HTTPException(409, 'Enrollment expired or already completed.')
        secret = cipher().decrypt(row['pending_secret']).decode()
        counter = matching_counter(secret, value)
        if counter is None:
            raise HTTPException(401, 'The verification code is incorrect.')
        await connection.execute(update(db.user_mfa).where(db.user_mfa.c.username == user['username']).values(
            secret=row['pending_secret'], pending_secret=None, pending_expires_at=None,
            last_counter=counter, recovery_hashes=[recovery_hash(code) for code in codes]))
        await connection.execute(update(db.auth_sessions).where(db.auth_sessions.c.username == user['username'])
                                .values(revoked=True))
    return codes


async def lock_enrollment_user(connection, expected):
    current = (await connection.execute(select(db.users).where(db.users.c.username == expected['username'])
                                        .with_for_update())).mappings().first()
    if not current or not current['active'] or current['role'] != expected['role'] or not hmac.compare_digest(
            current['password_hash'], expected['password_hash']):
        raise HTTPException(401, 'Credentials changed. Sign in again before enrolling.')


async def verify(username, value):
    async with engine.begin() as connection:
        row = (await connection.execute(select(db.user_mfa).where(db.user_mfa.c.username == username)
                                        .with_for_update())).mappings().first()
        if not row or not row['secret']:
            return False
        counter = matching_counter(cipher().decrypt(row['secret']).decode(), value)
        if counter is not None and counter > row['last_counter']:
            await connection.execute(update(db.user_mfa).where(db.user_mfa.c.username == username)
                                     .values(last_counter=counter))
            return True
        expected = recovery_hash(value)
        hashes = row['recovery_hashes'] or []
        if any(hmac.compare_digest(expected, candidate) for candidate in hashes):
            await connection.execute(update(db.user_mfa).where(db.user_mfa.c.username == username)
                                     .values(recovery_hashes=[v for v in hashes if v != expected]))
            return True
        return False
