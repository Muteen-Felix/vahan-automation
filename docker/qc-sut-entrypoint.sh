#!/bin/sh
# QC image entrypoint: embedded PostgreSQL + migrations + API, for a SUT that qc-agent builds and runs on its own.
# VAHAN_UI_AUTH_USERNAME and VAHAN_UI_AUTH_PASSWORD must come from the environment (qc-agent passes the repo secrets).
set -eu

if ! python -c 'import os,sys; sys.exit(0 if os.environ.get("VAHAN_UI_AUTH_USERNAME","").strip() and len(os.environ.get("VAHAN_UI_AUTH_PASSWORD",""))>=12 else 1)'; then
    echo "qc-sut: VAHAN_UI_AUTH_USERNAME must be set and VAHAN_UI_AUTH_PASSWORD must have at least 12 characters (no user would be created)." >&2
    exit 1
fi

# A fresh signing key per start; a value supplied by the caller wins.
if [ -z "${VAHAN_UI_AUTH_TOKEN_SECRET:-}" ]; then
    VAHAN_UI_AUTH_TOKEN_SECRET=$(python -c 'import secrets; print(secrets.token_hex(48))')
    export VAHAN_UI_AUTH_TOKEN_SECRET
fi

PGBIN=/usr/lib/postgresql/17/bin
PGDATA=/home/vahan/pgdata
if [ ! -s "$PGDATA/PG_VERSION" ]; then
    "$PGBIN/initdb" -D "$PGDATA" -U vahan --auth=trust --encoding=UTF8 --locale=C.UTF-8 >/dev/null
fi
# Loopback only and trust auth: the database exists for this container alone.
"$PGBIN/pg_ctl" -D "$PGDATA" -o "-c listen_addresses=127.0.0.1 -c unix_socket_directories=/tmp" -w -t 60 -l /tmp/postgres.log start >/dev/null
"$PGBIN/createdb" -h 127.0.0.1 -U vahan vahan

export DATABASE_URL=postgresql+asyncpg://vahan@127.0.0.1:5432/vahan
python -m app.migrate

# uvicorn becomes PID 1; PostgreSQL goes down with the container (the database is disposable).
exec uvicorn app.main:application --host 0.0.0.0 --port 8000
