"""Operator-stop semantics without connecting to a live database or portal."""
import unittest
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import create_engine, select, text
from app.models.validation_stop import VALIDATION_STOP_CODES, requires_operator
from app.repositories.batch_queue import BatchQueueRepository, automatic_retry_condition, task_document
from app.db import schema as db


def row(position=0, status='FAILED', error='CAPTCHA_REFRESH_LIMIT: operator review required'):
    return dict(position=position, scenario_name='Fixture', status=status, attempts=1, failures=1,
                runner_id='playwright-1', job_id='fixture-job', error=error, session_id='fixture-session')


class ValidationStopTest(unittest.TestCase):
    def test_classification_does_not_disable_normal_transient_retries(self):
        for code in VALIDATION_STOP_CODES:
            self.assertTrue(requires_operator(code + ': stopped'))
        for value in [None, '', 123, 'VAHAN_RESULT_TIMEOUT: timed out', 'CAPTCHA_REFRESH_FAILED: transient',
                      'Other: CAPTCHA_REFRESH_LIMIT: text', 'CAPTCHAXREFRESHXLIMIT: unrelated']:
            self.assertFalse(requires_operator(value))

    def test_sql_filter_matches_operator_stop_codes_including_null_errors(self):
        engine = create_engine('sqlite://')
        try:
            with engine.begin() as connection:
                connection.execute(text('PRAGMA case_sensitive_like=ON'))
                connection.execute(text('CREATE TABLE batch_queue_tasks(position INTEGER, error TEXT)'))
                values = [code + ': stopped' for code in VALIDATION_STOP_CODES]
                values += [None, 'VAHAN_RESULT_TIMEOUT: transient', 'CAPTCHAXREFRESHXLIMIT: unrelated']
                connection.execute(text('INSERT INTO batch_queue_tasks(position,error) VALUES(:position,:error)'),
                                   [dict(position=i,error=value) for i,value in enumerate(values)])
                allowed = list(connection.scalars(select(db.batch_queue_tasks.c.position).where(automatic_retry_condition())))
            self.assertEqual(allowed, [3,4,5])
        finally:
            engine.dispose()

    def test_stopped_case_stays_visible_without_promising_recovery(self):
        result = task_document(row(), {'finalPassStarted':False})
        self.assertTrue(result['requiresOperator'])
        self.assertFalse(result['recoveryPending'])
        self.assertEqual(result['attempts'],1)
        self.assertIn('CAPTCHA_REFRESH_LIMIT',result['error'])


class ValidationStopPolicyTest(unittest.IsolatedAsyncioTestCase):
    async def test_settle_guard_failure_is_terminal_on_first_attempt(self):
        repository = BatchQueueRepository()
        connection = MagicMock()
        result = MagicMock()
        result.mappings.return_value.first.return_value = {'status':'FAILED','error':'CAPTCHA_WAIT_TIMEOUT: stopped'}
        connection.execute = AsyncMock(return_value=result)
        connection.scalar = AsyncMock(return_value={'phase':'PRIMARY','finalTargets':[]})
        settled = await repository._settle(connection, {**row(status='PROCESSING'), 'failures':0})
        self.assertEqual(settled['status'],'FAILED')
        self.assertEqual(settled['failures'],1)

    async def test_normal_failure_is_still_pending_for_checkpoint(self):
        repository = BatchQueueRepository()
        connection = MagicMock()
        result = MagicMock()
        result.mappings.return_value.first.return_value = {'status':'FAILED','error':'VAHAN_RESULT_TIMEOUT: transient'}
        connection.execute = AsyncMock(return_value=result)
        connection.scalar = AsyncMock(return_value={'phase':'PRIMARY','finalTargets':[]})
        settled = await repository._settle(connection, {**row(status='PROCESSING'), 'failures':0})
        self.assertEqual(settled['status'],'PENDING')
        self.assertEqual(settled['failures'],1)

    async def policy(self, rows, phase='PRIMARY', final_targets=None):
        repository = BatchQueueRepository()
        repository._policy = AsyncMock(return_value={
            'phase':phase,'windowStart':0,'windowEnd':len(rows),'lastCheckpoint':0,
            'finalPassStarted':phase=='FINAL','finalTargets':final_targets or [],
        })
        repository._save_policy = AsyncMock()
        connection = MagicMock(execute=AsyncMock())
        policy, result = await repository._advance_policy(connection,
            {'session_id':'fixture-session','status':'RUNNING','total':len(rows)},rows)
        return repository,policy,result

    async def test_final_sweep_keeps_operator_errors_but_reopens_transient_failures(self):
        repository,policy,rows = await self.policy([row(),row(1,error='VAHAN_RESULT_TIMEOUT: transient')])
        self.assertEqual(policy['phase'],'FINAL')
        self.assertEqual(policy['finalTargets'],[1])
        self.assertEqual([r['status'] for r in rows],['FAILED','PENDING'])
        self.assertEqual(repository._retry_progress(policy,rows)['failedRemaining'],2)

    async def test_all_stopped_cases_finish_without_an_automatic_retry(self):
        repository,policy,rows = await self.policy([row()])
        self.assertEqual(policy['phase'],'DONE')
        self.assertEqual(policy['finalTargets'],[])
        self.assertEqual(repository._retry_progress(policy,rows)['failedRemaining'],1)

    async def test_old_pending_final_target_is_fenced_on_restore(self):
        _,policy,rows = await self.policy([row(status='PENDING')],phase='FINAL',final_targets=[0])
        self.assertEqual(policy['phase'],'DONE')
        self.assertEqual(rows[0]['status'],'FAILED')
        self.assertEqual(rows[0]['attempts'],1)
        self.assertEqual(rows[0]['failures'],1)


if __name__ == '__main__':
    unittest.main()
