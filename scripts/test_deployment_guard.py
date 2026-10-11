"""Release safety regressions using representative Compose and SQL outcomes."""
import json
import unittest
from unittest.mock import patch
import deployment_guard


class DeploymentGuardTest(unittest.TestCase):
    def evidence(self, **changes):
        return json.dumps({'activeJobs':0,'planningLeases':0,'runningQueues':0,'activeSchedules':0,**changes})

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
        for field in ['activeJobs','planningLeases','runningQueues','activeSchedules']:
            with self.subTest(field=field), patch('deployment_guard.capture',side_effect=['postgres','t',self.evidence(**{field:1})]):
                with self.assertRaisesRegex(RuntimeError,'Deployment blocked'):
                    deployment_guard.check_release()

    def test_invalid_or_unavailable_sql_evidence_fails_closed(self):
        for result in ['invalid','{}',self.evidence(activeJobs='0')]:
            with self.subTest(result=result), patch('deployment_guard.capture',side_effect=['postgres','t',result]):
                with self.assertRaises(RuntimeError):deployment_guard.check_release()
        with patch('deployment_guard.capture',side_effect=RuntimeError('Database unavailable')):
            with self.assertRaises(RuntimeError):deployment_guard.check_release()
