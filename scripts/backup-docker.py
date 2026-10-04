#!/usr/bin/env python3
"""Back up SQL and its encryption/signing configuration without printing secrets."""
from datetime import datetime, timezone
from pathlib import Path
import os, shutil, subprocess

root = Path(__file__).resolve().parents[1]
destination = root / 'backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
destination.mkdir(parents=True, mode=0o700)
dump = destination / 'database.dump'
try:
    with dump.open('wb') as output:
        os.chmod(dump, 0o600)
        subprocess.run(['docker', 'compose', '--env-file', '.docker.env', 'exec', '-T',
            'postgres', 'pg_dump', '-U', 'vahan', '-d', 'vahan', '-Fc'], cwd=root, stdout=output, check=True)
    config = destination / '.docker.env'
    shutil.copyfile(root / '.docker.env', config)
    config.chmod(0o600)
except Exception:
    dump.unlink(missing_ok=True)
    raise
print(f'Backup created: {destination}')
