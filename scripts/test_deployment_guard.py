"""Release safety regressions using representative Compose and SQL outcomes."""
import json
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, call, patch
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


class StoppedDatabaseTest(unittest.TestCase):
    def test_running_database_is_not_restarted(self):
        with patch('deployment_guard.capture', return_value='postgres') as capture:
            deployment_guard.start_stopped_database()
        capture.assert_called_once_with(['ps', '--status', 'running', '-q', 'postgres'])

    def test_missing_database_is_not_created(self):
        with patch('deployment_guard.capture', side_effect=['', '']) as capture:
            deployment_guard.start_stopped_database()
        self.assertEqual(capture.call_count, 2)

    def test_stopped_database_is_started_without_recreation_and_waits_for_readiness(self):
        with patch('deployment_guard.capture', side_effect=['', 'postgres', 'postgres', '']) as capture:
            deployment_guard.start_stopped_database()
        self.assertEqual(capture.call_args_list[-1],
            call(['start', '--wait', '--wait-timeout', '180', 'postgres'], timeout=190))

    def test_abnormal_database_state_is_rejected_without_starting(self):
        with patch('deployment_guard.capture', side_effect=['', 'postgres', '']) as capture:
            with self.assertRaisesRegex(RuntimeError, 'not stopped normally'):
                deployment_guard.start_stopped_database()
        self.assertEqual(capture.call_count, 3)

    def test_unavailable_database_does_not_skip_the_guard(self):
        with patch('deployment_guard.capture', side_effect=['', 'postgres', 'postgres', RuntimeError('start failed')]):
            with self.assertRaisesRegex(RuntimeError, 'start failed'):
                deployment_guard.start_stopped_database()

    def test_start_wait_has_a_longer_process_timeout_than_the_health_deadline(self):
        result = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        with patch('deployment_guard.subprocess.run', return_value=result) as run:
            deployment_guard.capture(['start', '--wait', '--wait-timeout', '180', 'postgres'], timeout=190)
        self.assertEqual(run.call_args.kwargs['timeout'], 190)


class LauncherRecoveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('release_launcher', Path(__file__).with_name('run-docker.py'))
        cls.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.launcher)

    def test_normal_start_checks_saved_work_after_database_recovery(self):
        launcher = self.launcher
        order = Mock()
        with patch.object(sys, 'argv', ['run-docker.py', '--no-build', '--workers', '1']), \
                patch.object(launcher, 'run') as run, \
                patch.object(launcher, 'start_stopped_database') as recover, \
                patch.object(launcher, 'check_release', return_value={'freshInstall': False}) as guard:
            order.attach_mock(run, 'run')
            order.attach_mock(recover, 'recover')
            order.attach_mock(guard, 'guard')
            self.assertEqual(launcher.main(), 0)
        calls = order.mock_calls
        self.assertLess(calls.index(call.recover()), calls.index(call.guard()))
        up = next(i for i, entry in enumerate(calls) if entry[0] == 'run' and 'up' in entry.args[0])
        self.assertEqual(sum(entry == call.guard() for entry in calls[:up]), 2)
        self.assertFalse(any('build' in entry.args[0] for entry in calls if entry[0] == 'run'))

    def test_read_only_release_check_does_not_start_any_service(self):
        launcher = self.launcher
        with patch.object(sys, 'argv', ['run-docker.py', '--check-release']), \
                patch.object(launcher, 'run') as run, \
                patch.object(launcher, 'start_stopped_database') as recover, \
                patch.object(launcher, 'check_release', return_value={'freshInstall': False}):
            self.assertEqual(launcher.main(), 0)
        recover.assert_not_called()
        self.assertFalse(any('start' in entry.args[0] or 'up' in entry.args[0] for entry in run.call_args_list))

    def test_config_only_does_not_recover_or_query_the_database(self):
        launcher = self.launcher
        with patch.object(sys, 'argv', ['run-docker.py', '--config-only']), \
                patch.object(launcher, 'run'), \
                patch.object(launcher, 'start_stopped_database') as recover, \
                patch.object(launcher, 'check_release') as guard:
            self.assertEqual(launcher.main(), 0)
        recover.assert_not_called()
        guard.assert_not_called()

    def test_saved_active_work_still_blocks_replacement_after_recovery(self):
        launcher = self.launcher
        with patch.object(sys, 'argv', ['run-docker.py', '--no-build', '--workers', '1']), \
                patch.object(launcher, 'run') as run, \
                patch.object(launcher, 'start_stopped_database') as recover, \
                patch.object(launcher, 'check_release', side_effect=RuntimeError('Deployment blocked: activeJobs=1')):
            with self.assertRaisesRegex(RuntimeError, 'Deployment blocked'):
                launcher.main()
        recover.assert_called_once_with()
        self.assertFalse(any('up' in entry.args[0] or 'build' in entry.args[0] for entry in run.call_args_list))
