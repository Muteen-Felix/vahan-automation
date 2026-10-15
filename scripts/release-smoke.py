#!/usr/bin/env python3
"""Release smoke test for a running Compose stack (PLAN T27, C4.1, C2.3).

    VAHAN_SMOKE_ADMIN_PASSWORD=... python scripts/release-smoke.py --base-url http://127.0.0.1:5173 \
        --admin-user admin --min-runners 1 [--compose-project NAME] [--require-compose-checks] [--output smoke.json]

Checks (standard library only): /api/health, /api/ready (storage postgresql), web `/`, admin login, runners online >= N,
a throw-away member receives 403 on admin APIs including run-history (then is deactivated), and - when --compose-project
is given - service `migrate` exited 0 and the API connects as a DML-only role. Passwords are read from the environment
and never printed. Exit 0 only when every check passed (skipped checks fail with --require-compose-checks).
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request

RUNTIME_ROLE_CHECK = r"""
import asyncio
from sqlalchemy import text
from app.db import engine
async def main():
    async with engine.connect() as c:
        row = (await c.execute(text("SELECT current_user AS u, r.rolsuper, r.rolcreatedb, r.rolcreaterole, "
            "has_schema_privilege(current_user,'public','CREATE') AS schema_create FROM pg_roles r "
            "WHERE r.rolname=current_user"))).mappings().one()
    print(dict(row))
    assert not (row['rolsuper'] or row['rolcreatedb'] or row['rolcreaterole'] or row['schema_create'])
    await engine.dispose()
asyncio.run(main())
"""


def call(base: str, path: str, *, method: str = "GET", token: str | None = None, body=None, timeout: int = 20):
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(base.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        raw, status = error.read(), error.code
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return 0, {"error": type(error).__name__}
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, None


class Smoke:
    def __init__(self):
        self.results: list[dict] = []

    def record(self, name: str, ok: bool | None, detail: str = "") -> bool:
        started = getattr(self, "_t", time.time())
        self.results.append({"check": name, "result": "pass" if ok else ("skipped" if ok is None else "fail"),
                             "detail": detail, "seconds": round(time.time() - started, 2)})
        print(f"[{self.results[-1]['result'].upper():7}] {name}" + (f" - {detail}" if detail else ""), flush=True)
        self._t = time.time()
        return bool(ok)


def compose(project: str, *args: str, timeout: int = 60):
    return subprocess.run(["docker", "compose", "-p", project, *args], capture_output=True, text=True, timeout=timeout)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True, help="Web origin (Nginx), e.g. http://127.0.0.1:5173")
    parser.add_argument("--admin-user", default=os.environ.get("VAHAN_SMOKE_ADMIN_USER", "admin"))
    parser.add_argument("--password-env", default="VAHAN_SMOKE_ADMIN_PASSWORD")
    parser.add_argument("--min-runners", type=int, default=1)
    parser.add_argument("--runner-wait-seconds", type=int, default=120)
    parser.add_argument("--compose-project")
    parser.add_argument("--require-compose-checks", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    password = os.environ.get(args.password_env)
    if not password:
        print(f"error: set {args.password_env} (the password is not accepted on the command line)", file=sys.stderr)
        return 2
    smoke, base = Smoke(), args.base_url

    status, body = call(base, "/api/health")
    smoke.record("GET /api/health returns 200 ok", status == 200 and (body or {}).get("status") == "ok", f"status={status}")
    status, body = call(base, "/api/ready")
    smoke.record("GET /api/ready returns 200 with PostgreSQL storage",
                 status == 200 and (body or {}).get("status") == "ok" and (body or {}).get("storage") == "postgresql",
                 f"status={status} body={body}")
    status, _ = call(base, "/")
    smoke.record("web / returns 200", status == 200, f"status={status}")

    status, body = call(base, "/api/auth/login", method="POST", body={"username": args.admin_user, "password": password})
    token = (body or {}).get("accessToken") if status == 200 else None
    if not smoke.record("admin login returns an access token", bool(token), f"status={status}"):
        return finish(smoke, args)

    deadline, online = time.time() + args.runner_wait_seconds, 0
    while True:
        status, runners = call(base, "/api/runners", token=token)
        online = sum(1 for r in (runners or []) if str(r.get("status")).upper() == "ONLINE") if status == 200 else 0
        if online >= args.min_runners or time.time() > deadline:
            break
        time.sleep(3)
    smoke.record(f"at least {args.min_runners} runner(s) ONLINE", online >= args.min_runners, f"online={online}")

    member, member_password = f"smoke-member-{secrets.token_hex(4)}", secrets.token_urlsafe(24)
    status, _ = call(base, "/api/users", method="POST", token=token,
                     body={"username": member, "password": member_password, "role": "user"})
    if smoke.record("throw-away member created", status == 201, f"status={status}"):
        try:
            status, body = call(base, "/api/auth/login", method="POST",
                                body={"username": member, "password": member_password})
            member_token = (body or {}).get("accessToken")
            smoke.record("member can sign in", bool(member_token), f"status={status}")
            for path in ("/api/annual-reports/run-history?limit=1", "/api/users", "/api/audit"):
                status, _ = call(base, path, token=member_token)
                smoke.record(f"member gets 403 on {path.split('?')[0]}", status == 403, f"status={status}")
            status, _ = call(base, "/api/annual-reports/run-history?limit=1", token=token)
            smoke.record("admin can read run-history", status == 200, f"status={status}")
        finally:
            status, _ = call(base, f"/api/users/{member}", method="PATCH", token=token, body={"active": False})
            smoke.record("throw-away member deactivated", status == 200, f"status={status}")

    if args.compose_project:
        result = compose(args.compose_project, "ps", "-a", "--format", "json", "migrate")
        exit_ok = False
        try:
            rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip().startswith("{")]
            exit_ok = bool(rows) and all(r.get("State") == "exited" and r.get("ExitCode") == 0 for r in rows)
        except ValueError:
            pass
        smoke.record("service migrate exited 0", exit_ok, "docker compose ps -a migrate")
        role = compose(args.compose_project, "exec", "-T", "api", "python", "-c", RUNTIME_ROLE_CHECK, timeout=90)
        smoke.record("API connects as a DML-only database role (S12)", role.returncode == 0,
                     (role.stdout.strip() or role.stderr.strip())[-200:])
    else:
        for name in ("service migrate exited 0", "API connects as a DML-only database role (S12)"):
            smoke.record(name, None, "needs --compose-project")
    return finish(smoke, args)


def finish(smoke: Smoke, args) -> int:
    failed = [r for r in smoke.results if r["result"] == "fail"]
    skipped = [r for r in smoke.results if r["result"] == "skipped"]
    summary = {"baseUrl": args.base_url, "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "passed": sum(r["result"] == "pass" for r in smoke.results), "failed": len(failed),
               "skipped": len(skipped), "checks": smoke.results}
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2)
    print(json.dumps({k: v for k, v in summary.items() if k != "checks"}))
    return 1 if failed or (skipped and args.require_compose_checks) else 0


if __name__ == "__main__":
    sys.exit(main())
