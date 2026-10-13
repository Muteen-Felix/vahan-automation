#!/usr/bin/env python3
"""Check repository-relative Markdown document links without external requests."""
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
files = [ROOT / 'README.md']
for directory in ('apps', 'docs', 'docker', 'tools'):
    files.extend(path for path in (ROOT / directory).rglob('*.md')
                 if not any(part in {'node_modules', '.venv', 'dist', 'runtime'} for part in path.parts))
broken = []
checked = 0
for document in files:
    body = re.sub(r'```.*?```', '', document.read_text(encoding='utf-8'), flags=re.S)
    for match in re.finditer(r'\[[^\]]*\]\(([^)]+)\)', body):
        target = match.group(1).strip().split(' "', 1)[0].strip('<>')
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        checked += 1
        path = document.parent / unquote(parsed.path)
        if not path.exists():
            broken.append(f'{document.relative_to(ROOT)} -> {target}')
for error in broken:
    print(error)
print(f'{checked} local document links checked; {len(broken)} missing targets.')
raise SystemExit(bool(broken))
