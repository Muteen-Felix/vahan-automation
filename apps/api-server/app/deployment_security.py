"""Fail closed if a tenant starts against another tenant's database."""
import json
import re
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from cryptography.fernet import Fernet
from app.config import settings
from app.db import engine, schema as db


async def verify_deployment():
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', settings.tenant_id):
        raise RuntimeError('Invalid deployment tenant ID.')
    if settings.production:
        from urllib.parse import urlsplit
        remote = [urlsplit(origin) for origin in settings.cors_origins
                  if urlsplit(origin).hostname not in {'127.0.0.1', 'localhost', '::1'}]
        if any(origin.scheme != 'https' for origin in remote) or (remote and not settings.cookie_secure):
            raise RuntimeError('Remote production access requires HTTPS and Secure session cookies.')
        tokens = json.loads(settings.runner_tokens or '{}')
        expected = {f'playwright-{n}' for n in range(1, 11)}
        if set(tokens) != expected or any(len(v) < 32 for v in tokens.values()) or len(set(tokens.values())) != len(tokens):
            raise RuntimeError('Production requires unique private credentials for each worker.')
        if '*' in settings.cors_origins or settings.socketio_cors_origins == '*' or '*' in settings.socketio_cors_origins:
            raise RuntimeError('Wildcard origins are forbidden in production.')
        if not settings.require_admin_mfa or not settings.mfa_key or not settings.soc_url or not settings.soc_ingest_key:
            raise RuntimeError('Production requires MFA and an independent SOC collector.')
        Fernet(settings.mfa_key.encode())
    async with engine.begin() as connection:
        if not settings.production:
            await connection.execute(insert(db.deployment_identity).values(id=1, tenant_id=settings.tenant_id)
                .on_conflict_do_nothing())
        tenant = await connection.scalar(select(db.deployment_identity.c.tenant_id).where(db.deployment_identity.c.id == 1))
        if tenant != settings.tenant_id:
            raise RuntimeError('Database belongs to a different tenant. Startup refused.')
        if settings.production:
            privileged = await connection.scalar(text(
                'SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls FROM pg_roles WHERE rolname = current_user'))
            if privileged:
                raise RuntimeError('Production runtime database role must not be privileged.')
