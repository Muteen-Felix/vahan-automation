"""Redacted structured events and durable forwarding to an independent collector."""
import asyncio
from contextvars import ContextVar
import hashlib
import hmac
import json
import logging
import re
from datetime import timedelta
from urllib.request import Request, build_opener, ProxyHandler
from uuid import uuid4
from sqlalchemy import insert, select, update
from app.config import settings
from app.db import engine, schema as db

request_context = ContextVar('security_request', default={})
logger = logging.getLogger('vahan.security')
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)
    logger.propagate = False
SENSITIVE = re.compile(r'password|secret|authorization|cookie|captcha.*value|storage.?state|token|recovery.?codes', re.I)


def redact(value):
    if isinstance(value, dict):
        return {str(k): '[REDACTED]' if SENSITIVE.search(str(k)) else redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value[:100]]
    if isinstance(value, str):
        value = re.sub(r'(?i)Bearer\s+[^\s"\']+', 'Bearer [REDACTED]', value)
        private = [settings.ui_auth_password, settings.ui_auth_token_secret, settings.runner_token,
                   settings.browser_state_key, settings.mfa_key, settings.soc_ingest_key]
        if settings.runner_tokens:
            private.extend(json.loads(settings.runner_tokens).values())
        for secret in private:
            if len(secret) >= 16:
                value = value.replace(secret, '[REDACTED]')
        return value[:8000]
    return value


def event(actor, name, payload):
    from app.repositories.postgres import now
    value = {'id': str(uuid4()), 'timestamp': now().isoformat(), 'tenantId': settings.tenant_id,
             'service': 'api', 'actor': actor, 'event': name,
             'context': request_context.get(), 'payload': redact(payload)}
    logger.info(json.dumps(value, ensure_ascii=True, default=str))
    return value


async def enqueue(connection, value):
    from app.repositories.postgres import now
    await connection.execute(insert(db.soc_outbox).values(id=value['id'], payload=value,
        created_at=now(), delivered=False, attempts=0, next_attempt_at=now()))


async def forward_loop():
    from app.repositories.postgres import now
    heartbeat_due = 0.0
    while True:
        try:
            if settings.soc_url and settings.soc_ingest_key:
                if asyncio.get_running_loop().time() >= heartbeat_due:
                    from app.repositories.postgres import audit
                    await audit(None, 'service.heartbeat', {})
                    heartbeat_due = asyncio.get_running_loop().time() + 30
                async with engine.connect() as connection:
                    rows = (await connection.execute(select(db.soc_outbox).where(
                        db.soc_outbox.c.delivered.is_(False), db.soc_outbox.c.next_attempt_at <= now())
                        .order_by(db.soc_outbox.c.created_at).limit(50))).mappings().all()
                for row in rows:
                    data = json.dumps(row['payload'], ensure_ascii=True, default=str).encode()
                    signature = hmac.new(settings.soc_ingest_key.encode(), data, hashlib.sha256).hexdigest()
                    def send():
                        request = Request(settings.soc_url.rstrip('/') + '/events', data=data,
                            headers={'Content-Type': 'application/json', 'X-SOC-Signature': signature})
                        with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
                            if response.status != 202:
                                raise OSError('SOC delivery rejected')
                    try:
                        await asyncio.to_thread(send)
                        values = {'delivered': True, 'delivered_at': now()}
                    except Exception:
                        attempts = row['attempts'] + 1
                        values = {'attempts': attempts,
                                  'next_attempt_at': now() + timedelta(seconds=min(300, 2 ** min(attempts, 8)))}
                    async with engine.begin() as connection:
                        await connection.execute(update(db.soc_outbox).where(db.soc_outbox.c.id == row['id'])
                                                 .values(**values))
            await asyncio.sleep(2)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not include SQL parameters, tokens or connection strings.
            logger.error(json.dumps({'event': 'soc.delivery_failed', 'tenantId': settings.tenant_id}))
            await asyncio.sleep(5)
