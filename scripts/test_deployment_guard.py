"""Release safety regressions using representative Compose and SQL outcomes."""
import json
import unittest
from unittest.mock import patch
import deployment_guard


class DeploymentGuardTest(unittest.TestCase):
    def evidence(self, **changes):
        return json.dumps({'activeJobs':0,'planningLeases':0,'runningQueues':0,'activeSchedules':0,
            'blockingDailySchedules':0,**changes})

    def test_new_install_without_containers_is_allowed(self):
        with patch('deployment_guard.capture', side_effect=['','']):
            self.assertEqual(deployment_guard.check_release(), {'freshInstall':True})

    def test_existing_stack_without_database_is_rejected(self):
        with patch('deployment_guard.capture', side_effect=['','api-container']):
            with self.assertRaisesRegex(RuntimeError,'no running PostgreSQL'):
                deployment_guard.check_release()

    def test_idle_and_paused_saved_work_is_allowed(self):
        with patch('deployment_guard.capture', side_effect=['postgres','t',self.evidence()]):
            self.assertEqual(deployment_guard.check_release()['activeJobs'],0)

    def test_each_kind_of_live_work_blocks_deployment(self):
        for field in ['activeJobs','planningLeases','runningQueues','activeSchedules','blockingDailySchedules']:
            with self.subTest(field=field), patch('deployment_guard.capture',side_effect=['postgres','t',self.evidence(**{field:1})]):
                with self.assertRaisesRegex(RuntimeError,'Deployment blocked'):
                    deployment_guard.check_release()

    def test_daily_schedule_that_still_owns_a_session_blocks_and_explains_why(self):
        with patch('deployment_guard.capture', side_effect=['postgres','t',self.evidence(blockingDailySchedules=2)]):
            with self.assertRaisesRegex(RuntimeError, r'blockingDailySchedules=2.*PAUSED.*0015'):
                deployment_guard.check_release()

    def test_evidence_without_the_daily_key_fails_closed(self):
        legacy = json.dumps({'activeJobs':0,'planningLeases':0,'runningQueues':0,'activeSchedules':0})
        with patch('deployment_guard.capture', side_effect=['postgres','t',legacy]):
            with self.assertRaisesRegex(RuntimeError, 'invalid database evidence'):
                deployment_guard.check_release()

    def test_daily_condition_does_not_depend_on_status(self):
        # A missing/NULL status makes `status IN (...)` NULL in SQL and would skip the row.
        self.assertNotIn('status', deployment_guard.DAILY_BLOCKING_SQL)
        self.assertIn("COALESCE(value->>'sessionId', '') <> ''", deployment_guard.DAILY_BLOCKING_SQL)
        self.assertIn(deployment_guard.DAILY_BLOCKING_SQL, deployment_guard.QUERY)

    def test_invalid_or_unavailable_sql_evidence_fails_closed(self):
        for result in ['invalid','{}',self.evidence(activeJobs='0')]:
            with self.subTest(result=result), patch('deployment_guard.capture',side_effect=['postgres','t',result]):
                with self.assertRaises(RuntimeError):deployment_guard.check_release()
        with patch('deployment_guard.capture',side_effect=RuntimeError('Database unavailable')):
            with self.assertRaises(RuntimeError):deployment_guard.check_release()
