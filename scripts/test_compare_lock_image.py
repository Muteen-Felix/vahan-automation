"""Dependency mismatch detection and target-platform marker regressions (DEF-25)."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('compare_lock_image', Path(__file__).with_name('compare-lock-image.py'))
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class LockImageTest(unittest.TestCase):
    def test_image_platform_selects_markers_even_on_windows_host(self):
        text = 'thing==1.0 \\\n    --hash=sha256:abc\nwindows-only==2 ; sys_platform == "win32"\nlinux-only==3 ; sys_platform != "win32"\n'
        self.assertEqual(checker.python_lock(text, {'sys_platform': 'linux'}), {'thing': '1.0', 'linux-only': '3'})

    def test_name_normalization_and_version_missing_extra_mismatches(self):
        self.assertEqual(checker.python_lock('Some_Package==2', {}), {'some-package': '2'})
        diff = checker.package_diff({'changed': '1', 'missing': '2'}, {'changed': '3', 'extra': '4'})
        self.assertEqual({d['package'] for d in diff}, {'changed', 'missing', 'extra'})

    def test_unpinned_and_empty_locks_fail(self):
        for text in ('thing>=1', '# empty', 'thing==1.*'):
            with self.assertRaises(ValueError):
                checker.python_lock(text, {})

    def test_node_omits_dev_and_foreign_optional_but_checks_nested_packages(self):
        lock = {'packages': {'': {}, 'node_modules/a': {'version': '1'},
            'node_modules/a/node_modules/b': {'version': '2'},
            'node_modules/dev': {'version': '1', 'dev': True},
            'node_modules/mac': {'version': '1', 'optional': True, 'os': ['darwin']}}}
        self.assertEqual(checker.node_lock(lock, 'linux', 'x64'),
                         {'node_modules/a': '1', 'node_modules/a/node_modules/b': '2'})

    def test_node_incompatible_required_package_fails(self):
        with self.assertRaises(ValueError):
            checker.node_lock({'packages': {'node_modules/a': {'version': '1', 'os': ['!linux']}}}, 'linux', 'x64')


if __name__ == '__main__':
    unittest.main()
