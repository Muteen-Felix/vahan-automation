#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
python3 scripts/setup-docker.py
docker compose --env-file .docker.env up -d --build
docker compose --env-file .docker.env ps
