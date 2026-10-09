#!/usr/bin/env python3
"""Build and start the Compose stack using commands that work on all host OSes."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from environment import read_env, append_missing
from deployment import drain, resume, running
from backup_security import create as backup, identity


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
    parser.add_argument('--env-file',type=Path,default=ROOT/'.docker.env')
    parser.add_argument('--tenant',default='legacy')
    parser.add_argument('--image-overrides',type=Path)
    args = parser.parse_args()

    run([sys.executable, "scripts/setup-docker.py",'--env-file',str(args.env_file),'--tenant',args.tenant])
    values=read_env(args.env_file)
    command=['docker','compose','--env-file',str(args.env_file),'-p',values['COMPOSE_PROJECT_NAME']]
    if args.image_overrides:
        command.extend(['-f',str(ROOT/'compose.yaml'),'-f',str(args.image_overrides.resolve())])
    run([*command, "config", "--quiet"])
    if args.config_only:
        print("Docker Compose configuration is valid.")
        return 0

    key=Path(values['VAHAN_BACKUP_IDENTITY_FILE']).expanduser()
    key=(key if key.is_absolute() else ROOT/key).resolve()
    values=append_missing(args.env_file,{'VAHAN_BACKUP_RECIPIENT':identity(key)})

    if not args.no_build:
        run([*command, "build"])
    # Remove the retired controller when upgrading an existing deployment.
    held=drain(command)
    changed=False
    try:
        if running(command,'postgres'):backup(args.env_file)
        if held:run([*command,'stop','api',*RUNNERS])
        changed=True
        run([*command,'up','-d','--no-build','--wait','--wait-timeout','120','postgres'])
        # Run the one-shot migration for every release, even if an old
        # successful migrator still has the same Compose configuration hash.
        run([*command,'rm','-f','migrate'])
        run([*command,'up','-d','--no-build','--remove-orphans','--wait','--wait-timeout','240',
             'postgres','documents','backup','api','web',*RUNNERS])
        run([*command,'ps'])
    finally:
        if held and not changed:resume(command)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from error
