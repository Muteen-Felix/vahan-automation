"""Apply owner-only permissions to local secrets and backup artifacts."""

from __future__ import annotations

import os
import csv
import subprocess
from pathlib import Path


def restrict_permissions(path: Path, *, directory: bool = False) -> None:
    """Restrict a file or directory to the current user on POSIX and Windows."""
    if os.name != "nt":
        os.chmod(path, 0o700 if directory else 0o600)
        return

    identity_output = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"], check=True, capture_output=True, text=True
    ).stdout.strip()
    identity = next(csv.reader([identity_output]))[-1] if identity_output else ''
    if not identity:
        raise RuntimeError("Could not determine the current Windows user for file permissions.")

    rights = "(OI)(CI)F" if directory else "F"
    # /reset cannot be combined with /grant; use the SID to avoid domain-name lookup.
    subprocess.run(["icacls.exe", str(path), "/reset"], check=True, capture_output=True, text=True)
    result = subprocess.run(
        ["icacls.exe", str(path), "/inheritance:r", "/grant:r", f"*{identity}:{rights}"],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(
            "Could not restrict local file permissions with icacls.exe. "
            "Run this command as the same Windows user who will run Docker Compose."
        )
