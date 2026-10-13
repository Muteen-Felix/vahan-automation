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
        self.pulled = []
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)

            def docker(*command):
                if command[:3] == ('docker', 'context', 'inspect'):
                    return json.dumps([{'Endpoints': {'docker': {'Host': 'unix:///ci/isolated/docker.sock'}}}])
                if command[:2] == ('docker', 'run'):
                    self.assertIn('/ci/isolated/docker.sock:/var/run/docker.sock', command)
                if command[:2] == ('docker', 'pull'):
                    self.pulled.append(command[-1])
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
            self.assertEqual(self.pulled, [scanner.OFFICIAL_POSTGRES])
            self.assertRegex(summary['scanned']['postgres'], r'^docker\.io/library/postgres:.+@sha256:[0-9a-f]{64}$')
            return summary

    def test_active_ci_engine_is_scanned_and_unfixed_findings_are_retained(self):
        summary = self.exercise()
        self.assertTrue(all(item['critical'] == 1 and item['fixableHighCritical'] == 0
            for item in summary['images'].values()))

    def exercise_findings(self, image_ref, findings):
        """Run the scanner with an explicit Trivy result for the PostgreSQL image only."""
        with tempfile.TemporaryDirectory() as directory:
            def docker(*command):
                if command[:3] == ('docker', 'context', 'inspect'):
                    return json.dumps([{'Endpoints': {'docker': {'Host': 'unix:///ci/isolated/docker.sock'}}}])
                if command[:2] == ('docker', 'cp'):
                    path = Path(command[-1])
                    path.write_text(json.dumps({'Results': findings} if path.name.endswith('.vulnerabilities.json')
                        else {'bomFormat': 'CycloneDX', 'components': []}), encoding='utf-8')
                return ''
            with patch.object(scanner, 'IMAGES', [image_ref]), patch.object(scanner, 'run', side_effect=docker),                     patch.object(scanner.subprocess, 'run'), patch('sys.argv', ['scan', '--output-dir', directory]),                     contextlib.redirect_stdout(io.StringIO()):
                try:
                    scanner.main()
                    failed = False
                except SystemExit:
                    failed = True
            return failed, json.loads((Path(directory) / 'summary.json').read_text())

    def gosu_finding(self, **override):
        return {'Target': 'usr/local/bin/gosu', 'Type': 'gobinary', 'Vulnerabilities': [
            {'Severity': 'CRITICAL', 'VulnerabilityID': 'CVE-x', 'PkgName': 'stdlib', 'FixedVersion': '1.24.13',
             **override}]}

    def test_gosu_stdlib_exception_is_bound_to_the_pinned_digest(self):
        failed, summary = self.exercise_findings(scanner.OFFICIAL_POSTGRES, [self.gosu_finding()])
        self.assertFalse(failed)
        self.assertEqual(summary['images']['postgres'], {'high': 0, 'critical': 1,
                                                          'fixableHighCritical': 0, 'acceptedFixable': 1})
        self.assertIn('D-36', json.dumps(summary['exceptions']))
        other = scanner.OFFICIAL_POSTGRES.rsplit('@', 1)[0] + '@sha256:' + 'b' * 64
        failed, summary = self.exercise_findings(other, [self.gosu_finding()])
        self.assertTrue(failed)
        self.assertEqual(summary['images']['postgres']['fixableHighCritical'], 1)

    def test_other_fixable_findings_still_fail_with_the_exception_present(self):
        for finding in (self.gosu_finding(PkgName='golang.org/x/net'),
                        {**self.gosu_finding(), 'Target': 'usr/lib/postgresql/17/bin/postgres'},
                        {**self.gosu_finding(), 'Target': 'debian 12.12', 'Type': 'debian'}):
            failed, summary = self.exercise_findings(scanner.OFFICIAL_POSTGRES, [finding])
            self.assertTrue(failed, finding)
            self.assertEqual(summary['images']['postgres']['fixableHighCritical'], 1)

    def test_fixable_critical_failure_still_writes_all_image_reports(self):
        summary = self.exercise(fixable=True)
        self.assertEqual(summary['images']['postgres']['fixableHighCritical'], 1)


if __name__ == '__main__':
    unittest.main()
