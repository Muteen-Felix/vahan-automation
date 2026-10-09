"""Protected dotenv utilities shared by provisioning, deployment and backups."""
from pathlib import Path
from secure_permissions import restrict_permissions


def read_env(path):
    values = {}
    for raw in Path(path).read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'): continue
        if line.startswith('export '): line = line[7:]
        key, separator, value = line.partition('=')
        if separator: values[key.strip()] = value.strip().strip('"\'')
    return values


def append_missing(path, values):
    path = Path(path)
    existing = read_env(path) if path.exists() else {}
    additions = {key:value for key,value in values.items() if key not in existing}
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    original = path.read_text(encoding='utf-8') if path.exists() else ''
    if original and not original.endswith('\n'): original += '\n'
    for key, value in additions.items():
        if '\n' in str(value) or '\r' in str(value): raise ValueError('Invalid environment value.')
        original += f'{key}={value}\n'
    path.write_text(original, encoding='utf-8')
    restrict_permissions(path)
    return {**existing, **additions}
