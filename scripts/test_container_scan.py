"""Exercise scanner isolation and reporting without a live Docker daemon."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scan_container_images as scanner


class ContainerScanTests(unittest.TestCase):
    def exercise(self, *, fixable=False):
        self.scanned = []
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)

            def docker(*command):
                if command[:3] == ('docker', 'context', 'inspect'):
                    return json.dumps([{'Endpoints': {'docker': {'Host': 'unix:///ci/isolated/docker.sock'}}}])
                if command[:2] == ('docker', 'run'):
                    self.assertIn('/ci/isolated/docker.sock:/var/run/docker.sock', command)
                if command[:2] == ('docker', 'exec'):
                    self.scanned.append(command[-1])
                if command[:2] == ('docker', 'cp'):
                    path = Path(command[-1])
                    if path.name.endswith('.vulnerabilities.json'):
                        finding = {'Severity': 'CRITICAL', 'VulnerabilityID': 'fixture-unfixed'}
                        if fixable and path.name.startswith('postgres.'):
                            finding['FixedVersion'] = 'patched-fixture'
                        value = {'Results': [{'Vulnerabilities': [finding]}]}
                    else:
                        value = {'bomFormat': 'CycloneDX', 'components': []}
                    path.write_text(json.dumps(value), encoding='utf-8')
                return ''

            with patch.dict(os.environ, {'DOCKER_HOST': ''}), patch.object(scanner, 'run', side_effect=docker), \
                    patch.object(scanner.subprocess, 'run'), patch('sys.argv',
                        ['scan', '--output-dir', directory]), contextlib.redirect_stdout(io.StringIO()):
                if fixable:
                    with self.assertRaises(SystemExit):
                        scanner.main()
                else:
                    scanner.main()
            for name in ('postgres', 'api', 'web', 'runner'):
                self.assertTrue((output / f'{name}.cdx.json').is_file())
                self.assertTrue((output / f'{name}.vulnerabilities.json').is_file())
            summary = json.loads((output / 'summary.json').read_text())
            self.assertEqual(set(summary['images']), {'postgres', 'api', 'web', 'runner'})
            self.assertEqual(summary['errors'], [])
            self.assertEqual(set(self.scanned), set(scanner.IMAGES))
            return summary

    def test_active_ci_engine_is_scanned_and_unfixed_findings_are_retained(self):
        summary = self.exercise()
        self.assertTrue(all(item['critical'] == 1 and item['fixableHighCritical'] == 0
            for item in summary['images'].values()))

    def test_fixable_critical_failure_still_writes_all_image_reports(self):
        summary = self.exercise(fixable=True)
        self.assertEqual(summary['images']['postgres']['fixableHighCritical'], 1)


if __name__ == '__main__':
    unittest.main()
