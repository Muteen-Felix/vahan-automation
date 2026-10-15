"""test-review-package.py keeps the offline package result apart from the D3 live VAHAN preflight."""
import importlib.util
import sys
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


if __name__ == "__main__":
    unittest.main()
