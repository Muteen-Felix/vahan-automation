#!/usr/bin/env python3
"""Back up SQL and its encryption/signing configuration without printing secrets."""
from datetime import datetime, timezone
from pathlib import Path
import shutil, subprocess, hashlib, json
from secure_permissions import restrict_permissions

root = Path(__file__).resolve().parents[1]
destination = root / 'backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
destination.mkdir(parents=True, mode=0o700)
restrict_permissions(destination, directory=True)
dump = destination / 'database.dump'
try:
    with dump.open('wb') as output:
        subprocess.run(['docker', 'compose', '--env-file', '.docker.env', 'exec', '-T',
            'postgres', 'pg_dump', '-U', 'vahan', '-d', 'vahan', '-Fc'], cwd=root, stdout=output, check=True)
    restrict_permissions(dump)
    with dump.open('rb') as source:
        subprocess.run(['docker','compose','--env-file','.docker.env','exec','-T','postgres',
            'pg_restore','--list'], cwd=root, stdin=source, stdout=subprocess.DEVNULL, check=True)
    config = destination / '.docker.env'
    shutil.copyfile(root / '.docker.env', config)
    restrict_permissions(config)
    manifest = destination / 'manifest.json'
    checksums = {}
    for artifact in (dump, config):
        with artifact.open('rb') as source:
            checksums[artifact.name] = hashlib.file_digest(source, 'sha256').hexdigest()
    manifest.write_text(json.dumps({'createdAt':datetime.now(timezone.utc).isoformat(),
        'archiveListingVerified':True,'sha256':checksums},indent=2)+'\n')
    restrict_permissions(manifest)
except Exception:
    dump.unlink(missing_ok=True)
    raise
print(f'Backup created: {destination}')
