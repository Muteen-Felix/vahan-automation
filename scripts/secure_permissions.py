"""Apply owner-only permissions to local secrets and backup artifacts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def restrict_permissions(path: Path, *, directory: bool = False) -> None:
    """Restrict a file or directory to the current user on POSIX and Windows."""
    if os.name != "nt":
        os.chmod(path, 0o700 if directory else 0o600)
        return

    identity = subprocess.run(
        ["whoami"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if not identity:
        raise RuntimeError("Could not determine the current Windows user for file permissions.")

    rights = "(OI)(CI)F" if directory else "F"
    result = subprocess.run(
        ["icacls.exe", str(path), "/reset", "/inheritance:r", "/grant:r", f"{identity}:{rights}"],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(
            "Could not restrict local file permissions with icacls.exe. "
            "Run this command as the same Windows user who will run Docker Compose."
        )
