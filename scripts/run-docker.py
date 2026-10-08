#!/usr/bin/env python3
"""Build and start the Compose stack using commands that work on all host OSes."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "--env-file", ".docker.env"]
RUNNERS = ["runner", *(f"runner-{number}" for number in range(2, 11))]


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config-only",
        action="store_true",
        help="create or verify local settings and validate Compose without changing services",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="use already-built or docker-loaded images",
    )
    args = parser.parse_args()

    run([sys.executable, "scripts/setup-docker.py"])
    run([*COMPOSE, "config", "--quiet"])
    if args.config_only:
        print("Docker Compose configuration is valid.")
        return 0

    if not args.no_build:
        run([*COMPOSE, "build"])
    run([*COMPOSE, "create", "--no-build", *RUNNERS])
    run([*COMPOSE, "up", "-d", "--no-build", "postgres", "worker-control", "api", "web"])
    run([*COMPOSE, "ps"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from error
