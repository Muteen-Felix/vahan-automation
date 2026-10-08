#!/usr/bin/env python3
"""Back up SQL and its encryption/signing configuration without printing secrets."""
from datetime import datetime, timezone
from pathlib import Path
import shutil, subprocess
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
    config = destination / '.docker.env'
    shutil.copyfile(root / '.docker.env', config)
    restrict_permissions(config)
except Exception:
    dump.unlink(missing_ok=True)
    raise
print(f'Backup created: {destination}')
