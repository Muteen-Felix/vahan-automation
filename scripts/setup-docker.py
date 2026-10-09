#!/usr/bin/env python3
"""Generate ignored local Docker secrets without overwriting an existing configuration."""
import argparse, base64, os, secrets
from pathlib import Path
from secure_permissions import restrict_permissions
root = Path(__file__).resolve().parents[1]
path = root / '.docker.env'
# Dockerfiles copy this optional certificate directory even on machines with no custom CA.
certs = root / 'docker' / 'certs'
certs.mkdir(parents=True, exist_ok=True)
(certs / '.gitkeep').touch(exist_ok=True)
parser = argparse.ArgumentParser()
parser.add_argument('--api-port', default='8000')
parser.add_argument('--web-port', default='5173')
args = parser.parse_args()

def read_env_file(env_path):
    values = {}
    try:
        lines = env_path.read_text().splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        key, separator, value = line.partition('=')
        if separator:
            values[key.strip()] = value.strip().strip('"\'')
    return values

if path.exists():
    print(f'Using existing {path}')
else:
    values = {'POSTGRES_PASSWORD': secrets.token_hex(24), 'VAHAN_UI_AUTH_USERNAME': 'admin',
        'VAHAN_UI_AUTH_PASSWORD': secrets.token_urlsafe(24), 'VAHAN_UI_AUTH_TOKEN_SECRET': secrets.token_hex(48),
        'VAHAN_API_RUNNER_TOKEN': secrets.token_urlsafe(36),
        'VAHAN_BROWSER_STATE_KEY': base64.urlsafe_b64encode(os.urandom(32)).decode(),
        'API_PORT': args.api_port, 'WEB_PORT': args.web_port,
        'API_BIND_ADDRESS': '127.0.0.1', 'WEB_BIND_ADDRESS': '127.0.0.1',
        'VAHAN_IMAGE_NAMESPACE': 'vahan-automation', 'VAHAN_IMAGE_TAG': 'local'}
    # Retain the existing local login when upgrading this checkout.
    local = root / 'apps/api-server/.env'
    if local.exists():
        for line in local.read_text().splitlines():
            key, separator, value = line.partition('=')
            if separator and key in ('VAHAN_UI_AUTH_USERNAME', 'VAHAN_UI_AUTH_PASSWORD',
                                     'VAHAN_UI_AUTH_TOKEN_SECRET', 'VAHAN_API_RUNNER_TOKEN'):
                cleaned = value.strip().strip('\"\'')
                if key == 'VAHAN_API_RUNNER_TOKEN' and (len(cleaned) < 24 or cleaned == 'change-me'):
                    continue
                if cleaned:
                    values[key] = cleaned
    path.write_text(''.join(f'{k}={v}\n' for k,v in values.items()))
    print(f'Created {path}; credentials remain in this ignored file.')

restrict_permissions(path)

runner_token = read_env_file(path).get('VAHAN_API_RUNNER_TOKEN', '')
if len(runner_token) < 24 or runner_token == 'change-me':
    raise SystemExit(f'{path} must contain a private VAHAN_API_RUNNER_TOKEN (at least 24 characters).')

# Docker Desktop and plain `docker compose` look for `.env` automatically.
# Point that default at the same protected file used by the launch script.
compose_env = root / '.env'
if compose_env.is_symlink():
    if compose_env.resolve() != path.resolve():
        raise SystemExit(f'{compose_env} is a symlink to another file; preserve it and pass --env-file .docker.env to Compose.')
elif not compose_env.exists():
    if os.name == 'nt':
        print('Windows uses explicit --env-file .docker.env; no .env symlink is needed.')
    else:
        compose_env.symlink_to(path.name)
        print(f'Linked {compose_env} to {path.name} for Docker Desktop Compose launches.')
