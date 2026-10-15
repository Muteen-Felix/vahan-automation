"""Static checks that the three application images declare their revision and version (PLAN T29).

This only reads files. It proves the build is wired to pass the declared revision, not that an image was built from that
commit: the real label is asserted by scripts/test_container_security.py in the `container-build` CI job, and a label is a
declaration, not provenance (docs/release/pins.md).
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILES = {
    'api': 'apps/api-server/Dockerfile',
    'runner': 'apps/browser-runner/Dockerfile',
    'web': 'apps/web-ui/Dockerfile',
}


def read(relative):
    return (ROOT / relative).read_text(encoding='utf-8').replace('\r\n', '\n')


def final_stage(text):
    stages = re.split(r'^FROM\s', text, flags=re.MULTILINE)
    return stages[-1].split('\n')


class DockerfileLabels(unittest.TestCase):
    def test_final_stage_declares_arg_defaults_and_both_oci_labels(self):
        for service, path in DOCKERFILES.items():
            with self.subTest(image=service):
                lines = [line.strip() for line in final_stage(read(path))]
                self.assertIn('ARG VCS_REF=unknown', lines)
                self.assertIn('ARG VERSION=unknown', lines)
                labels = [line for line in lines if line.startswith('LABEL ')]
                self.assertEqual(len(labels), 1, labels)
                self.assertIn('org.opencontainers.image.revision=$VCS_REF', labels[0])
                self.assertIn('org.opencontainers.image.version=$VERSION', labels[0])

    def test_labels_come_after_the_heavy_layers_so_they_do_not_break_the_build_cache(self):
        for service, path in DOCKERFILES.items():
            with self.subTest(image=service):
                lines = [line.strip() for line in final_stage(read(path)) if line.strip()]
                heavy = [i for i, line in enumerate(lines) if re.match(r'(COPY|RUN|ADD)\s', line)]
                declared = [i for i, line in enumerate(lines) if line.startswith(('ARG VCS_REF', 'ARG VERSION'))]
                self.assertTrue(heavy and declared)
                self.assertGreater(min(declared), max(heavy))

    def test_postgres_is_the_upstream_image_and_is_not_labelled_by_us(self):
        self.assertFalse((ROOT / 'docker/postgres.Dockerfile').exists())
        compose = read('compose.yaml')
        postgres = re.search(r'^  postgres:\n(?P<body>(?:    .*\n|\n)+)', compose, re.MULTILINE)
        self.assertIsNotNone(postgres)
        self.assertNotIn('build:', postgres.group('body'))


class ComposeBuildArgs(unittest.TestCase):
    def service_block(self, name):
        match = re.search(rf'^  {name}:\n(?P<body>(?:    .*\n|\n)+)', read('compose.yaml'), re.MULTILINE)
        self.assertIsNotNone(match, name)
        return match.group('body')

    def test_application_services_pass_revision_and_version_with_unknown_defaults(self):
        for service in ('api', 'runner', 'web'):
            with self.subTest(service=service):
                body = self.service_block(service)
                self.assertIn('VCS_REF: ${VAHAN_VCS_REF:-unknown}', body)
                self.assertIn('VERSION: ${VAHAN_IMAGE_TAG:-unknown}', body)


class ReleaseAndCiPath(unittest.TestCase):
    def test_review_package_passes_the_sha_and_refuses_a_different_label(self):
        source = read('scripts/build-review-package.py')
        self.assertIn("'VAHAN_VCS_REF': sha", source)
        self.assertRegex(source, r"require\(item\['revisionLabel'\] == sha")

    def test_run_docker_declares_the_checked_out_commit_for_dev_builds(self):
        source = read('scripts/run-docker.py')
        self.assertIn('VAHAN_VCS_REF', source)
        self.assertIn('git', source)

    def test_ci_builds_through_the_script_that_asserts_the_label_with_the_commit_sha(self):
        workflow = read('.github/workflows/platform.yml')
        match = re.search(r'- name: Test production container security\n(?P<step>(?:        .*\n)+)', workflow)
        self.assertIsNotNone(match, 'container-build step is missing')
        step = match.group('step')
        self.assertIn('VAHAN_VCS_REF: ${{ github.sha }}', step)
        self.assertIn('python scripts/test_container_security.py', step)
        script = read('scripts/test_container_security.py')
        self.assertIn('org.opencontainers.image.revision', script)
        self.assertIn('git", "rev-parse", "HEAD"', script)
        self.assertIn('"VAHAN_VCS_REF": declared', script)


if __name__ == '__main__':
    unittest.main()
