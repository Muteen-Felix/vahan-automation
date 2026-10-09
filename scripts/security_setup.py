"""Provision independent credentials without rotating existing encryption keys."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit
from environment import append_missing, read_env

ROOT = Path(__file__).resolve().parents[1]


def provision(path, tenant='legacy', api_port='8000', web_port='5173', public_origin=None, project=None):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', tenant):
        raise ValueError('Tenant ID must use lowercase letters, digits and dashes.')
    current = read_env(path) if path.exists() else {}
    if current.get('VAHAN_TENANT_ID', tenant) != tenant:
        raise ValueError('Environment belongs to another tenant.')
    if public_origin:
        parsed = urlsplit(public_origin)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.path not in {'', '/'} or parsed.query or parsed.fragment:
            raise ValueError('Specify an HTTP(S) origin without a path or query.')
        public_origin = public_origin.rstrip('/')
    origin = public_origin or f'http://127.0.0.1:{web_port}'
    if public_origin and current.get('VAHAN_PUBLIC_ORIGIN') not in {None, origin}:
        raise ValueError('Public origin differs from existing configuration; update it deliberately.')
    defaults = {
        'POSTGRES_PASSWORD': secrets.token_hex(32), 'VAHAN_UI_AUTH_USERNAME': 'admin',
        'VAHAN_UI_AUTH_PASSWORD': secrets.token_urlsafe(32),
        'VAHAN_UI_AUTH_TOKEN_SECRET': secrets.token_hex(48),
        'VAHAN_BROWSER_STATE_KEY': base64.urlsafe_b64encode(os.urandom(32)).decode(),
        'VAHAN_MFA_ENCRYPTION_KEY': base64.urlsafe_b64encode(os.urandom(32)).decode(),
        'VAHAN_SOC_INGEST_KEY': secrets.token_hex(32),
        'VAHAN_SOC_BACKUP_KEY': secrets.token_hex(32),
        'VAHAN_DB_RUNTIME_PASSWORD': secrets.token_hex(32),
        'VAHAN_DB_MIGRATION_PASSWORD': secrets.token_hex(32),
        'VAHAN_DB_BACKUP_PASSWORD': secrets.token_hex(32),
        'VAHAN_TENANT_ID': tenant,
        'COMPOSE_PROJECT_NAME': project or ('vahan-automation' if tenant == 'legacy' else f'vahan-{tenant}'),
        'API_PORT': api_port, 'WEB_PORT': web_port,
        'API_BIND_ADDRESS': '127.0.0.1', 'WEB_BIND_ADDRESS': '127.0.0.1',
        'VAHAN_PUBLIC_ORIGIN': origin,
        'VAHAN_ALLOWED_ORIGINS': origin if public_origin else f'{origin},http://localhost:{web_port}',
        'VAHAN_COOKIE_SECURE': 'true' if origin.startswith('https:') else 'false',
        'VAHAN_IMAGE_NAMESPACE': 'vahan-automation', 'VAHAN_IMAGE_TAG': 'soc',
        'VAHAN_BACKUP_IDENTITY_FILE': f'.secrets/{tenant}-backup.agekey',
    }
    local = ROOT / 'apps/api-server/.env'
    if not path.exists() and path.resolve() == (ROOT / '.docker.env').resolve() and local.exists():
        for key, value in read_env(local).items():
            if key in {'VAHAN_UI_AUTH_USERNAME','VAHAN_UI_AUTH_PASSWORD','VAHAN_UI_AUTH_TOKEN_SECRET'} and value:
                defaults[key] = value
    tokens = json.loads(current.get('VAHAN_RUNNER_TOKENS', '{}'))
    for number in range(1, 11):
        key, identity = f'VAHAN_RUNNER_TOKEN_{number}', f'playwright-{number}'
        token = current.get(key) or tokens.get(identity) or secrets.token_urlsafe(36)
        defaults[key] = token; tokens[identity] = token
    defaults['VAHAN_RUNNER_TOKENS'] = json.dumps(tokens, separators=(',', ':'))
    values = append_missing(path, defaults)
    configured = json.loads(values['VAHAN_RUNNER_TOKENS'])
    if len(set(configured.values())) != 10 or any(len(v) < 32 for v in configured.values()):
        raise ValueError('Configure ten distinct private worker credentials.')
    for number in range(1, 11):
        if configured.get(f'playwright-{number}') != values[f'VAHAN_RUNNER_TOKEN_{number}']:
            raise ValueError('Worker credential map does not match worker configuration.')
    if values['API_BIND_ADDRESS'] != '127.0.0.1' or values['WEB_BIND_ADDRESS'] != '127.0.0.1':
        raise ValueError('Bind private services to loopback and use a controlled TLS ingress.')
    print(f'Protected configuration ready for tenant {tenant}: {path}')
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.docker.env')
    parser.add_argument('--tenant', default='legacy')
    parser.add_argument('--project')
    parser.add_argument('--api-port', default='8000')
    parser.add_argument('--web-port', default='5173')
    parser.add_argument('--public-origin')
    args = parser.parse_args()
    provision(args.env_file, args.tenant, args.api_port, args.web_port, args.public_origin, args.project)
