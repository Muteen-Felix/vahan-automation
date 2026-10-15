"""Self-test for check-test-registration.py (PLAN T13, appendix B.1): it must catch each way a test can vanish."""
import importlib.util
import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "check-test-registration.py"
SPEC = importlib.util.spec_from_file_location("check_test_registration", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)

WORKFLOW = textwrap.dedent("""\
    name: fixture
    jobs:
      py:
        steps:
          - name: API tests
            working-directory: apps/api-server
            run: |
              python -m pytest verification/test_a.py
              VAHAN_FIXTURE_DB=x python -m pytest tests
              python -m unittest discover -s ../../scripts -p 'test_g.py'
              python - <<'PY'
              print("python scripts/test_ghost.py")
              PY
          - name: Runner tests
            working-directory: apps/browser-runner
            run: |
              npm run check
              npm run test:c
          - name: Web tests
            working-directory: apps/web-ui
            run: npm run test:platform
          - name: Direct script
            run: python tools/guard/test_t.py
    """)


class Fixture:
    def __init__(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.write("apps/api-server/verification/test_a.py", "def test_a():\n    pass\n")
        self.write("apps/api-server/tests/test_b.py", "def test_b():\n    pass\n")
        self.write("apps/browser-runner/test-c.mjs", "console.log('c');\n")
        self.write("apps/browser-runner/test-d.mjs", "console.log('d');\n")
        self.write("apps/browser-runner/package.json", json.dumps({"scripts": {
            "check": "node --check test-d.mjs", "test:c": "node test-c.mjs"}}))
        self.write("apps/web-ui/package.json", json.dumps({"scripts": {"test:platform": "node scripts/test-platform.mjs"}}))
        self.write("apps/web-ui/scripts/test-platform.mjs",
                   "const testFiles = [\n  'scripts/test-e.mjs',\n];\nawait runNode(['scripts/test-f.mjs'], env);\n")
        self.write("apps/web-ui/scripts/test-e.mjs", "console.log('e');\n")
        self.write("apps/web-ui/scripts/test-f.mjs", "console.log('f');\n")
        self.write("scripts/test_g.py", "def test_g():\n    pass\n")
        self.write("tools/guard/test_t.py", "def test_t():\n    pass\n")
        self.write(".github/workflows/platform.yml", WORKFLOW)
        self.entries = {
            "apps/api-server/verification/test_a.py": ("workflow-run", "cd apps/api-server && python -m pytest verification/test_a.py"),
            "apps/api-server/tests/test_b.py": ("workflow-run", "cd apps/api-server && python -m pytest tests"),
            "apps/browser-runner/test-c.mjs": ("npm-script", "npm run test:c"),
            "apps/web-ui/scripts/test-platform.mjs": ("npm-script", "npm run test:platform"),
            "apps/web-ui/scripts/test-e.mjs": ("test-platform", "npm run test:platform"),
            "apps/web-ui/scripts/test-f.mjs": ("test-platform", "npm run test:platform"),
            "scripts/test_g.py": ("workflow-run", "python -m unittest discover -s scripts -p test_g.py"),
            "tools/guard/test_t.py": ("script", "python tools/guard/test_t.py"),
        }
        self.manifest = {"version": 1, "tests": [
            {"path": path, "status": "ci", "via": via, "command": command} for path, (via, command) in self.entries.items()
        ] + [{"path": "apps/browser-runner/test-d.mjs", "status": "manual", "reason": "syntax-checked only", "owner": "Felix"}]}

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def entry(self, path):
        return next(e for e in self.manifest["tests"] if e["path"] == path)

    def run(self, **kwargs):
        return checker.check(self.root, self.manifest, self.root / ".github/workflows/platform.yml", **kwargs)

    def problems(self, **kwargs):
        return self.run(**kwargs)[0]

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                              capture_output=True, text=True, check=True)

    def cleanup(self):
        self.directory.cleanup()


class RegistrationChecks(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.cleanup)

    def assertProblem(self, code, problems):
        self.assertTrue(any(p.startswith(code) for p in problems), f"expected {code} in {problems}")

    def test_consistent_repository_passes(self):
        self.assertEqual(self.fx.problems(), [])

    def test_unregistered_test_file_fails(self):
        self.fx.write("apps/api-server/verification/test_new.py", "def test_new():\n    pass\n")
        self.assertProblem("UNREGISTERED:", self.fx.problems())

    def test_duplicate_entry_fails(self):
        self.fx.manifest["tests"].append(dict(self.fx.entry("scripts/test_g.py")))
        self.assertProblem("DUPLICATE:", self.fx.problems())

    def test_ci_entry_not_referenced_by_any_run_step_fails(self):
        self.fx.write(".github/workflows/platform.yml", WORKFLOW.replace("npm run test:c", "echo skipped"))
        self.assertProblem("NOT-REFERENCED:", self.fx.problems())

    def test_node_check_is_not_a_test_run(self):
        entry = self.fx.entry("apps/browser-runner/test-d.mjs")
        entry.update({"status": "ci", "via": "npm-script", "command": "npm run check"})
        self.assertProblem("NOT-REFERENCED:", self.fx.problems())

    def test_heredoc_text_is_not_a_command(self):
        self.fx.write("scripts/test_ghost.py", "def test_ghost():\n    pass\n")
        self.fx.manifest["tests"].append({"path": "scripts/test_ghost.py", "status": "ci", "via": "script", "command": "x"})
        self.assertProblem("NOT-REFERENCED:", self.fx.problems())

    def test_excused_status_needs_reason_owner_and_until(self):
        entry = self.fx.entry("apps/browser-runner/test-d.mjs")
        entry.pop("reason")
        entry.pop("owner")
        found = self.fx.problems()
        self.assertProblem("MISSING-REASON:", found)
        self.assertProblem("MISSING-OWNER:", found)
        entry.update({"status": "deferred", "reason": "r", "owner": "o"})
        self.assertProblem("MISSING-UNTIL:", self.fx.problems())

    def test_undeclared_skip_fails_and_declaring_it_passes(self):
        self.fx.write("apps/api-server/verification/test_a.py",
                      "import unittest\n\nclass T(unittest.TestCase):\n    @unittest.skip('later')\n    def test_later(self):\n        pass\n")
        self.assertProblem("UNDECLARED-SKIP:", self.fx.problems())
        self.fx.entry("apps/api-server/verification/test_a.py")["deferred_tests"] = ["test_later"]
        self.assertEqual(self.fx.problems(), [])

    def test_word_skipped_in_a_string_is_not_a_skip_marker(self):
        self.fx.write("apps/browser-runner/test-c.mjs", "assert.equal(env.confirm, 'skipped');\n")
        self.assertEqual(self.fx.problems(), [])

    def test_markers_inside_strings_and_comments_are_not_skips(self):
        self.fx.write("apps/api-server/verification/test_a.py",
                      "# @unittest.skip('commented out')\nFIXTURE = \"\"\"\n@unittest.skip('quoted')\nself.skipTest('quoted')\n\"\"\"\n"
                      "def test_a():\n    assert FIXTURE\n")
        self.fx.write("apps/browser-runner/test-c.mjs",
                      "// test.skip('commented out')\nconst text = \"it.skip('quoted')\";\nconsole.log(text);\n")
        self.assertEqual(self.fx.problems(), [])

    def test_real_javascript_skip_is_detected(self):
        self.fx.write("apps/browser-runner/test-c.mjs", "import test from 'node:test';\ntest.skip('later', () => {});\n")
        self.assertProblem("UNDECLARED-SKIP:", self.fx.problems())
    def test_stale_deferred_name_fails(self):
        self.fx.entry("scripts/test_g.py")["deferred_tests"] = ["test_does_not_exist"]
        self.assertProblem("STALE-DEFERRED:", self.fx.problems())

    def test_test_run_by_workflow_but_missing_from_manifest_fails(self):
        self.fx.manifest["tests"] = [e for e in self.fx.manifest["tests"] if e["path"] != "tools/guard/test_t.py"]
        found = self.fx.problems()
        self.assertProblem("UNREGISTERED:", found)
        self.fx.write("extras/test_z.py", "def test_z():\n    pass\n")
        self.fx.write(".github/workflows/platform.yml", WORKFLOW + "          - run: python extras/test_z.py\n")
        self.assertProblem("UNREGISTERED-IN-CI:", self.fx.problems())

    def test_wrong_via_and_unknown_env_fail(self):
        self.fx.entry("apps/browser-runner/test-c.mjs")["via"] = "script"
        self.assertProblem("WRONG-VIA:", self.fx.problems())
        self.fx.entry("apps/browser-runner/test-c.mjs")["via"] = "npm-script"
        self.fx.entry("apps/api-server/verification/test_a.py")["env"] = ["VAHAN_TYPO_DB"]
        self.assertProblem("UNKNOWN-ENV:", self.fx.problems())

    def test_manifest_entry_without_file_fails(self):
        self.fx.manifest["tests"].append({"path": "scripts/test_gone.py", "status": "manual", "reason": "r", "owner": "o"})
        self.assertProblem("MISSING-FILE:", self.fx.problems())


class RemovedEntries(unittest.TestCase):
    """The three `removed` failure modes of B.1 plus the silent delete, against a real temporary git history."""

    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.cleanup)
        self.fx.git("init", "-q")
        self.fx.git("add", "-A")
        self.fx.git("commit", "-q", "-m", "baseline")
        self.base = self.fx.git("rev-parse", "HEAD").stdout.strip()
        self.fx.manifest["baseline"] = self.base

    def delete_g(self):
        (self.fx.root / "scripts/test_g.py").unlink()
        self.fx.git("add", "-A")
        self.fx.git("commit", "-q", "-m", "delete g")
        without_g = "".join(line for line in WORKFLOW.splitlines(keepends=True) if "test_g.py" not in line)
        self.fx.write(".github/workflows/platform.yml", without_g)
        self.fx.manifest["tests"] = [e for e in self.fx.manifest["tests"] if e["path"] != "scripts/test_g.py"]

    def removed_entry(self, **extra):
        entry = {"path": "scripts/test_g.py", "status": "removed", "removed_in": "T18", "reason": "route retired",
                 "owner": "Felix", "equivalent_tests": ["test_b"]}
        entry.update(extra)
        self.fx.manifest["tests"].append(entry)

    def assertProblem(self, code, problems):
        self.assertTrue(any(p.startswith(code) for p in problems), f"expected {code} in {problems}")

    def test_history_is_checked_and_clean_when_nothing_was_deleted(self):
        problems, notes, _tests, _resolver = self.fx.run()
        self.assertEqual((problems, notes), ([], []))

    def test_deleted_test_without_removed_entry_fails(self):
        self.delete_g()
        self.assertProblem("SILENT-DELETE:", self.fx.problems())

    def test_properly_declared_removal_passes(self):
        self.delete_g()
        self.removed_entry()
        self.assertEqual(self.fx.problems(), [])

    def test_removed_entry_while_file_still_exists_fails(self):
        self.removed_entry()
        self.fx.manifest["tests"] = [e for e in self.fx.manifest["tests"]
                                     if not (e["path"] == "scripts/test_g.py" and e["status"] == "ci")]
        self.assertProblem("REMOVED-BUT-PRESENT:", self.fx.problems())

    def test_removed_entry_still_called_by_the_workflow_fails(self):
        self.delete_g()
        self.removed_entry()
        self.fx.write(".github/workflows/platform.yml", WORKFLOW)  # still calls test_g.py
        self.assertProblem("REMOVED-BUT-REFERENCED:", self.fx.problems())

    def test_removed_entry_still_listed_in_the_platform_runner_fails(self):
        self.delete_g()
        self.removed_entry()
        self.fx.write("apps/web-ui/scripts/test-platform.mjs",
                      "const testFiles = [\n  'scripts/test-e.mjs',\n  'scripts/test_g.py',\n];\nawait runNode(['scripts/test-f.mjs'], env);\n")
        self.assertProblem("REMOVED-BUT-REFERENCED:", self.fx.problems())
    def test_removal_claim_for_a_file_that_was_not_deleted_fails(self):
        self.removed_entry(path="scripts/test_never_existed.py")
        self.assertProblem("FALSE-REMOVED:", self.fx.problems())

    def test_removed_entry_needs_equivalent_tests_or_assessment(self):
        self.delete_g()
        self.removed_entry()
        self.fx.manifest["tests"][-1].pop("equivalent_tests")
        self.assertProblem("MISSING-EQUIVALENT:", self.fx.problems())
        self.fx.manifest["tests"][-1]["coverage_assessment"] = "route no longer shipped"
        self.assertEqual(self.fx.problems(), [])

    def test_removed_test_name_still_in_file_fails(self):
        self.fx.entry("scripts/test_g.py")["removed_tests"] = ["test_g"]
        self.assertProblem("REMOVED-TEST-PRESENT:", self.fx.problems())

    def test_unreachable_baseline_is_a_note_unless_history_is_required(self):
        self.fx.manifest["baseline"] = "0" * 40
        problems, notes, _tests, _resolver = self.fx.run()
        self.assertEqual(problems, [])
        self.assertTrue(any("NOT RUN" in n for n in notes))
        self.assertProblem("NO-HISTORY:", self.fx.problems(require_history=True))


class CommandLine(unittest.TestCase):
    def test_exit_codes(self):
        fx = Fixture()
        self.addCleanup(fx.cleanup)
        manifest = fx.root / "scripts/test-manifest.json"
        manifest.write_text(json.dumps(fx.manifest), encoding="utf-8")
        run = lambda *a: subprocess.run(["python", str(SCRIPT), "--repo", str(fx.root), *a],  # noqa: E731
                                        capture_output=True, text=True).returncode
        self.assertEqual(run(), 0)
        fx.write("scripts/test_extra.py", "def test_x():\n    pass\n")
        self.assertEqual(run(), 1)
        manifest.unlink()
        self.assertEqual(run(), 2)


if __name__ == "__main__":
    unittest.main()
