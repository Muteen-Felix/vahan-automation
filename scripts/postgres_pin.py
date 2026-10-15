"""Single source of truth for the official PostgreSQL image pin (PLAN T21a, D-33).

The reference is read from compose.yaml so the scanner, packager and tests can
never drift from the file Docker Compose actually runs.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_PATTERN = re.compile(
    r"docker\.io/library/postgres:[0-9][0-9A-Za-z.\-]*@sha256:[0-9a-f]{64}")
POSTGRES_MAJOR = "17"


def postgres_service_block(compose_text: str) -> str:
    match = re.search(r"^  postgres:\n((?:    .*\n|\n)+)", compose_text, re.MULTILINE)
    if not match:
        raise ValueError("compose.yaml has no postgres service block.")
    return match.group(1)


def pinned_reference(compose_path: Path = ROOT / "compose.yaml") -> str:
    block = postgres_service_block(compose_path.read_text(encoding="utf-8"))
    image = re.search(r"^    image:\s*(\S+)\s*$", block, re.MULTILINE)
    if not image or not REFERENCE_PATTERN.fullmatch(image.group(1)):
        raise ValueError("postgres image must be docker.io/library/postgres:<tag>@sha256:<digest>.")
    if re.search(r"^    build:", block, re.MULTILINE):
        raise ValueError("postgres must not be built locally (D-33).")
    return image.group(1)


def digest_of(reference: str) -> str:
    return reference.rsplit("@", 1)[1]
