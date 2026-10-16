"""test-review-package.py keeps the offline package result apart from the D3 live VAHAN preflight."""
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("review_install", SCRIPTS / "test-review-package.py")
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)

OK = [{"name": "image-load", "exitCode": 0}, {"name": "administrator-login", "passed": True}]


def d3(requested=False, preflight="NOT_RUN", live_case=False, single_case="NOT_RUN"):
    return {"requested": requested, "liveCaseRequested": live_case,
            "livePreflight": {"status": preflight}, "liveSingleCase": {"status": single_case}}


class ClassifyOutcomeTest(unittest.TestCase):
    def test_default_run_records_not_run_and_never_pass(self):
        outcome, status = review.classify_outcome(OK, None, d3())
        self.assertEqual((outcome, status), ("PACKAGE_PASS_D3_NOT_RUN", 0))
        self.assertEqual(review.d3_status(d3()), "NOT_RUN")
        self.assertNotIn("D3_PASS", outcome)

    def test_requested_preflight_pass(self):
        self.assertEqual(review.classify_outcome(OK, None, d3(True, "PASS")), ("PACKAGE_PASS_D3_PASS", 0))

    def test_requested_preflight_fail_keeps_fail_and_exit_two(self):
        self.assertEqual(review.d3_status(d3(True, "FAIL")), "FAIL")
        self.assertEqual(review.classify_outcome(OK, None, d3(True, "FAIL")), ("PACKAGE_PASS_D3_FAIL", 2))

    def test_requested_but_not_reached_is_not_a_pass(self):
        self.assertEqual(review.d3_status(d3(True, "NOT_RUN")), "FAIL")
        self.assertEqual(review.classify_outcome(OK, None, d3(True, "NOT_RUN")), ("PACKAGE_PASS_D3_FAIL", 2))

    def test_package_failure_wins_and_exits_one(self):
        for checks, error in (([*OK, {"name": "x", "passed": False}], None),
                              ([*OK, {"name": "y", "exitCode": 1}], None), (OK, "boom")):
            for state in (d3(), d3(True, "PASS"), d3(True, "FAIL")):
                self.assertEqual(review.classify_outcome(checks, error, state), ("PACKAGE_FAIL", 1))

    def test_live_case_must_pass_too(self):
        self.assertEqual(review.classify_outcome(OK, None, d3(True, "PASS", True, "PASS")),
                         ("PACKAGE_PASS_D3_PASS", 0))
        for single in ("FAIL", "NOT_RUN"):
            self.assertEqual(review.classify_outcome(OK, None, d3(True, "PASS", True, single)),
                             ("PACKAGE_PASS_D3_FAIL", 2))


class CommandLineTest(unittest.TestCase):
    def test_live_case_requires_explicit_preflight(self):
        argv = ["test-review-package.py", "--package-dir", "p", "--output-dir", "o", "--live-case"]
        with mock.patch.object(sys, "argv", argv), self.assertRaises(SystemExit) as stop:
            with mock.patch("sys.stderr"):
                review.main()
        self.assertEqual(stop.exception.code, 2)

    def test_source_has_no_unconditional_preflight_or_package_check_entry(self):
        source = (SCRIPTS / "test-review-package.py").read_text(encoding="utf-8")
        self.assertNotIn("'name':'live-vahan", source)
        self.assertLess(source.index("if args.vahan_preflight:"), source.index("/api/ui-health/preflight"))


class CleanDockerEngineTest(unittest.TestCase):
    def test_empty_engine_is_accepted_without_removing_anything(self):
        with mock.patch.object(review.subprocess, 'run') as run:
            run.return_value.stdout = ''
            self.assertEqual(review.require_clean_docker_engine(), {'images': 0, 'containers': 0, 'volumes': 0})
        self.assertEqual([c.args[0] for c in run.call_args_list], [
            ['docker', 'image', 'ls', '-aq'], ['docker', 'ps', '-aq'], ['docker', 'volume', 'ls', '-q']])

    def test_any_existing_image_container_or_volume_blocks(self):
        for index in range(3):
            results = [mock.Mock(stdout='') for _ in range(3)]
            results[index].stdout = 'existing-resource\n'
            with self.subTest(resource=index), mock.patch.object(review.subprocess, 'run', side_effect=results):
                with self.assertRaises(AssertionError) as stopped:
                    review.require_clean_docker_engine()
                self.assertIn('empty disposable Docker engine', str(stopped.exception))

    def test_clean_check_precedes_archive_load(self):
        source = (SCRIPTS / 'test-review-package.py').read_text(encoding='utf-8')
        self.assertLess(source.index('clean_engine = require_clean_docker_engine()'),
                        source.index("run(['docker','image','load'"))


BUILDER_SPEC = importlib.util.spec_from_file_location("build_package", SCRIPTS / "build-review-package.py")
builder = importlib.util.module_from_spec(BUILDER_SPEC)
BUILDER_SPEC.loader.exec_module(builder)
REPOSITORY = SCRIPTS.parent


class OfflineImageSaveTest(unittest.TestCase):
    PINNED = 'docker.io/library/postgres:17.11-bookworm@sha256:' + 'a' * 64

    def test_postgres_is_tagged_from_verified_digest_and_exported_by_tag(self):
        refs = ['vahan-review/api:1.0.0', self.PINNED, 'vahan-review/runner:1.0.0', 'vahan-review/web:1.0.0']
        original = list(refs)
        tag = self.PINNED.split('@', 1)[0]
        with mock.patch.object(builder.subprocess, 'run') as run:
            builder.save_offline_images(Path('images.tar'), refs, self.PINNED)
        self.assertEqual(run.call_args_list, [
            mock.call(['docker', 'image', 'tag', self.PINNED, tag], check=True),
            mock.call(['docker', 'image', 'save', '-o', 'images.tar', refs[0], tag, refs[2], refs[3]], check=True)])
        self.assertEqual(refs, original, 'Runtime/manifest digest references must stay unchanged')

    def test_invalid_or_unlisted_digest_is_refused_before_mutation(self):
        for refs, pinned in (([], self.PINNED), (['postgres:latest'], 'postgres:latest'),
                             (['postgres@sha256:' + 'a' * 64], 'postgres@sha256:' + 'a' * 64)):
            with self.subTest(pinned=pinned), mock.patch.object(builder.subprocess, 'run') as run:
                with self.assertRaises(SystemExit):
                    builder.save_offline_images(Path('images.tar'), refs, pinned)
                run.assert_not_called()

    def test_tag_failure_prevents_saving_archive(self):
        with mock.patch.object(builder.subprocess, 'run', side_effect=OSError('tag failed')) as run:
            with self.assertRaises(OSError):
                builder.save_offline_images(Path('images.tar'), [self.PINNED], self.PINNED)
        self.assertEqual(run.call_count, 1)


def version_files(**overrides):
    """Committed contents of the five version carriers, all at 1.0.0 unless overridden."""
    texts = {
        "apps/api-server/pyproject.toml": '[project]\nname = "x"\nversion = "1.0.0"\n',
        "apps/web-ui/package.json": json.dumps({"name": "web", "version": "1.0.0"}),
        "apps/web-ui/package-lock.json": json.dumps({"name": "web", "version": "1.0.0",
                                                     "packages": {"": {"name": "web", "version": "1.0.0"}}}),
        "apps/browser-runner/package.json": json.dumps({"name": "runner", "version": "1.0.0"}),
        "apps/browser-runner/package-lock.json": json.dumps({"name": "runner", "version": "1.0.0",
                                                             "packages": {"": {"name": "runner", "version": "1.0.0"}}}),
    }
    texts.update(overrides)
    return lambda sha, path: texts[path]


class ReleaseVersionTest(unittest.TestCase):
    def test_all_carriers_agree(self):
        with mock.patch.object(builder, "committed_text", version_files()):
            self.assertEqual(builder.release_version("f" * 40), "1.0.0")

    def test_one_stale_lock_entry_stops_the_build(self):
        stale = json.dumps({"name": "web", "version": "1.0.0", "packages": {"": {"name": "web", "version": "0.1.0"}}})
        with mock.patch.object(builder, "committed_text", version_files(**{"apps/web-ui/package-lock.json": stale})):
            with self.assertRaises(SystemExit) as stopped:
                builder.release_version("f" * 40)
        self.assertIn("disagree", str(stopped.exception))

    def test_non_release_versions_are_refused(self):
        everything = {
            "apps/api-server/pyproject.toml": '[project]\nversion = "1.0"\n',
            "apps/web-ui/package.json": json.dumps({"version": "1.0"}),
            "apps/web-ui/package-lock.json": json.dumps({"version": "1.0", "packages": {"": {"version": "1.0"}}}),
            "apps/browser-runner/package.json": json.dumps({"version": "1.0"}),
            "apps/browser-runner/package-lock.json": json.dumps({"version": "1.0", "packages": {"": {"version": "1.0"}}}),
        }
        with mock.patch.object(builder, "committed_text", lambda sha, path: everything[path]):
            with self.assertRaises(SystemExit):
                builder.release_version("f" * 40)

    def test_working_tree_versions_agree_and_changelog_names_the_release(self):
        found = set()
        for path, kind in builder.VERSION_FILES.items():
            text = (REPOSITORY / path).read_text(encoding="utf-8")
            found.update(builder.parse_versions(path, kind, text))
        self.assertEqual(len(found), 1, found)
        version = found.pop()
        changelog = (REPOSITORY / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertRegex(changelog, rf"(?m)^## \[{re.escape(version)}\]")


class PackageContentTest(unittest.TestCase):
    def test_changelog_ships_in_the_source_archive_and_is_required(self):
        self.assertIn("CHANGELOG.md", builder.PATHS)
        builder.check_source_members(["README.md", "CHANGELOG.md", "docs/release/INSTALL.md"])
        with self.assertRaises(SystemExit):
            builder.check_source_members(["README.md", "docs/release/INSTALL.md"])

    def test_secrets_and_operator_ca_material_are_refused(self):
        bad = [".docker.env", "apps/api-server/.env", "docker/certs/corp-root.crt", "a/.secrets/token",
               "docker/certs/proxy.PEM", "keys/server.key"]
        self.assertEqual(builder.forbidden_members(bad), bad)
        for name in bad:
            with self.subTest(name=name), self.assertRaises(SystemExit):
                builder.check_source_members(["CHANGELOG.md", name])

    def test_templates_and_certificate_readmes_are_allowed(self):
        fine = ["apps/api-server/.env.example", "apps/web-ui/.env.example", "docker/certs/README.md",
                "docker/certs/.gitkeep", "docs/release/config/config-template.env"]
        self.assertEqual(builder.forbidden_members(fine), [])

    def test_builder_source_checks_version_label_and_tag_and_names_files_by_short_sha(self):
        source = (SCRIPTS / "build-review-package.py").read_text(encoding="utf-8")
        self.assertIn("namespace, tag = 'vahan-review', version", source)
        self.assertRegex(source, r"require\(item\['versionLabel'\] == version")
        self.assertIn("f'vahan-{sha[:12]}-source.zip'", source)
        self.assertIn("'imageRevision': sha", source)


class ChecksumTest(unittest.TestCase):
    def package(self, root: Path):
        (root / "vahan-abc-source.zip").write_bytes(b"zip bytes")
        (root / "vahan-abc-images.tar").write_bytes(b"tar bytes")
        manifest = {"version": "1.0.0", "sourceCommit": "a" * 40,
                    "files": {"vahan-abc-source.zip": builder.digest(root / "vahan-abc-source.zip"),
                              "vahan-abc-images.tar": builder.digest(root / "vahan-abc-images.tar")}}
        (root / "vahan-abc-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        builder.write_sums(root, {**manifest["files"], "vahan-abc-manifest.json": builder.digest(root / "vahan-abc-manifest.json")})
        builder.verify_sums(root, complete=False)

    def test_sums_use_sha256sum_format_and_cover_the_three_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.package(root)
            lines = (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 3)
            for line in lines:
                self.assertRegex(line, r"^[0-9a-f]{64}  vahan-abc-(source\.zip|images\.tar|manifest\.json)$")

    def test_seal_covers_evidence_added_after_the_build_without_touching_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.package(root)
            before = {name: builder.digest(root / name) for name in ("vahan-abc-source.zip", "vahan-abc-images.tar")}
            (root / "evidence").mkdir()
            (root / "evidence" / "clean-install-0123456789ab.md").write_text("log", encoding="utf-8")
            with self.assertRaises(SystemExit):
                builder.verify_sums(root)  # evidence is not listed yet
            result = builder.seal(root)
            self.assertEqual(result["files"], 4)
            builder.verify_sums(root)
            listed = builder.read_sums(root / "SHA256SUMS")
            self.assertIn("evidence/clean-install-0123456789ab.md", listed)
            self.assertEqual({name: builder.digest(root / name) for name in before}, before)
            self.assertEqual(builder.seal(root)["files"], 4)  # idempotent

    def test_seal_refuses_a_changed_archive_or_manifest_or_missing_record(self):
        for victim in ("vahan-abc-source.zip", "vahan-abc-images.tar", "vahan-abc-manifest.json"):
            with self.subTest(victim=victim), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.package(root)
                (root / victim).write_bytes((root / victim).read_bytes() + b" ")
                with self.assertRaises(SystemExit):
                    builder.seal(root)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.package(root)
            kept = [line for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
                    if "manifest" not in line]
            (root / "SHA256SUMS").write_text("\n".join(kept) + "\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                builder.seal(root)

    def test_seal_cannot_be_combined_with_a_build(self):
        with mock.patch.object(sys, "argv", ["build-review-package.py", "--seal", ".", "--output-dir", "x"]):
            with self.assertRaises(SystemExit):
                builder.main()


if __name__ == "__main__":
    unittest.main()
