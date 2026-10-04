#!/usr/bin/env python3
"""Snapshot jobs still held in RAM by the pre-PostgreSQL API."""
import argparse, json, urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--api-url', default='http://127.0.0.1:8000')
parser.add_argument('--output', type=Path, default=root / 'apps/api-server/runtime/migration-snapshot.json')
args = parser.parse_args()
values = {}
for raw in (root / 'apps/api-server/.env').read_text().splitlines():
    key, separator, value = raw.strip().removeprefix('export ').partition('=')
    if separator:
        values[key] = value.strip().strip('\"\'')
body = json.dumps({'username': values['VAHAN_UI_AUTH_USERNAME'], 'password': values['VAHAN_UI_AUTH_PASSWORD']}).encode()
def call(path, body=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return json.load(urllib.request.urlopen(urllib.request.Request(args.api_url.rstrip('/') + path, body, headers), timeout=30))
token = call('/api/auth/login', body)['accessToken']
snapshot = call('/api/jobs/reports/sessions', token=token)
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
args.output.chmod(0o600)
print(f'Saved {len(snapshot)} sessions / {sum(len(s["jobs"]) for s in snapshot)} jobs to {args.output}')
