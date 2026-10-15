"""release-smoke.py against a stub API: passes on a healthy stack, fails when a member is not blocked."""
import importlib.util
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("release_smoke", Path(__file__).with_name("release-smoke.py"))
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def make_handler(member_status):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body=None):
            raw = json.dumps(body).encode() if body is not None else b""
            self.send_response(status)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def read(self):
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self):
            token = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
            path = self.path.split("?")[0]
            if path == "/api/health":
                return self.reply(200, {"status": "ok"})
            if path == "/api/ready":
                return self.reply(200, {"status": "ok", "storage": "postgresql", "queue": "postgresql"})
            if path == "/":
                return self.reply(200, {})
            if path == "/api/runners":
                return self.reply(200, [{"id": "r1", "status": "ONLINE"}])
            if path in ("/api/annual-reports/run-history", "/api/users", "/api/audit"):
                return self.reply(200 if token == "admin-token" else member_status, [])
            self.reply(404, {})

        def do_POST(self):
            body = self.read()
            if self.path == "/api/auth/login":
                ok = body.get("password") == "pw-admin"
                return self.reply(200, {"accessToken": "admin-token" if body.get("username") == "admin" else "member-token"}) \
                    if ok or body.get("username") != "admin" else self.reply(401, {})
            if self.path == "/api/users":
                return self.reply(201, {})
            self.reply(404, {})

        def do_PATCH(self):
            self.read()
            self.reply(200, {})
    return Handler


class ReleaseSmokeTests(unittest.TestCase):
    def run_against(self, member_status):
        server = HTTPServer(("127.0.0.1", 0), make_handler(member_status))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        os.environ["VAHAN_SMOKE_ADMIN_PASSWORD"] = "pw-admin"
        self.addCleanup(os.environ.pop, "VAHAN_SMOKE_ADMIN_PASSWORD", None)
        return smoke.main(["--base-url", f"http://127.0.0.1:{server.server_address[1]}", "--runner-wait-seconds", "1"])

    def test_healthy_stack_passes_without_compose_checks(self):
        self.assertEqual(self.run_against(403), 0)

    def test_member_not_blocked_fails(self):
        self.assertEqual(self.run_against(200), 1)

    def test_require_compose_checks_fails_when_skipped(self):
        server = HTTPServer(("127.0.0.1", 0), make_handler(403))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        os.environ["VAHAN_SMOKE_ADMIN_PASSWORD"] = "pw-admin"
        self.addCleanup(os.environ.pop, "VAHAN_SMOKE_ADMIN_PASSWORD", None)
        code = smoke.main(["--base-url", f"http://127.0.0.1:{server.server_address[1]}", "--runner-wait-seconds", "1",
                           "--require-compose-checks"])
        self.assertEqual(code, 1)

    def test_password_is_required_from_the_environment(self):
        os.environ.pop("VAHAN_SMOKE_ADMIN_PASSWORD", None)
        self.assertEqual(smoke.main(["--base-url", "http://127.0.0.1:1"]), 2)


if __name__ == "__main__":
    unittest.main()
