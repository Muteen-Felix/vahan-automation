"""Static check that the dashboard login stays rate limited in docker/nginx.conf (S3, T19a).

This only reads the file: it does not start nginx and says nothing about the limit being
enforced at runtime.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'docker/nginx.conf').read_text(encoding='utf-8')
LOGIN_BLOCK = re.search(r'location\s*=\s*/api/auth/login\s*\{(?P<body>[^{}]*)\}', CONFIG)


class NginxLoginRateLimitTests(unittest.TestCase):
    def test_login_has_its_own_exact_match_location(self):
        self.assertIsNotNone(LOGIN_BLOCK, 'Missing `location = /api/auth/login` block.')
        self.assertIn('proxy_pass', LOGIN_BLOCK.group('body'))

    def test_zone_is_keyed_by_client_address_at_ten_requests_per_minute(self):
        zones = re.findall(r'^limit_req_zone\s+(\S+)\s+zone=(\w+):(\d+m)\s+rate=(\d+)r/m\s*;', CONFIG, re.MULTILINE)
        self.assertEqual(len(zones), 1, zones)
        key, _name, _size, rate = zones[0]
        self.assertEqual(key, '$binary_remote_addr')
        self.assertEqual(rate, '10')

    def test_login_location_uses_that_zone_with_burst_ten_and_429(self):
        self.assertIsNotNone(LOGIN_BLOCK)
        body = LOGIN_BLOCK.group('body')
        zone = re.search(r'^limit_req_zone\s+\S+\s+zone=(\w+):', CONFIG, re.MULTILINE).group(1)
        self.assertRegex(body, rf'limit_req\s+zone={zone}\s+burst=10(\s+nodelay)?\s*;')
        self.assertRegex(body, r'limit_req_status\s+429\s*;')

    def test_login_limit_is_not_declared_for_the_generic_api_location_only(self):
        generic = re.search(r'location\s+/api/\s*\{(?P<body>[^{}]*)\}', CONFIG)
        self.assertIsNotNone(generic)
        self.assertNotIn('limit_req', generic.group('body'))


if __name__ == '__main__':
    unittest.main()
