"""PLAN_STATE_VAHAN WP-G: audited retire, gate generation, observation order, rollback; disposable DB only.

VAHAN_RESULT_TEST_DATABASE=vahan_results_<name>_test python -m pytest verification/test_gate_ops.py
"""
import asyncio
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from starlette.requests import Request

import test_report_results as fixture  # noqa: F401  (guards the database and runs migrations)
from app.api.ui_health import (GateReason, PreflightInput, admin_invalidate_gates, admin_retire_runner_error,
    preflight, receive_ui_health_log)
from app.db import engine, schema as db
from app.models.runner import Runner
from app.models.ui_health import UiHealthLogRequest
from app.repositories import ui_contract
from app.repositories.postgres import now, runner_document
from app.services import services

REASON = 'orphaned worker id after runner image replacement'


def observation(ok=True, check_id=None, seq=None, checked_at=None, **extra):
    controls = []
    for seed in ui_contract.SEEDS:
        controls.append({**seed, 'found': True, 'count': 1, 'tag': 'button' if seed['tag'] == 'action' else seed['tag'],
            'name': seed['field'], 'label': seed['field'], 'matchedBy': 'selector',
            'inputType': 'text' if seed['tag'] == 'input' else None, 'optionsHash': 'a'})
    if not ok:
        next(control for control in controls if control['field'] == 'makers')['found'] = False
    check = {'status': 'PASS', 'observedControls': controls, 'checkedAt': checked_at or now().isoformat(),
        'checkId': check_id or str(uuid4()), 'trigger': 'preflight', **extra}
    if seq is not None:
        check['checkSeq'] = seq
    return check


class GateOpsBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        self.owner = 'gate-' + str(uuid4())
        await services.users.bootstrap(self.owner, 'fixture-password-long')
        async with engine.begin() as c:
            await c.execute(delete(db.ui_preflight_checks))
            await c.execute(delete(db.ui_contract_versions))
            await c.execute(delete(db.app_settings).where(db.app_settings.c.key.in_(
                [ui_contract.ACTIVE_KEY, ui_contract.GENERATION_KEY])))
            await c.execute(delete(db.app_settings).where(db.app_settings.c.key.like('ui_gate:%')))
        self.runner_a = 'gate-a-' + str(uuid4())
        self.runner_b = 'gate-b-' + str(uuid4())
        for runner in (self.runner_a, self.runner_b):
            await services.runners.register(runner_id=runner, name='Fixture', socket_id=runner)

    async def asyncTearDown(self):
        await engine.dispose()

    # --- helpers -----------------------------------------------------------------------------
    async def record(self, runner, ok=True, **kwargs):
        """Evaluate an observation and store its health log the way the runner/API path does."""
        check = observation(ok=ok, **kwargs)
        validation = await ui_contract.evaluate(check, runner)
        check['contractValidation'] = validation
        await services.ui_health_logs.append(check)
        return validation

    async def make_offline(self, runner_id, silent_minutes=20, payload_edit=None):
        """Offline + silent, with a payload produced by the real runner_document()."""
        async with engine.begin() as c:
            payload = await c.scalar(select(db.runners.c.payload).where(db.runners.c.id == runner_id))
            runner = Runner.model_validate(payload)
            runner.last_seen_at = now() - timedelta(minutes=silent_minutes)
            document = runner_document(runner)
            if payload_edit:
                payload_edit(document)
            await c.execute(update(db.runners).where(db.runners.c.id == runner_id).values(
                connected=False, socket_id=None, payload=document))

    async def state(self):
        return await ui_contract.current()

    async def generation(self):
        return await ui_contract.gate_generation()

    async def audit_count(self, event):
        async with engine.connect() as c:
            return await c.scalar(select(func.count()).select_from(db.audit_events).where(db.audit_events.c.event == event))

    async def preflight_ids(self, ids, fail=()):
        request = Request({'type': 'http', 'headers': []})
        request.state.authenticated_user = self.owner
        seen = []

        async def checked(event, payload, **kwargs):
            runner = kwargs['to']
            seen.append({'runner': runner, **payload})
            check = observation(ok=runner not in fail, check_id=payload['requestId'], seq=payload.get('checkSeq'))
            check['contractValidation'] = await ui_contract.evaluate(check, runner)
            return await services.ui_health_logs.append(check)
        with patch('app.api.ui_health.sio.call', side_effect=checked), patch('app.api.ui_health.sio.emit', new=AsyncMock()):
            try:
                return await preflight(PreflightInput(runnerIds=ids), request), seen
            except HTTPException as error:
                return error, seen

    def admin_request(self, role='admin'):
        request = Request({'type': 'http', 'headers': []})
        request.state.authenticated_user = 'admin-user'
        request.state.authenticated_role = role
        return request

    async def pass_preflight(self, ids):
        result, _ = await self.preflight_ids(ids)
        self.assertNotIsInstance(result, HTTPException, getattr(result, 'detail', None))
        self.assertTrue(result['allowed'])
        return result['preflightId']

    async def orphan_scenario(self):
        """Runner A has a stored error, runner B has passed a newer check; A is gone."""
        await self.record(self.runner_a, ok=False)
        await self.record(self.runner_b, ok=True)
        await self.make_offline(self.runner_a)


class RetireAtomicityTests(GateOpsBase):
    async def test_valid_retire_changes_state_generation_and_audit_together(self):
        await self.orphan_scenario()
        self.assertTrue((await self.state())['blocked'])
        before = await self.audit_count('ui_health.runner_error_retired')
        result = await ui_contract.retire_runner_error('admin-user', self.runner_a, REASON)
        state = await self.state()
        self.assertFalse(state['blocked'])
        self.assertNotIn(self.runner_a, state['runnerErrors'])
        self.assertEqual((result['generationBefore'], result['generationAfter']), (0, 1))
        self.assertEqual(await self.generation(), 1)
        self.assertEqual(await self.audit_count('ui_health.runner_error_retired'), before + 1)
        async with engine.connect() as c:
            payload = await c.scalar(select(db.audit_events.c.payload).where(
                db.audit_events.c.event == 'ui_health.runner_error_retired').order_by(db.audit_events.c.created_at.desc()))
        self.assertEqual(payload['runnerId'], self.runner_a)
        self.assertEqual(payload['generationAfter'], 1)
        self.assertNotIn('password', str(payload).lower())

    async def test_fault_at_every_step_changes_nothing(self):
        for step in ('after_lock', 'after_checks', 'after_state', 'after_generation', 'after_supersede', 'after_audit'):
            with self.subTest(step=step):
                await self.asyncSetUp()
                await self.orphan_scenario()
                before_audit = await self.audit_count('ui_health.runner_error_retired')

                def boom(name, step=step):
                    if name == step:
                        raise RuntimeError('injected ' + step)
                with self.assertRaises(RuntimeError):
                    await ui_contract.retire_runner_error('admin-user', self.runner_a, REASON, fault=boom)
                state = await self.state()
                self.assertIn(self.runner_a, state['runnerErrors'], 'error must still be stored')
                self.assertTrue(state['blocked'])
                self.assertEqual(await self.generation(), 0)
                self.assertEqual(await self.audit_count('ui_health.runner_error_retired'), before_audit)

    async def test_failing_audit_write_means_no_retire(self):
        await self.orphan_scenario()
        with patch('app.repositories.ui_contract.audit_in', side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):
                await ui_contract.retire_runner_error('admin-user', self.runner_a, REASON)
        self.assertIn(self.runner_a, (await self.state())['runnerErrors'])
        self.assertEqual(await self.generation(), 0)

    async def test_concurrent_evaluate_keeps_other_runner_error(self):
        await self.orphan_scenario()
        other_error = observation(ok=False)
        results = await asyncio.gather(
            ui_contract.retire_runner_error('admin-user', self.runner_a, REASON),
            ui_contract.evaluate(other_error, self.runner_b), return_exceptions=True)
        self.assertFalse(any(isinstance(r, Exception) for r in results), results)
        state = await self.state()
        self.assertNotIn(self.runner_a, state['runnerErrors'])
        self.assertIn(self.runner_b, state['runnerErrors'])

    async def test_retire_preconditions_reject_without_side_effects(self):
        await self.record(self.runner_a, ok=False)
        before = await self.audit_count('ui_health.runner_error_retired')

        async def expect(code, runner=None, reason=REASON):
            with self.assertRaises(ui_contract.GateOpError) as error:
                await ui_contract.retire_runner_error('admin-user', runner or self.runner_a, reason)
            self.assertEqual(error.exception.code, code)
            self.assertEqual(await self.generation(), 0)
            self.assertEqual(await self.audit_count('ui_health.runner_error_retired'), before)
            self.assertIn(self.runner_a, (await self.state())['runnerErrors'])
        await expect('RUNNER_CONNECTED')                                  # A is still connected
        await self.make_offline(self.runner_a, silent_minutes=1)
        await expect('RUNNER_RECENTLY_SEEN')                              # offline, seen a minute ago
        await self.make_offline(self.runner_a, silent_minutes=20)
        await expect('NO_REPLACEMENT_PASS')                               # nobody passed after the error
        await self.record(self.runner_b, ok=True)
        await expect('REASON_REQUIRED', reason='short')
        with self.assertRaises(ui_contract.GateOpError) as missing:
            await ui_contract.retire_runner_error('admin-user', self.runner_b, REASON)
        self.assertEqual(missing.exception.code, 'NO_ERROR_FOR_RUNNER')

    async def test_retire_endpoint_is_admin_only_and_idempotent(self):
        await self.orphan_scenario()
        with patch('app.api.ui_health.sio.emit', new=AsyncMock()):
            with self.assertRaises(HTTPException) as denied:
                await admin_retire_runner_error(self.runner_a, GateReason(reason=REASON), self.admin_request('user'))
            self.assertEqual(denied.exception.status_code, 403)
            self.assertEqual(await self.generation(), 0)
            done = await admin_retire_runner_error(self.runner_a, GateReason(reason=REASON), self.admin_request())
            self.assertFalse(done['blocked'])
            with self.assertRaises(HTTPException) as again:
                await admin_retire_runner_error(self.runner_a, GateReason(reason=REASON), self.admin_request())
            self.assertEqual(again.exception.status_code, 404)
            self.assertEqual(again.exception.detail['code'], 'NO_ERROR_FOR_RUNNER')
            self.assertEqual(await self.generation(), 1)


class RunnerPayloadTests(GateOpsBase):
    """GA6: the silence condition reads the payload exactly as runner_document() writes it."""
    async def test_real_payload_key_is_snake_case(self):
        runner = Runner(id='x', name='n', socket_id='s')
        document = runner_document(runner)
        self.assertIn('last_seen_at', document)
        self.assertNotIn('lastSeenAt', document)

    async def test_offline_and_silent_runner_is_retired(self):
        await self.orphan_scenario()                       # payload rebuilt by runner_document()
        async with engine.connect() as c:
            payload = await c.scalar(select(db.runners.c.payload).where(db.runners.c.id == self.runner_a))
        self.assertIn('last_seen_at', payload)
        await ui_contract.retire_runner_error('admin-user', self.runner_a, REASON)
        self.assertNotIn(self.runner_a, (await self.state())['runnerErrors'])

    async def test_runner_that_just_heartbeated_is_rejected(self):
        await self.record(self.runner_a, ok=False)
        await self.record(self.runner_b, ok=True)
        self.assertIsNotNone(await services.runners.heartbeat(self.runner_a))
        await services.runners.remove_by_socket(self.runner_a)      # offline but just seen
        async with engine.connect() as c:
            row = (await c.execute(select(db.runners.c.connected).where(db.runners.c.id == self.runner_a))).scalar_one()
        self.assertFalse(row)
        with self.assertRaises(ui_contract.GateOpError) as error:
            await ui_contract.retire_runner_error('admin-user', self.runner_a, REASON)
        self.assertEqual(error.exception.code, 'RUNNER_RECENTLY_SEEN')
        self.assertEqual(await self.generation(), 0)

    async def test_legacy_alias_key_is_still_read(self):
        await self.record(self.runner_a, ok=False)
        await self.record(self.runner_b, ok=True)
        await self.make_offline(self.runner_a, 20, payload_edit=lambda d: d.update(lastSeenAt=d.pop('last_seen_at')))
        async with engine.connect() as c:
            payload = await c.scalar(select(db.runners.c.payload).where(db.runners.c.id == self.runner_a))
        self.assertIn('lastSeenAt', payload)
        self.assertNotIn('last_seen_at', payload)
        await ui_contract.retire_runner_error('admin-user', self.runner_a, REASON)
        self.assertNotIn(self.runner_a, (await self.state())['runnerErrors'])

    async def test_unparseable_last_seen_is_refused(self):
        await self.record(self.runner_a, ok=False)
        await self.record(self.runner_b, ok=True)
        await self.make_offline(self.runner_a, 20)
        async with engine.begin() as c:                   # corrupt the stored document directly
            payload = await c.scalar(select(db.runners.c.payload).where(db.runners.c.id == self.runner_a))
            await c.execute(update(db.runners).where(db.runners.c.id == self.runner_a).values(
                payload={**payload, 'last_seen_at': 'not-a-date'}))
        with self.assertRaises(ui_contract.GateOpError) as error:
            await ui_contract.retire_runner_error('admin-user', self.runner_a, REASON)
        self.assertEqual(error.exception.code, 'RUNNER_STATE_UNREADABLE')
        self.assertEqual(await self.generation(), 0)

    async def test_missing_last_seen_is_treated_as_recently_seen_and_refused(self):
        await self.record(self.runner_a, ok=False)
        await self.record(self.runner_b, ok=True)
        await self.make_offline(self.runner_a, 20)
        async with engine.begin() as c:
            payload = await c.scalar(select(db.runners.c.payload).where(db.runners.c.id == self.runner_a))
            payload.pop('last_seen_at')
            await c.execute(update(db.runners).where(db.runners.c.id == self.runner_a).values(payload=payload))
        with self.assertRaises(ui_contract.GateOpError) as missing:
            await ui_contract.retire_runner_error('admin-user', self.runner_a, REASON)
        self.assertEqual(missing.exception.code, 'RUNNER_RECENTLY_SEEN')
        self.assertEqual(await self.generation(), 0)


class GateGenerationTests(GateOpsBase):
    async def test_old_pass_does_not_survive_retire_even_after_reconnect(self):
        """T5 / GB1: PASS made before the error, a late CHECK_ERROR log (no BLOCKED preflight), retire."""
        pass_id = await self.pass_preflight([self.runner_a])
        session = uuid4()
        await ui_contract.bind_gate(session, pass_id)
        self.assertEqual(await ui_contract.require_gate(self.owner, [self.runner_a], pass_id, fresh=True), pass_id)
        await self.record(self.runner_a, ok=False)                 # late log: sets runnerErrors, no BLOCKED row
        await self.record(self.runner_b, ok=True)
        await self.make_offline(self.runner_a)
        with self.assertRaises(ValueError) as blocked:
            await ui_contract.require_gate(self.owner, [self.runner_a], fresh=True)
        self.assertTrue(str(blocked.exception).startswith('UI_HEALTH_BLOCKED'))
        await ui_contract.retire_runner_error('admin-user', self.runner_a, REASON)
        self.assertFalse((await self.state())['blocked'])

        async def all_forms_rejected():
            forms = [lambda: ui_contract.require_gate(self.owner, [self.runner_a], fresh=True),
                lambda: ui_contract.require_gate(self.owner, [self.runner_a], pass_id, fresh=True),
                lambda: ui_contract.require_gate(self.owner, [self.runner_a], session_id=str(session), bound=True),
                lambda: ui_contract.require_gate(self.owner, [self.runner_a])]
            for form in forms:
                with self.assertRaises(ValueError) as error:
                    await form()
                self.assertTrue(str(error.exception).startswith('UI_PREFLIGHT_REQUIRED'), str(error.exception))
        await all_forms_rejected()
        await services.runners.register(runner_id=self.runner_a, name='Reconnected', socket_id=self.runner_a)
        await all_forms_rejected()
        async with engine.connect() as c:
            retired_at = await c.scalar(select(db.audit_events.c.created_at).where(
                db.audit_events.c.event == 'ui_health.runner_error_retired').order_by(db.audit_events.c.created_at.desc()))
        new_id = await self.pass_preflight([self.runner_a])
        self.assertNotEqual(new_id, pass_id)
        self.assertEqual(await ui_contract.require_gate(self.owner, [self.runner_a], fresh=True), new_id)
        async with engine.connect() as c:
            row = (await c.execute(select(db.ui_preflight_checks).where(db.ui_preflight_checks.c.id == new_id))).mappings().one()
        self.assertEqual(row['gate_generation'], 1)
        self.assertGreater(row['created_at'], retired_at)

    async def test_generation_alone_rejects_a_pass_row_even_if_its_status_is_restored(self):
        """GB3: the status flip is a belt; the generation is the authority."""
        pass_id = await self.pass_preflight([self.runner_a])
        await ui_contract.invalidate_gates('admin-user', REASON)
        async with engine.begin() as c:
            await c.execute(update(db.ui_preflight_checks).where(db.ui_preflight_checks.c.id == pass_id).values(status='PASS'))
        with self.assertRaises(ValueError) as error:
            await ui_contract.require_gate(self.owner, [self.runner_a], pass_id, fresh=True)
        self.assertTrue(str(error.exception).startswith('UI_PREFLIGHT_REQUIRED'))

    async def test_preflight_started_before_a_reset_is_not_reported_allowed(self):
        """GB2: the gate is invalidated while workers are being checked."""
        request = Request({'type': 'http', 'headers': []})
        request.state.authenticated_user = self.owner

        async def checked(event, payload, **kwargs):
            await ui_contract.invalidate_gates('admin-user', REASON)
            check = observation(check_id=payload['requestId'], seq=payload.get('checkSeq'))
            check['contractValidation'] = await ui_contract.evaluate(check, kwargs['to'])
            return await services.ui_health_logs.append(check)
        with patch('app.api.ui_health.sio.call', side_effect=checked), patch('app.api.ui_health.sio.emit', new=AsyncMock()):
            with self.assertRaises(HTTPException) as error:
                await preflight(PreflightInput(runnerIds=[self.runner_a]), request)
        self.assertEqual(error.exception.detail['code'], 'PREFLIGHT_WAITING')
        async with engine.connect() as c:
            row = (await c.execute(select(db.ui_preflight_checks).where(
                db.ui_preflight_checks.c.id == error.exception.detail['diagnostics']['preflightId']))).mappings().one()
        self.assertEqual(row['status'], 'WAITING')
        with self.assertRaises(ValueError):
            await ui_contract.require_gate(self.owner, [self.runner_a], fresh=True)

    async def test_invalidate_voids_gates_audits_and_keeps_runner_errors(self):
        pass_id = await self.pass_preflight([self.runner_a])
        await self.record(self.runner_b, ok=False)
        before = await self.audit_count('ui_health.gates_invalidated')
        with patch('app.api.ui_health.sio.emit', new=AsyncMock()):
            with self.assertRaises(HTTPException) as short:
                await admin_invalidate_gates(GateReason(reason='short'), self.admin_request())
            self.assertEqual(short.exception.status_code, 400)
            result = await admin_invalidate_gates(GateReason(reason=REASON), self.admin_request())
        self.assertEqual(result['generationAfter'], 1)
        self.assertEqual(await self.audit_count('ui_health.gates_invalidated'), before + 1)
        self.assertIn(self.runner_b, (await self.state())['runnerErrors'])
        async with engine.connect() as c:
            status = await c.scalar(select(db.ui_preflight_checks.c.status).where(db.ui_preflight_checks.c.id == pass_id))
        self.assertEqual(status, 'SUPERSEDED')


class ObservationOrderTests(GateOpsBase):
    """I15: order comes from the server-issued checkSeq; checkedAt never decides."""
    async def test_late_pass_cannot_clear_a_newer_error(self):                       # GC1
        await ui_contract.evaluate(observation(ok=False, seq=11, check_id='c11'), self.runner_a)
        late = await ui_contract.evaluate(observation(ok=True, seq=10, check_id='c10'), self.runner_a)
        self.assertEqual(late['status'], 'STALE_OBSERVATION')
        self.assertTrue(late['ignored'])
        state = await self.state()
        self.assertTrue(state['blocked'])
        self.assertEqual(state['runnerErrors'][self.runner_a]['checkId'], 'c11')

    async def test_clock_going_backwards_does_not_change_the_decision(self):         # GC2
        await ui_contract.evaluate(observation(ok=False, seq=11, check_id='c11', checked_at='2026-10-14T10:00:00+00:00'), self.runner_a)
        newer = await ui_contract.evaluate(observation(ok=True, seq=12, check_id='c12', checked_at='2026-10-14T09:00:00+00:00'), self.runner_a)
        self.assertTrue(newer['allowed'])
        self.assertFalse((await self.state())['blocked'])
        old = await ui_contract.evaluate(observation(ok=False, seq=5, check_id='c5', checked_at='2026-10-14T23:00:00+00:00'), self.runner_a)
        self.assertEqual(old['status'], 'STALE_OBSERVATION')
        self.assertFalse((await self.state())['blocked'], 'an older error with a later timestamp is stale')

    async def test_duplicate_and_equal_sequence_rules(self):                          # GC3
        first = await ui_contract.evaluate(observation(ok=False, seq=20, check_id='dup'), self.runner_a)
        again = await ui_contract.evaluate(observation(ok=False, seq=20, check_id='dup'), self.runner_a)
        self.assertEqual((first['allowed'], again['allowed']), (False, False))
        self.assertEqual(again['order'], 'idempotent')
        self.assertFalse(again['ignored'])
        # same sequence, different check: a PASS must not clear the error, an error is still applied
        anomalous = await ui_contract.evaluate(observation(ok=True, seq=20, check_id='other'), self.runner_a)
        self.assertEqual(anomalous['status'], 'STALE_OBSERVATION')
        self.assertTrue((await self.state())['blocked'])
        self.assertEqual(anomalous['order'], 'anomaly')
        applied = await ui_contract.evaluate(observation(ok=False, seq=20, check_id='other-error'), self.runner_b)
        self.assertFalse(applied['allowed'])

    async def test_observation_without_check_seq_keeps_arrival_order_behaviour(self):  # GC4 (OPEN-5)
        await ui_contract.evaluate(observation(ok=False, check_id='legacy-1'), self.runner_a)
        await ui_contract.evaluate(observation(ok=True, check_id='legacy-2'), self.runner_a)
        self.assertFalse((await self.state())['blocked'])
        await ui_contract.evaluate(observation(ok=False, seq=3, check_id='c3'), self.runner_a)
        await ui_contract.evaluate(observation(ok=True, check_id='legacy-3'), self.runner_a)   # no seq: applied
        self.assertFalse((await self.state())['blocked'])
        state = await self.state()
        self.assertEqual(state['runnerLastSeq'][self.runner_a], 3, 'order bookkeeping survives a rewrite')

    async def test_preflight_issues_increasing_sequence_numbers(self):               # GC5
        first = await ui_contract.next_check_seq()
        second = await ui_contract.next_check_seq()
        self.assertGreater(second, first)
        _, seen = await self.preflight_ids([self.runner_a])
        _, seen_again = await self.preflight_ids([self.runner_a])
        self.assertIsInstance(seen[0]['checkSeq'], int)
        self.assertGreater(seen_again[0]['checkSeq'], seen[0]['checkSeq'])


class RolloutAndRollbackTests(GateOpsBase):
    async def test_orphan_blocks_http_but_runner_observations_are_allowed(self):     # GX3 / rollout step 5
        await self.record(self.runner_a, ok=False)
        await self.make_offline(self.runner_a)
        result, _ = await self.preflight_ids([self.runner_b])
        self.assertIsInstance(result, HTTPException)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.detail['code'], 'UI_HEALTH_BLOCKED')
        self.assertFalse(result.detail['diagnostics']['allowed'])
        self.assertTrue(result.detail['diagnostics']['reports'][0]['allowed'])

    async def test_old_id_offline_keeps_gate_blocked_after_new_id_passes(self):      # GX4 (why retire exists)
        await self.record(self.runner_a, ok=False)
        await self.make_offline(self.runner_a)
        await self.record(self.runner_b, ok=True)
        state = await self.state()
        self.assertTrue(state['blocked'])
        self.assertEqual(state['blockedRunnerIds'], [self.runner_a])

    async def test_rollback_sequence_requires_fresh_preflight_after_retire(self):    # GR1a, GR1b, GR2
        r1, r2 = self.runner_a, self.runner_b
        r3, r4 = 'gate-c-' + str(uuid4()), 'gate-d-' + str(uuid4())
        pass_id = await self.pass_preflight([r1, r2])
        session = uuid4()
        await ui_contract.bind_gate(session, pass_id)
        # RB3: invalidate before replacing runners
        await ui_contract.invalidate_gates('admin-user', REASON)
        for form in (lambda: ui_contract.require_gate(self.owner, [r1], fresh=True),
                lambda: ui_contract.require_gate(self.owner, [r1], session_id=str(session), bound=True)):
            with self.assertRaises(ValueError):
                await form()
        # RB4: image rollback creates new ids; the old ones go away
        for runner in (r3, r4):
            await services.runners.register(runner_id=runner, name='Rollback', socket_id=runner)
        with self.assertRaises(ValueError) as nothing:
            await ui_contract.require_gate(self.owner, [r3], fresh=True)
        self.assertTrue(str(nothing.exception).startswith('UI_PREFLIGHT_REQUIRED'))
        # RB5: preflight the pool of the rolled-back image
        rb5 = await self.pass_preflight([r3, r4])
        self.assertEqual(await ui_contract.require_gate(self.owner, [r3], fresh=True), rb5)
        # an error of a gone runner appears late (no BLOCKED row) and is retired (RB6)
        await self.record(r1, ok=False)
        await self.record(r3, ok=True)                  # an online worker passes a newer check
        await self.make_offline(r1)
        await self.make_offline(r2)
        before = await self.audit_count('ui_health.runner_error_retired')
        await ui_contract.retire_runner_error('admin-user', r1, REASON)
        self.assertEqual(await self.audit_count('ui_health.runner_error_retired'), before + 1)
        self.assertEqual(await self.audit_count('ui_health.gates_invalidated') >= 1, True)
        # the RB5 gate was voided by the retire: it must not be accepted
        with self.assertRaises(ValueError) as voided:
            await ui_contract.require_gate(self.owner, [r3], rb5, fresh=True)
        self.assertTrue(str(voided.exception).startswith('UI_PREFLIGHT_REQUIRED'))
        # RB7: preflight the whole pool again; only then is the gate usable
        rb7 = await self.pass_preflight([r3, r4])
        self.assertNotEqual(rb7, rb5)
        for runner in (r3, r4):
            self.assertEqual(await ui_contract.require_gate(self.owner, [runner], fresh=True), rb7)
        # the retired error is not restored by any of this
        state = await self.state()
        self.assertFalse(state['blocked'])
        self.assertNotIn(r1, state['runnerErrors'])

    async def test_recovery_evidence_is_kept_in_the_sql_payload(self):               # GX5
        request = Request({'type': 'http', 'headers': [(b'x-vahan-runner-id', self.runner_a.encode())]})
        request.state.authenticated_runner = True
        check = observation(recovery={'recovered': True, 'droppedCookie': 'analytics_sh_cok'})
        with patch('app.api.ui_health.sio.emit', new=AsyncMock()):
            await receive_ui_health_log(UiHealthLogRequest(runnerId=self.runner_a, healthCheck=check), request)
        async with engine.connect() as c:
            saved = await c.scalar(select(db.ui_health_checks.c.payload).where(db.ui_health_checks.c.id == check['checkId']))
        self.assertEqual(saved['healthCheck']['recovery']['droppedCookie'], 'analytics_sh_cok')


if __name__ == '__main__':
    unittest.main(verbosity=2)
