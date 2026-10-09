"""Redacted structured events for the application's local audit history."""
from contextvars import ContextVar
import json
import logging
import re
from uuid import uuid4
from app.config import settings

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
                   settings.browser_state_key, settings.mfa_key]
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


