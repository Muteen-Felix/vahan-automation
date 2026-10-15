#!/usr/bin/env python3
"""Exercise the production API and Nginx security boundary from the host."""
from __future__ import annotations

import base64
import argparse
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' ws: wss:; "
    "frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'")


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def request(url: str, *, method: str = "GET", headers: dict[str, str] | None = None,
            body: bytes | None = None) -> tuple[int, dict[str, str], bytes]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers or {},
                method=method), timeout=20) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as response:
        return response.code, dict(response.headers.items()), response.read()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def header_value(headers: dict[str, str], name: str) -> str | None:
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-build", action="store_true",
        help="Use the already built security-test image tags.")
    args = parser.parse_args()
    api_port, web_port = free_port(), free_port()
    while web_port == api_port:
        web_port = free_port()
    # T29: the images must carry the checked-out commit as their declared revision. CI passes github.sha; a local
    # run may omit the variable (then HEAD is used), but a value that differs from HEAD is refused.
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    declared = os.environ.get("VAHAN_VCS_REF") or ("" if os.environ.get("GITHUB_ACTIONS") else head)
    require(declared == head, f"VAHAN_VCS_REF must be the checked-out commit {head}; got {declared!r}.")
    project = f"vahan-security-{secrets.token_hex(6)}"
    allowed_origin = f"http://localhost:{web_port}"
    password = secrets.token_urlsafe(36)
    values = {
        "POSTGRES_PASSWORD": secrets.token_urlsafe(36),
        "DB_APP_USERNAME": "vahan_app",
        "DB_APP_PASSWORD": secrets.token_urlsafe(36),
        "VAHAN_UI_AUTH_USERNAME": "security-check-admin",
        "VAHAN_UI_AUTH_PASSWORD": password,
        "VAHAN_UI_AUTH_TOKEN_SECRET": secrets.token_urlsafe(48),
        "VAHAN_API_RUNNER_TOKEN": secrets.token_urlsafe(36),
        "VAHAN_BROWSER_STATE_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "VAHAN_API_CORS_ORIGINS": allowed_origin,
        "VAHAN_API_SOCKETIO_CORS_ORIGINS": allowed_origin,
        "API_BIND_ADDRESS": "127.0.0.1",
        "API_PORT": str(api_port),
        "WEB_BIND_ADDRESS": "127.0.0.1",
        "WEB_PORT": str(web_port),
        "VAHAN_IMAGE_NAMESPACE": "vahan-security-test",
        "VAHAN_IMAGE_TAG": "round4",
        "VAHAN_VCS_REF": declared,
        "VAHAN_WORKER_REPLICAS": "1",
    }
    with tempfile.TemporaryDirectory(prefix="vahan-security-") as temporary:
        env_file = Path(temporary) / "compose.env"
        env_file.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
        compose = ["docker", "compose", "--env-file", str(env_file), "-p", project]

        def run(*args: str, timeout: int = 900, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
            result = subprocess.run([*compose, *args], cwd=ROOT, text=True, encoding="utf-8",
                errors="replace", timeout=timeout,
                capture_output=capture_output)
            if result.returncode:
                description = " ".join(args)
                for secret in values.values():
                    if secret:
                        description = description.replace(secret, "[redacted]")
                raise RuntimeError(f"docker compose {description} failed with exit code {result.returncode}.")
            return result

        try:
            if not args.no_build:
                run("build", "--sbom=true", "--provenance=mode=max", timeout=1800)
            for service in ("api", "runner", "web"):
                image = f"{values['VAHAN_IMAGE_NAMESPACE']}/{service}:{values['VAHAN_IMAGE_TAG']}"
                inspected = subprocess.run(["docker", "image", "inspect", "--format",
                    '{{ index .Config.Labels "org.opencontainers.image.revision" }}|'
                    '{{ index .Config.Labels "org.opencontainers.image.version" }}', image],
                    text=True, capture_output=True, timeout=60)
                require(inspected.returncode == 0, f"Could not inspect {image}.")
                revision, version = inspected.stdout.strip().split("|", 1)
                require(revision == declared, f"{image} revision label is {revision!r}, expected {declared}.")
                require(version == values["VAHAN_IMAGE_TAG"],
                        f"{image} version label is {version!r}, expected {values['VAHAN_IMAGE_TAG']}.")
            run("up", "-d", "--no-build", "--wait", "--wait-timeout", "300", "postgres", "api", "web")
            api_container = run("ps", "-q", "api", capture_output=True).stdout.strip()
            require(bool(api_container), "Could not find the isolated production API container.")
            lifecycle_script = ROOT / "scripts" / "test_runtime_role_lifecycle.py"
            copied = subprocess.run(["docker", "cp", str(lifecycle_script),
                    f"{api_container}:/tmp/test_runtime_role_lifecycle.py"],
                cwd=ROOT, text=True, capture_output=True, timeout=30)
            require(copied.returncode == 0,
                "Could not stage the fresh/upgrade DB-role integration test in the isolated API container.")
            owner_database_url = (f"postgresql+asyncpg://vahan:{values['POSTGRES_PASSWORD']}"
                "@postgres:5432/vahan")
            run("exec", "-T", "--env", f"DATABASE_URL={owner_database_url}",
                "--env", "API_SERVER_ROOT=/app", "api", "python",
                "/tmp/test_runtime_role_lifecycle.py", timeout=900)
            api = f"http://127.0.0.1:{api_port}"
            web = f"http://127.0.0.1:{web_port}"

            status, _, body = request(f"{api}/api/ready")
            require(status == 200 and json.loads(body)["status"] == "ok",
                "Production /api/ready did not pass from outside Docker.")
            status, _, body = request(f"{web}/api/ready")
            require(status == 200 and json.loads(body)["status"] == "ok",
                "Nginx did not proxy /api/ready from outside Docker.")

            for path in ("/docs", "/redoc", "/openapi.json"):
                status, _, _ = request(f"{api}{path}")
                require(status == 404, f"Production API reference {path} returned {status}, expected 404.")

            status, headers, _ = request(web)
            require(status == 200, f"Dashboard returned {status}.")
            for header, value in (("X-Content-Type-Options", "nosniff"),
                    ("X-Frame-Options", "DENY"), ("Referrer-Policy", "same-origin"),
                    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
                    ("Content-Security-Policy", EXPECTED_CSP)):
                require(header_value(headers, header) == value,
                    f"Dashboard security header {header} is missing or changed.")
            status, headers, _ = request(f"{web}/api/ready")
            require(header_value(headers, "X-Content-Type-Options") == "nosniff"
                and header_value(headers, "Content-Security-Policy") == EXPECTED_CSP,
                "Nginx security headers were not applied to proxied API responses.")

            for origin, is_allowed in ((allowed_origin, True), ("https://evil.example", False)):
                request_headers = {"Origin": origin, "Access-Control-Request-Method": "GET"}
                status, response_headers, _ = request(f"{web}/api/ready", method="OPTIONS", headers=request_headers)
                if is_allowed:
                    require(status == 200 and header_value(response_headers, "Access-Control-Allow-Origin") == origin,
                        f"Configured HTTP origin was not allowed (status={status}, "
                        f"access-control-allow-origin={header_value(response_headers, 'Access-Control-Allow-Origin')!r}).")
                else:
                    require(status == 400 and header_value(response_headers, "Access-Control-Allow-Origin") is None,
                        "Unlisted HTTP origin was not blocked.")
                socket_url = f"{web}/socket.io/?EIO=4&transport=polling&t={time.time_ns()}"
                status, _, _ = request(socket_url, headers={"Origin": origin})
                require(status == (200 if is_allowed else 400),
                    f"Socket.IO origin {origin} returned {status}.")

            statuses = []
            payload = json.dumps({"username": "invalid-security-test-user", "password": "invalid-password"}).encode()
            login_headers = {"Content-Type": "application/json"}
            for _ in range(30):
                status, _, _ = request(f"{web}/api/auth/login", method="POST",
                    headers=login_headers, body=payload)
                statuses.append(status)
                if status == 429:
                    break
            require(429 in statuses, "Nginx did not rate-limit repeated login attempts.")

            runtime_check = r'''import asyncio
from sqlalchemy import text
from app.db import engine
async def main():
    async with engine.connect() as connection:
        row = (await connection.execute(text("""SELECT current_user, r.rolsuper, r.rolcreatedb,
          r.rolcreaterole, r.rolreplication, r.rolbypassrls,
          has_schema_privilege(current_user,'public','CREATE') AS schema_create,
          has_table_privilege(current_user,'app_settings','UPDATE') AS settings_update,
          EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relowner=r.oid) AS owns_objects
          FROM pg_roles r WHERE r.rolname=current_user"""))).mappings().one()
        assert row['current_user'] == 'vahan_app'
        assert not any(row[key] for key in ('rolsuper','rolcreatedb','rolcreaterole','rolreplication',
            'rolbypassrls','schema_create','owns_objects'))
        assert row['settings_update']
        async with engine.connect() as ddl_connection:
            transaction = await ddl_connection.begin()
            try:
                await ddl_connection.execute(text('CREATE TABLE public.__runtime_role_must_not_create (id integer)'))
            except Exception:
                await transaction.rollback()
            else:
                await transaction.rollback()
                raise AssertionError('restricted API role unexpectedly created a table')
        async with engine.begin() as writable:
            await writable.execute(text("INSERT INTO app_settings(key,value) VALUES ('security-role-probe','{}')"))
            await writable.execute(text("DELETE FROM app_settings WHERE key='security-role-probe'"))
        print('Production API role is DML-only and does not own schema objects.')
    await engine.dispose()
asyncio.run(main())'''
            run("exec", "-T", "api", "python", "-c", runtime_check, timeout=60)

            # Exercise persisted UI Health with the built production API and its
            # restricted role, rather than allowing transport loss to hide drift.
            contract_check = r'''import asyncio
from app.db import engine
from app.repositories import ui_contract
from app.repositories.postgres import now
from app.services import services
async def main():
    runner='security-contract-probe'
    other='security-contract-other'
    await services.runners.register(runner_id=runner,name='Probe',socket_id=runner)
    controls=[{**seed,'found':True,'count':1,'name':seed['field'],'label':seed['field'],
        'matchedBy':'selector','inputType':'text' if seed['tag']=='input' else None,
        'optionsHash':'probe'} for seed in ui_contract.SEEDS]
    good={'status':'PASS','observedControls':controls,'checkedAt':now().isoformat()}
    broken={**good,'observedControls':[{**item,'found':False} if item['field']=='makers' else item for item in controls]}
    await ui_contract.evaluate(broken,runner)
    await services.runners.remove_by_socket(runner)
    await engine.dispose()
    disconnected=await ui_contract.current()
    assert disconnected['blocked'] and disconnected['lastError']
    await ui_contract.evaluate(good,other)
    assert (await ui_contract.current())['blocked']
    await services.runners.register(runner_id=runner,name='Probe',socket_id=runner)
    assert (await ui_contract.current())['blocked']
    await ui_contract.evaluate(good,runner)
    assert not (await ui_contract.current())['blocked']
    await services.runners.remove_by_socket(runner)
    await engine.dispose()
    print('Built API UI Health: disconnect and reconnect retain drift; only same-runner successful evidence clears it.')
asyncio.run(main())'''
            run("exec", "-T", "api", "python", "-c", contract_check, timeout=60)

            print("Container security checks passed: production startup/readiness, docs, HTTP and Socket.IO origin allowlists, headers/CSP, Nginx login throttling and restricted runtime DB role.")
        finally:
            run("down", "--volumes", "--remove-orphans", "--timeout", "15", timeout=120)


if __name__ == "__main__":
    main()
