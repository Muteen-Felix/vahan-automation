"""Compose, CI and the package/scan tooling must use the same official PostgreSQL pin (T21a, D-33)."""
import unittest
from pathlib import Path

import postgres_pin

ROOT = Path(__file__).resolve().parents[1]


class PostgresPinTests(unittest.TestCase):
    def test_compose_uses_official_digest_and_no_local_build(self):
        reference = postgres_pin.pinned_reference()
        self.assertTrue(reference.startswith('docker.io/library/postgres:17.'))
        self.assertRegex(postgres_pin.digest_of(reference), r'^sha256:[0-9a-f]{64}$')

    def test_ci_service_uses_the_same_reference(self):
        workflow = (ROOT / '.github/workflows/platform.yml').read_text(encoding='utf-8')
        references = set(postgres_pin.REFERENCE_PATTERN.findall(workflow))
        self.assertEqual(references, {postgres_pin.pinned_reference()})

    def test_self_built_image_is_gone(self):
        self.assertFalse((ROOT / 'docker/postgres.Dockerfile').exists())
        compose = (ROOT / 'compose.yaml').read_text(encoding='utf-8')
        self.assertNotIn('postgres.Dockerfile', compose)
        self.assertNotRegex(compose, r'/postgres:\$\{VAHAN_IMAGE_TAG')

    def test_pins_document_records_the_same_digest(self):
        pins = ROOT / 'docs/release/pins.md'
        self.assertTrue(pins.is_file(), 'docs/release/pins.md is required by T21a.')
        self.assertIn(postgres_pin.pinned_reference(), pins.read_text(encoding='utf-8'))

    def test_block_parser_rejects_build_and_mutable_tags(self):
        good = "services:\n  postgres:\n    image: docker.io/library/postgres:17.11-bookworm@sha256:" + "a" * 64 + "\n    environment: {}\n  api:\n    image: x\n"
        tmp = Path(self._testMethodName + '.yaml')
        try:
            tmp.write_text(good, encoding='utf-8')
            self.assertTrue(postgres_pin.pinned_reference(tmp).endswith('a' * 64))
            tmp.write_text(good.replace('@sha256:' + 'a' * 64, ''), encoding='utf-8')
            with self.assertRaises(ValueError):
                postgres_pin.pinned_reference(tmp)
            tmp.write_text(good.replace('    environment', '    build:\n      context: .\n    environment'), encoding='utf-8')
            with self.assertRaises(ValueError):
                postgres_pin.pinned_reference(tmp)
        finally:
            tmp.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
