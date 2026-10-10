#!/usr/bin/env python3
"""Build and start the Compose stack using commands that work on all host OSes."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from worker_capacity import assess_worker_capacity, print_assessment


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "--env-file", ".docker.env"]


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
    parser.add_argument(
        "--assess-only",
        action="store_true",
        help="assess single-host worker capacity without changing running services",
    )
    parser.add_argument(
        "--workers",
        default=os.environ.get("VAHAN_WORKER_REPLICAS", "auto"),
        help="browser-worker instances to run, or 'auto' to assess this server (default: auto)",
    )
    args = parser.parse_args()
    worker_setting = str(args.workers).strip().lower()
    if worker_setting == "auto":
        worker_count = None
    else:
        try:
            worker_count = int(worker_setting)
        except ValueError:
            parser.error("--workers must be 'auto' or a positive integer")
        if worker_count < 1:
            parser.error("--workers must be 'auto' or a positive integer")

    run([sys.executable, "scripts/setup-docker.py"])
    run([*COMPOSE, "config", "--quiet"])
    if args.config_only:
        print("Docker Compose configuration is valid.")
        return 0

    if args.assess_only:
        print_assessment(assess_worker_capacity())
        return 0

    if not args.no_build:
        run([*COMPOSE, "build"])
    if worker_count is None:
        assessment = assess_worker_capacity()
        print_assessment(assessment)
        worker_count = assessment.recommended_workers
        if worker_count < 1:
            print(
                "The current host does not have enough measured headroom for one browser runner.",
                file=sys.stderr,
            )
            return 2
    else:
        print(f"Using the manually configured worker count: {worker_count}.")
    # Remove the retired controller when upgrading an existing deployment.
    run([*COMPOSE, "up", "-d", "--no-build", "--remove-orphans", "--scale",
         f"runner={worker_count}", "postgres", "api", "web", "runner"])
    run([*COMPOSE, "ps"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from error
