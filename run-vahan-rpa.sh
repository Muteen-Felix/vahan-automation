#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
python3 scripts/setup-docker.py
docker compose --env-file .docker.env build
# Create spare crawler containers without starting their Chromium processes.
docker compose --env-file .docker.env create --no-build runner runner-2 runner-3 runner-4 runner-5 runner-6 runner-7 runner-8 runner-9 runner-10
# The API restores the selected count and starts only that many crawlers.
docker compose --env-file .docker.env up -d --no-build postgres worker-control api web
docker compose --env-file .docker.env ps
