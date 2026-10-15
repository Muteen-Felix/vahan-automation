"""Self-test for evidence-check.py and config-snapshot.py (PLAN T28/T28b, appendix B.2)."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH_MAP = json.loads((ROOT / "docs/release/path-map.json").read_text(encoding="utf-8"))
SNAP_SPEC = importlib.util.spec_from_file_location("config_snapshot", ROOT / "scripts/config-snapshot.py")
EVID_SPEC = importlib.util.spec_from_file_location("evidence_check", ROOT / "scripts/evidence-check.py")
snap = importlib.util.module_from_spec(SNAP_SPEC)
SNAP_SPEC.loader.exec_module(snap)
evid = importlib.util.module_from_spec(EVID_SPEC)
EVID_SPEC.loader.exec_module(evid)

CANARY = "CANARY-9f3a1c77-do-not-leak"
EVERY_ROW = sorted(PATH_MAP["rows"])
PIN = "docker.io/library/postgres:17.11-bookworm@sha256:" + "a" * 64


def compose(**environment):
    base = {"VAHAN_API_CORS_ORIGINS": "http://localhost:5173,http://127.0.0.1:5173", "VAHAN_ENVIRONMENT": "production",
            "DATABASE_URL": f"postgresql+asyncpg://vahan:{CANARY}@postgres:5432/vahan",
            "DB_APP_PASSWORD": CANARY, "VAHAN_API_RUNNER_TOKEN": CANARY,
            "VAHAN_URL": "https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en",
            "VAHAN_API_URL": "http://api:8000"}
    base.update(environment)
    return {"services": {
        "api": {"image": "vahan-automation/api:local", "environment": base, "ports": [
            {"host_ip": "127.0.0.1", "published": "8000", "target": 8000, "protocol": "tcp"}]},
        "runner": {"image": "vahan-automation/runner:local", "environment": {"VAHAN_URL": base["VAHAN_URL"]},
                   "deploy": {"replicas": 3}},
        "postgres": {"image": PIN, "environment": {"POSTGRES_PASSWORD": CANARY}},
    }}


def snapshot(project_dir, **environment):
    return snap.build_snapshot(compose(**environment), PATH_MAP, Path(project_dir))


class SnapshotAllowlist(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def text(self, **environment):
        return json.dumps(snapshot(self.dir.name, **environment))

    def test_secrets_and_unknown_keys_are_never_written(self):
        text = self.text(VAHAN_UPSTREAM_PASS=CANARY, INTERNAL_CREDENTIAL=CANARY,
                         DB_URI=f"postgresql://user:{CANARY}@db/x")
        self.assertNotIn(CANARY, text)
        values = json.loads(text)["values"]
        for key in ("api.VAHAN_UPSTREAM_PASS", "api.INTERNAL_CREDENTIAL", "api.DB_URI", "api.DATABASE_URL"):
            self.assertEqual(values[key], "<set>")

    def test_reviewed_plain_keys_are_written_verbatim(self):
        values = json.loads(self.text())["values"]
        self.assertEqual(values["api.VAHAN_ENVIRONMENT"], "production")
        self.assertEqual(values["runner.replicas"], "3")
        self.assertEqual(values["api.VAHAN_URL"], "https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en")

    def test_vahan_url_with_token_query_is_withheld(self):
        text = self.text(VAHAN_URL=f"https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en&token={CANARY}")
        self.assertNotIn(CANARY, text)
        self.assertEqual(json.loads(text)["values"]["api.VAHAN_URL"], "<set>")
        self.assertTrue(json.loads(text)["reviewErrors"])

    def test_urls_with_userinfo_query_or_fragment_are_withheld(self):
        for key, value in (("VAHAN_API_URL", f"http://api:8000/?key={CANARY}"),
                           ("VAHAN_API_URL", f"http://u:{CANARY}@api:8000"),
                           ("VAHAN_API_CORS_ORIGINS", f"http://u:{CANARY}@host:1"),
                           ("VAHAN_API_CORS_ORIGINS", f"http://host:1/path?x={CANARY}")):
            text = self.text(**{key: value})
            self.assertNotIn(CANARY, text, key)
            self.assertEqual(json.loads(text)["values"][f"api.{key}"], "<set>")

    def test_secret_scan_blocks_leaks_that_bypass_the_allowlist(self):
        self.assertTrue(snap.secret_findings(f'"x": "postgresql://vahan:{CANARY}@db/x"'))
        self.assertTrue(snap.secret_findings('password = hunter2hunter2'))
        self.assertFalse(snap.secret_findings(json.dumps(snapshot(self.dir.name))))

    def test_compose_override_stops_verification(self):
        project = Path(self.dir.name)
        (project / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
        (project / "compose.override.yaml").write_text("services: {}\n", encoding="utf-8")
        captured = project / "config.json"
        captured.write_text(json.dumps(compose()), encoding="utf-8")
        code = snap.main(["--project-dir", str(project), "--compose-json", str(captured),
                          "--out", str(project / "out.json")])
        self.assertEqual(code, 3)
        self.assertFalse((project / "out.json").exists())

    def test_cli_writes_a_snapshot_without_secrets(self):
        project = Path(self.dir.name)
        (project / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
        captured = project / "config.json"
        captured.write_text(json.dumps(compose()), encoding="utf-8")
        code = snap.main(["--project-dir", str(project), "--compose-json", str(captured), "--out", str(project / "out.json")])
        self.assertEqual(code, 0)
        self.assertNotIn(CANARY, (project / "out.json").read_text(encoding="utf-8"))


class SnapshotComparison(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def compare(self, before=None, after=None):
        old = snapshot(self.dir.name, **(before or {}))
        new = snapshot(self.dir.name, **(after or {}))
        return evid.compare_snapshots(old, new, PATH_MAP)

    def test_identical_snapshots_are_valid(self):
        self.assertEqual(self.compare(), {})

    def test_cors_origin_change_reopens_mapped_rows(self):
        found = self.compare(after={"VAHAN_API_CORS_ORIGINS": "https://example.org"})
        self.assertEqual(set(found), {"R1", "R2"})

    def test_secret_value_change_while_set_does_not_reopen(self):
        self.assertEqual(self.compare(after={"DB_APP_PASSWORD": "another-" + CANARY,
                                            "DATABASE_URL": "postgresql://vahan:other@postgres/vahan"}), {})

    def test_secret_unset_to_set_reopens(self):
        found = evid.compare_snapshots(
            {"values": {"api.DB_APP_PASSWORD": "<unset>"}}, {"values": {"api.DB_APP_PASSWORD": "<set>"}}, PATH_MAP)
        self.assertEqual(set(found), {"R1"})
        found = evid.compare_snapshots(
            {"values": {"api.DATABASE_URL": "<set>"}}, {"values": {"api.DATABASE_URL": "<unset>"}}, PATH_MAP)
        self.assertEqual(set(found), {"R1"})

    def test_unknown_key_reopens_every_row_fail_closed(self):
        found = self.compare(after={"BRAND_NEW_FLAG": "1"})
        self.assertEqual(sorted(found), EVERY_ROW)

    def test_replica_change_reopens_worker_rows(self):
        old = snapshot(self.dir.name)
        new = json.loads(json.dumps(old))
        new["values"]["runner.replicas"] = "5"
        self.assertEqual(set(evid.compare_snapshots(old, new, PATH_MAP)), {"R9", "R9b"})

    def test_plain_url_change_reopens_mapped_rows_and_unreviewed_url_reopens_all(self):
        found = self.compare(after={"VAHAN_API_URL": "http://other-api:8000"})
        self.assertEqual(set(found), {"R1", "R9b"})
        found = self.compare(after={"VAHAN_URL": f"https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en&token={CANARY}"})
        self.assertEqual(sorted(found), EVERY_ROW)

    def test_postgres_digest_change_reopens_all(self):
        old, new = snapshot(self.dir.name), snapshot(self.dir.name)
        new["images"]["postgres"] = PIN.replace("a" * 64, "b" * 64)
        self.assertEqual(sorted(evid.compare_snapshots(old, new, PATH_MAP)), EVERY_ROW)

    def test_added_compose_override_reopens_all(self):
        old, new = snapshot(self.dir.name), snapshot(self.dir.name)
        new["composeFiles"] = ["compose.override.yaml", "compose.yaml"]
        self.assertEqual(sorted(evid.compare_snapshots(old, new, PATH_MAP)), EVERY_ROW)

    def test_fingerprint_rules(self):
        base = {"base_image_digests": "sha256:1", "tesseract_version": "5.3", "chromium_version": "1"}
        self.assertEqual(sorted(evid.compare_fingerprints(base, {**base, "base_image_digests": "sha256:2"}, PATH_MAP)), EVERY_ROW)
        self.assertEqual(set(evid.compare_fingerprints(base, {**base, "tesseract_version": "5.4"}, PATH_MAP)), {"R14"})
        self.assertEqual(sorted(evid.compare_fingerprints(base, {**base, "new_unknown_input": "x"}, PATH_MAP)), EVERY_ROW)


def run_git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.org", *args],
                   check=True, capture_output=True, text=True)


class LedgerVerdicts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        run_git(self.repo, "init", "-q", "-b", "main")
        self.write("apps/api-server/app/repositories/annual_reports.py", "v1")
        self.write("apps/web-ui/src/components/RunHistory.tsx", "v1")
        self.write("docs/note.md", "v1")
        self.commit("base")
        self.base = self.head()
        self.write("docs/release/evidence/R5.md", f"- row: R5\n- sha: {self.base}\n")
        self.write("docs/release/evidence/R17.md", f"- row: R17\n- sha: {self.base}\n")
        self.commit("ledgers")

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message):
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-q", "-m", message)

    def head(self):
        return subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

    def verdicts(self, **extra):
        args = evid.argparse.Namespace(from_sha=None, to=self.head(), repo=str(self.repo), ledger_dir="docs/release/evidence",
                                      snapshot_from=None, snapshot_to=None, fingerprint_from=None, fingerprint_to=None,
                                      require_snapshot=False, allow_reopened=True, manifest=None, path_map=None)
        for key, value in extra.items():
            setattr(args, key, value)
        import contextlib, io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            evid.check_ledgers(args, PATH_MAP)
        return {Path(item["ledger"]).stem: item for item in json.loads(buffer.getvalue())["ledgers"]}

    def test_docs_only_change_is_valid(self):
        self.write("docs/note.md", "v2")
        self.commit("docs")
        self.assertTrue(all(v["verdict"] == "Valid" for v in self.verdicts().values()))

    def test_row_runtime_path_reopens_only_that_row(self):
        self.write("apps/api-server/app/repositories/annual_reports.py", "v2")
        self.commit("code")
        found = self.verdicts()
        self.assertEqual(found["R5"]["verdict"], "Reopened")
        self.assertEqual(found["R17"]["verdict"], "Valid")

    def test_global_path_reopens_every_row(self):
        self.write("compose.yaml", "services: {}\n")
        self.commit("compose")
        self.assertTrue(all(v["verdict"] == "Reopened" for v in self.verdicts().values()))

    def test_unmapped_runtime_file_is_fail_closed(self):
        self.write("apps/api-server/app/brand_new_module.py", "x")
        self.commit("new")
        self.assertTrue(all(v["verdict"] == "Reopened" for v in self.verdicts().values()))

    def test_workflow_change_is_valid_but_flagged(self):
        self.write(".github/workflows/platform.yml", "name: x\n")
        self.commit("ci")
        found = self.verdicts()["R5"]
        self.assertEqual(found["verdict"], "Valid")
        self.assertTrue(found["buildWorkflowChanged"])

    def test_non_ancestor_sha_is_reopened(self):
        run_git(self.repo, "checkout", "-q", "-b", "side", self.base)
        self.write("docs/side.md", "x")
        self.commit("side")
        side = self.head()
        run_git(self.repo, "checkout", "-q", "main")
        self.write("docs/release/evidence/R5.md", f"- row: R5\n- sha: {side}\n")
        self.commit("point at side")
        self.assertEqual(self.verdicts()["R5"]["verdict"], "Reopened")

    def test_version_only_change_follows_the_configured_rule(self):
        self.write("apps/web-ui/package.json", '{\n  "name": "x",\n  "version": "0.1.0"\n}\n')
        self.commit("pkg")
        self.write("docs/release/evidence/R17.md", f"- row: R17\n- sha: {self.head()}\n")
        self.commit("ledger")
        self.write("apps/web-ui/package.json", '{\n  "name": "x",\n  "version": "1.0.0"\n}\n')
        self.commit("bump")
        strict = self.verdicts()["R17"]
        self.assertEqual(strict["verdict"], "Reopened")
        lenient_map = dict(PATH_MAP, ignore_version_only_changes=True)
        original = evid.check_ledgers
        import contextlib, io
        args = evid.argparse.Namespace(from_sha=None, to=self.head(), repo=str(self.repo), ledger_dir="docs/release/evidence",
                                      snapshot_from=None, snapshot_to=None, fingerprint_from=None, fingerprint_to=None,
                                      require_snapshot=False, allow_reopened=True, manifest=None, path_map=None)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            original(args, lenient_map)
        found = {Path(i["ledger"]).stem: i for i in json.loads(buffer.getvalue())["ledgers"]}
        self.assertEqual(found["R17"]["verdict"], "Valid")


class ManifestChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.repo, self.release = root / "repo", root / "release"
        self.repo.mkdir()
        self.release.mkdir()
        run_git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "compose.yaml").write_text(f"services:\n  postgres:\n    image: {PIN}\n", encoding="utf-8")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-q", "-m", "F")
        self.sha = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        run_git(self.repo, "tag", "v1.0.0-rc.1")
        self.images = [{"ref": f"vahan/{n}:1.0.0", "id": f"sha256:{i}" * 1, "platform": "linux/amd64",
                        "label_revision": self.sha, "upstream": False} for i, n in enumerate(("api", "runner", "web"), 1)]
        self.images.append({"ref": PIN, "id": "sha256:" + "a" * 64, "digest": "sha256:" + "a" * 64,
                            "platform": "linux/amd64", "label_revision": None, "upstream": True})
        self.manifest = {"source_sha": self.sha, "tag": "v1.0.0-rc.1", "images": self.images, "custom_ca_files": [],
                         "lock_image_diff": [], "ledgers": []}
        (self.release / "images").mkdir()
        self.flush()

    def flush(self):
        (self.release / "release-manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        (self.release / "images" / "images.json").write_text(json.dumps(self.manifest["images"]), encoding="utf-8")
        import hashlib
        lines = [f"{hashlib.sha256((self.release / n).read_bytes()).hexdigest()}  {n}"
                 for n in ("release-manifest.json", "images/images.json")]
        (self.release / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def failures(self):
        import contextlib, io
        args = evid.argparse.Namespace(manifest=str(self.release), repo=str(self.repo))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = evid.check_manifest(args)
        report = json.loads(buffer.getvalue())
        return code, [c["check"] for c in report["checks"] if not c["ok"]]

    def test_consistent_manifest_passes(self):
        self.assertEqual(self.failures(), (0, []))

    def test_missing_image_fails(self):
        self.manifest["images"] = self.images[:3]
        self.flush()
        code, failed = self.failures()
        self.assertEqual(code, 1)
        self.assertTrue(any("exactly 4 images" in c for c in failed))

    def test_postgres_digest_not_matching_compose_fails(self):
        self.manifest["images"][3]["ref"] = PIN.replace("a" * 64, "c" * 64)
        self.flush()
        self.assertTrue(any("equals compose.yaml pin" in c for c in self.failures()[1]))

    def test_label_not_equal_to_f_fails(self):
        self.manifest["images"][0]["label_revision"] = "0" * 40
        self.flush()
        self.assertTrue(any("revision label" in c for c in self.failures()[1]))

    def test_custom_ca_and_tampered_checksum_fail(self):
        self.manifest["custom_ca_files"] = ["corp.crt"]
        self.flush()
        self.assertTrue(any("custom_ca_files" in c for c in self.failures()[1]))
        self.manifest["custom_ca_files"] = []
        self.flush()
        (self.release / "images" / "images.json").write_text("[]", encoding="utf-8")
        self.assertTrue(any("SHA256SUMS matches" in c for c in self.failures()[1]))

    def test_docs_commit_touching_code_fails(self):
        (self.repo / "app.py").write_text("x", encoding="utf-8")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-q", "-m", "D")
        self.manifest["docs_commit"] = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"],
                                                      capture_output=True, text=True).stdout.strip()
        self.flush()
        self.assertTrue(any("docs commit D" in c for c in self.failures()[1]))

    def test_clean_install_log_for_another_digest_fails(self):
        tar = self.release / "images.tar"
        tar.write_bytes(b"artifact-bytes")
        self.manifest["images_tar"] = "images.tar"
        (self.release / "evidence").mkdir()
        (self.release / "evidence" / "clean-install-000000000000.md").write_text("old digest", encoding="utf-8")
        self.flush()
        self.assertTrue(any("clean-install log" in c for c in self.failures()[1]))


if __name__ == "__main__":
    unittest.main()
