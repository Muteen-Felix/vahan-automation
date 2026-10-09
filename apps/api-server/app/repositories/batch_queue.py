"""Durable shared queue for independent State/RTO report cases."""
from datetime import datetime, timezone
import re
from uuid import UUID

from sqlalchemy import and_, case, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import engine, schema as db
from app.models.job import Job, JobStatus
from app.models.runner import Runner, RunnerStatus
from app.models.validation_stop import VALIDATION_STOP_CODES, requires_operator
from app.repositories.postgres import PostgresJobRepository, runner_document

MAX_FAILURES = 2
CHECKPOINT_SIZE = 10
RETRY_KEY = 'batch-retry-policy:'
MAX_ACTIVE_WORKERS = 10
TERMINAL_TASKS = {'COMPLETED', 'NO_DATA', 'FAILED'}


def now():
    return datetime.now(timezone.utc)


def automatic_retry_condition():
    error = func.coalesce(db.batch_queue_tasks.c.error, '')
    return and_(*(~error.startswith(code + ':', autoescape=True) for code in VALIDATION_STOP_CODES))


def task_document(row, policy=None):
    return {
        'position': row['position'], 'name': row['scenario_name'],
        'status': row['status'], 'attempts': row['attempts'],
        'failures': row['failures'], 'runnerId': row['runner_id'],
        'jobId': row['job_id'], 'error': row['error'],
        'requiresOperator': requires_operator(row['error']),
        'recoveryPending': bool(policy and not policy['finalPassStarted'] and row['status'] == 'FAILED'
                                and not requires_operator(row['error'])),
    }


class BatchQueueRepository:
    async def _policy(self, connection, session):
        return await connection.scalar(select(db.app_settings.c.value).where(
            db.app_settings.c.key == RETRY_KEY + session['session_id']))

    async def _save_policy(self, connection, session, policy):
        await connection.execute(pg_insert(db.app_settings).values(
            key=RETRY_KEY + session['session_id'], value=policy).on_conflict_do_update(
                index_elements=[db.app_settings.c.key], set_={'value': policy}))

    async def needs_work(self, session_id, owner):
        """Include a future final sweep without loading every case before each claim."""
        async with engine.connect() as connection:
            session = await self._session(connection, session_id, owner)
            pending = await connection.scalar(select(db.batch_queue_tasks.c.position).where(
                db.batch_queue_tasks.c.session_id == str(session_id),
                (db.batch_queue_tasks.c.status == 'PROCESSING') |
                ((db.batch_queue_tasks.c.status == 'PENDING') & automatic_retry_condition())).limit(1))
            if pending is not None:
                return True
            policy = await self._policy(connection, session)
            if policy and not policy['finalPassStarted']:
                return (await connection.scalar(select(db.batch_queue_tasks.c.position).where(
                    db.batch_queue_tasks.c.session_id == str(session_id),
                    db.batch_queue_tasks.c.status == 'FAILED', automatic_retry_condition()).limit(1))) is not None
            return False

    async def _policy_rows(self, connection, session, policy):
        tasks = db.batch_queue_tasks
        condition = tasks.c.position.in_(policy['finalTargets']) if policy['phase'] in {'FINAL', 'DONE'} else (
            (tasks.c.position >= policy['windowStart']) & (tasks.c.position < policy['windowEnd']))
        return [dict(row) for row in (await connection.execute(select(
            tasks.c.position, tasks.c.status, tasks.c.attempts, tasks.c.failures,
            tasks.c.runner_id, tasks.c.job_id, tasks.c.error
        ).where(tasks.c.session_id == session['session_id'], condition)
            .order_by(tasks.c.position).with_for_update())).mappings()]

    async def _stop_operator_retries(self, connection, session, rows):
        # An older process may already have reopened a stopped case. Restore
        # FAILED before another claim without faking extra failed attempts.
        positions = [row['position'] for row in rows if row['status'] == 'PENDING'
                     and requires_operator(row.get('error'))]
        if positions:
            await connection.execute(update(db.batch_queue_tasks).where(
                db.batch_queue_tasks.c.session_id == session['session_id'],
                db.batch_queue_tasks.c.position.in_(positions),
                db.batch_queue_tasks.c.status == 'PENDING').values(status='FAILED', updated_at=now()))
            rows = [{**row, 'status': 'FAILED'} if row['position'] in positions else row for row in rows]
        return rows

    async def _advance_policy(self, connection, session, rows, complete_rows=True):
        policy = await self._policy(connection, session)
        if not policy:
            # Completed historical sessions stay completed. Explicit claims can
            # opt an unfinished legacy queue into the durable checkpoint policy.
            return None, rows
        if session['status'] != 'RUNNING':
            return policy, rows
        rows = await self._stop_operator_retries(connection, session, rows)
        policy = dict(policy)
        original = dict(policy)
        while policy['phase'] not in {'FINAL', 'DONE'}:
            window = [row for row in rows if policy['windowStart'] <= row['position'] < policy['windowEnd']]
            if any(row['status'] == 'PROCESSING' for row in window):
                break
            if policy['phase'] == 'PRIMARY':
                if any(row['status'] == 'PENDING' and row['failures'] == 0 for row in window):
                    break
                policy['phase'] = 'CHECKPOINT'
            if any(row['status'] == 'PENDING' and 0 < row['failures'] < MAX_FAILURES for row in window):
                break
            policy['lastCheckpoint'] = policy['windowEnd']
            if policy['windowEnd'] < session['total']:
                policy.update(phase='PRIMARY', windowStart=policy['windowEnd'],
                              windowEnd=min(session['total'], policy['windowEnd'] + CHECKPOINT_SIZE))
                if not complete_rows:
                    rows = await self._policy_rows(connection, session, policy)
                    rows = await self._stop_operator_retries(connection, session, rows)
                continue
            failed = [row for row in rows if row['status'] == 'FAILED' and not requires_operator(row.get('error'))] if complete_rows else list(
                (await connection.execute(select(db.batch_queue_tasks.c.position).where(
                    db.batch_queue_tasks.c.session_id == session['session_id'],
                    db.batch_queue_tasks.c.status == 'FAILED', automatic_retry_condition()).with_for_update())).mappings())
            policy.update(phase='FINAL' if failed else 'DONE', finalPassStarted=True,
                          finalTargets=[row['position'] for row in failed])
            if failed:
                positions = policy['finalTargets']
                await connection.execute(update(db.batch_queue_tasks).where(
                    db.batch_queue_tasks.c.session_id == session['session_id'],
                    db.batch_queue_tasks.c.position.in_(positions),
                    db.batch_queue_tasks.c.status == 'FAILED').values(status='PENDING', updated_at=now()))
                rows = [{**row, 'status': 'PENDING'} if row['position'] in positions else row for row in rows]
                if not complete_rows:
                    rows = await self._policy_rows(connection, session, policy)
            break
        if policy['phase'] == 'FINAL' and not any(
            row['position'] in policy['finalTargets'] and row['status'] in {'PENDING', 'PROCESSING'} for row in rows
        ):
            policy['phase'] = 'DONE'
        if policy != original:
            await self._save_policy(connection, session, policy)
        return policy, rows

    def _retry_progress(self, policy, rows):
        if not policy:
            return None
        return {'phase': policy['phase'], 'checkpointStart': policy['windowStart'],
            'checkpointEnd': policy['windowEnd'], 'lastCheckpoint': policy.get('lastCheckpoint', 0),
            'finalPassStarted': policy['finalPassStarted'],
            'failedRemaining': sum(row['failures'] > 0 and row['status'] not in {'COMPLETED', 'NO_DATA'} for row in rows),
            'pendingRetries': sum(row['failures'] > 0 and row['status'] in {'PENDING', 'PROCESSING'} for row in rows),
            'complete': policy['phase'] == 'DONE'}

    async def _claim_progress(self, connection, policy, rows, session):
        progress = self._retry_progress(policy, rows)
        if progress:
            tasks = db.batch_queue_tasks
            failed, pending = (await connection.execute(select(
                func.count().filter((tasks.c.failures > 0) & tasks.c.status.not_in(['COMPLETED', 'NO_DATA'])),
                func.count().filter((tasks.c.failures > 0) & tasks.c.status.in_(['PENDING', 'PROCESSING']))
            ).where(tasks.c.session_id == session['session_id']))).one()
            progress.update(failedRemaining=failed, pendingRetries=pending)
        return progress

    async def start(self, session_id: UUID, owner: str, tasks: list, max_workers: int = MAX_ACTIVE_WORKERS):
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or not 1 <= max_workers <= MAX_ACTIVE_WORKERS:
            raise ValueError('Choose between 1 and 10 workers.')
        from app.models.filter_profile import case_key
        office_keys = [case_key(task.filters.model_dump(mode='json', by_alias=True))
                      for task in tasks if len(task.filters.states) == 1 and len(task.filters.rtos) == 1
                      and task.filters.states[0].strip() and task.filters.rtos[0].strip()]
        if len(office_keys) != len(tasks) or len(set(office_keys)) != len(tasks):
            raise ValueError('Every queue case needs one State, one RTO and a distinct filter combination.')
        session_key = str(session_id)
        async with engine.begin() as connection:
            await connection.execute(pg_insert(db.report_sessions).values(
                id=session_key, owner_username=owner, created_at=now()).on_conflict_do_nothing())
            report = (await connection.execute(select(db.report_sessions).where(
                db.report_sessions.c.id == session_key).with_for_update())).mappings().one()
            if report['owner_username'] != owner or report['deleted_at'] is not None:
                raise ValueError('Report session is unavailable to this user.')
            existing = (await connection.execute(select(db.batch_queue_sessions).where(
                db.batch_queue_sessions.c.session_id == session_key).with_for_update())).mappings().first()
            if existing:
                if existing['owner_username'] != owner or existing['total'] != len(tasks) or existing['max_workers'] != max_workers:
                    raise ValueError('Saved queue has a different owner or case count.')
                originals = (await connection.execute(select(db.batch_queue_tasks.c.position,
                    db.batch_queue_tasks.c.scenario_name, db.batch_queue_tasks.c.filters).where(
                    db.batch_queue_tasks.c.session_id == session_key).order_by(db.batch_queue_tasks.c.position))).mappings().all()
                if len(originals) != len(tasks) or any(row['position'] != position or row['scenario_name'] != task.name
                       or row['filters'] != task.filters.model_dump(mode='json', by_alias=True)
                       for position, (row, task) in enumerate(zip(originals, tasks))):
                    raise ValueError('Saved queue cases changed. Start a new report session.')
                return
            await connection.execute(insert(db.batch_queue_sessions).values(
                session_id=session_key, owner_username=owner, status='RUNNING',
                total=len(tasks), max_workers=max_workers, created_at=now(), updated_at=now()))
            await connection.execute(insert(db.batch_queue_tasks), [{
                'session_id': session_key, 'position': position, 'scenario_name': task.name,
                'filters': task.filters.model_dump(mode='json', by_alias=True),
                'status': 'PENDING', 'attempts': 0, 'failures': 0,
                'runner_id': None, 'job_id': None, 'error': None, 'updated_at': now(),
            } for position, task in enumerate(tasks)])
            await self._save_policy(connection, {'session_id': session_key}, {
                'version': 1, 'phase': 'PRIMARY', 'windowStart': 0,
                'windowEnd': min(CHECKPOINT_SIZE, len(tasks)), 'lastCheckpoint': 0,
                'finalPassStarted': False, 'finalTargets': []})

    async def _session(self, connection, session_id: UUID, owner: str, lock=False):
        query = select(db.batch_queue_sessions).where(db.batch_queue_sessions.c.session_id == str(session_id))
        if lock:
            query = query.with_for_update()
        row = (await connection.execute(query)).mappings().first()
        if not row or row['owner_username'] != owner:
            raise LookupError('Queue session not found.')
        return row

    async def _settle(self, connection, row):
        if row['status'] != 'PROCESSING' or not row['job_id']:
            return row
        job_row = (await connection.execute(select(db.jobs.c.status,
            db.jobs.c.payload['error'].as_string().label('error')).where(
            db.jobs.c.id == row['job_id']))).mappings().first()
        if not job_row:
            return row
        job_status = job_row['status']
        if job_status not in {'COMPLETED', 'NO_DATA', 'FAILED', 'CANCELLED'}:
            return row
        if job_status in {'COMPLETED', 'NO_DATA'}:
            status, failures = job_status, row['failures']
        elif job_status == 'CANCELLED':
            status, failures = 'PENDING', row['failures']
        else:
            failures = row['failures'] + 1
            policy = await connection.scalar(select(db.app_settings.c.value).where(
                db.app_settings.c.key == RETRY_KEY + row['session_id']))
            final_attempt = policy and policy['phase'] == 'FINAL' and row['position'] in policy['finalTargets']
            status = 'FAILED' if requires_operator(job_row['error']) or final_attempt or failures >= MAX_FAILURES else 'PENDING'
        error = row['error'] if job_status == 'CANCELLED' and row['failures'] else job_row['error']
        values = dict(status=status, failures=failures, error=error, updated_at=now())
        await connection.execute(update(db.batch_queue_tasks).where(
            db.batch_queue_tasks.c.session_id == row['session_id'],
            db.batch_queue_tasks.c.position == row['position']).values(**values))
        return {**row, **values}

    async def _reconcile_successful_retries(self, connection, rows):
        failed = {row['job_id']: row for row in rows if row['status'] == 'FAILED' and row['job_id']}
        if not failed:
            return rows
        retry_rows = (await connection.execute(select(db.jobs.c.id, db.jobs.c.runner_id,
            db.jobs.c.status, db.jobs.c.filters, db.jobs.c.retry_of_job_id, db.jobs.c.scenario_name).where(
            db.jobs.c.session_id == rows[0]['session_id'],
            db.jobs.c.status.in_(['COMPLETED', 'NO_DATA']),
            db.jobs.c.retry_of_job_id.in_(list(failed))
        ).order_by(db.jobs.c.updated_at.desc()))).mappings().all()
        replacements = {}
        for retry in retry_rows:
            previous_id = retry['retry_of_job_id']
            task = failed.get(previous_id)
            if (not task or task['position'] in replacements or retry['filters'] != task['filters']
                    or retry['scenario_name'] != task['scenario_name']):
                continue
            values = dict(status=retry['status'], attempts=task['attempts'] + 1,
                runner_id=retry['runner_id'], job_id=retry['id'], error=None, updated_at=now())
            result = await connection.execute(update(db.batch_queue_tasks).where(
                db.batch_queue_tasks.c.session_id == task['session_id'],
                db.batch_queue_tasks.c.position == task['position'],
                db.batch_queue_tasks.c.status == 'FAILED',
                db.batch_queue_tasks.c.job_id == previous_id).values(**values))
            if result.rowcount:
                replacements[task['position']] = {**task, **values}
        return [replacements.get(row['position'], row) for row in rows]

    async def snapshot(self, session_id: UUID, owner: str):
        async with engine.begin() as connection:
            session = await self._session(connection, session_id, owner, lock=True)
            # Only unsettled cases need row locks/full filters. Completed and
            # pending rows remain cheap projections even in a 100,000-case queue.
            mutable = (await connection.execute(select(db.batch_queue_tasks).where(
                db.batch_queue_tasks.c.session_id == str(session_id),
                db.batch_queue_tasks.c.status.in_(['PROCESSING', 'FAILED']))
                .order_by(db.batch_queue_tasks.c.position).with_for_update())).mappings().all()
            mutable = await self._reconcile_successful_retries(connection, mutable)
            for row in mutable:
                await self._settle(connection, row)
            tasks_table = db.batch_queue_tasks
            rows = (await connection.execute(select(*[column for column in tasks_table.c
                if column.name != 'filters']).where(tasks_table.c.session_id == str(session_id))
                .order_by(tasks_table.c.position))).mappings().all()
            policy, rows = await self._advance_policy(connection, session, rows)
            tasks = [task_document(row, policy) for row in rows]
        return {'sessionId': str(session_id), 'status': session['status'], 'maxWorkers': session['max_workers'],
                'tasks': tasks, 'retry': self._retry_progress(policy, rows)}

    async def settle(self, session_id: UUID, owner: str, position: int):
        async with engine.begin() as connection:
            session = await self._session(connection, session_id, owner, lock=True)
            row = (await connection.execute(select(db.batch_queue_tasks).where(
                db.batch_queue_tasks.c.session_id == str(session_id),
                db.batch_queue_tasks.c.position == position).with_for_update())).mappings().first()
            if not row:
                raise LookupError('Queue case not found.')
            return task_document(await self._settle(connection, row), await self._policy(connection, session))

    async def set_status(self, session_id: UUID, owner: str, status: str, max_workers: int | None = None):
        async with engine.begin() as connection:
            session = await self._session(connection, session_id, owner, lock=True)
            values = dict(status=status, updated_at=now())
            if max_workers is not None and max_workers != session['max_workers']:
                if not 1 <= max_workers <= MAX_ACTIVE_WORKERS or session['status'] != 'PAUSED':
                    raise ValueError('Pause the queue before changing its worker count.')
                processing = (await connection.execute(select(db.batch_queue_tasks).where(
                    db.batch_queue_tasks.c.session_id == str(session_id), db.batch_queue_tasks.c.status == 'PROCESSING')
                    .with_for_update())).mappings().all()
                for task in processing:
                    await self._settle(connection, task)
                active = await connection.scalar(select(func.count()).select_from(db.batch_queue_tasks).where(
                    db.batch_queue_tasks.c.session_id == str(session_id), db.batch_queue_tasks.c.status == 'PROCESSING'))
                if active:
                    raise ValueError('Wait for active cases to stop before changing workers.')
                values['max_workers'] = max_workers
            await connection.execute(update(db.batch_queue_sessions).where(
                db.batch_queue_sessions.c.session_id == str(session_id)).values(**values))

    async def claim(self, session_id: UUID, owner: str, runner_id: str):
        async with engine.begin() as connection:
            preliminary = await self._session(connection, session_id, owner)
            if preliminary['status'] != 'RUNNING': return {'type': 'paused'}
            from app.worker_pool import assignment_status, capacity_available
            allocation, count = await assignment_status(connection, runner_id)
            if allocation == 'offline': return {'type': 'network_paused'}
            if allocation == 'updating': return {'type': 'pool_updating'}
            number = re.fullmatch(r'playwright-(\d+)', runner_id)
            if allocation == 'disabled' or (number and int(number[1]) > preliminary['max_workers']):
                return {'type': 'worker_disabled', 'workerCount': min(preliminary['max_workers'], count or 10)}
            runner_row = (await connection.execute(select(db.runners).where(
                db.runners.c.id == runner_id).with_for_update())).mappings().first()
            await connection.execute(select(db.report_sessions.c.id).where(
                db.report_sessions.c.id == str(session_id)).with_for_update())
            session = await self._session(connection, session_id, owner, lock=True)
            if session['status'] != 'RUNNING':
                return {'type': 'paused'}
            if not runner_row or not runner_row['connected']:
                return {'type': 'runner_unavailable'}
            if await connection.scalar(select(db.runner_planning_leases.c.runner_id).where(
                db.runner_planning_leases.c.runner_id == runner_id, db.runner_planning_leases.c.expires_at > now())):
                return {'type': 'waiting'}
            runner = Runner.model_validate(runner_row['payload'])
            if runner.current_job_id:
                existing = (await connection.execute(select(db.batch_queue_tasks).where(
                    db.batch_queue_tasks.c.session_id == str(session_id),
                    db.batch_queue_tasks.c.job_id == runner.current_job_id,
                    db.batch_queue_tasks.c.status == 'PROCESSING'))).mappings().first()
                if existing:
                    return {'type': 'assigned', 'task': task_document(existing), 'jobId': runner.current_job_id,
                            'recovered': True}
                return {'type': 'runner_unavailable'}
            if runner.status == RunnerStatus.RECONNECTING or runner.source != 'new':
                return {'type': 'runner_unavailable'}
            active_count = await connection.scalar(select(func.count()).select_from(db.batch_queue_tasks).where(
                db.batch_queue_tasks.c.session_id == str(session_id),
                db.batch_queue_tasks.c.status == 'PROCESSING'))
            if active_count >= session['max_workers']:
                processing = (await connection.execute(select(db.batch_queue_tasks).where(
                    db.batch_queue_tasks.c.session_id == str(session_id),
                    db.batch_queue_tasks.c.status == 'PROCESSING').limit(session['max_workers'])
                    .with_for_update(skip_locked=True))).mappings().all()
                for active_task in processing:
                    await self._settle(connection, active_task)
                active_count = await connection.scalar(select(func.count()).select_from(db.batch_queue_tasks).where(
                    db.batch_queue_tasks.c.session_id == str(session_id),
                    db.batch_queue_tasks.c.status == 'PROCESSING'))
                if active_count >= session['max_workers']:
                    return {'type': 'waiting'}
            policy = await self._policy(connection, session)
            if not policy:
                unfinished = await connection.scalar(select(db.batch_queue_tasks.c.position).where(
                    db.batch_queue_tasks.c.session_id == session['session_id'],
                    db.batch_queue_tasks.c.status.in_(['PENDING', 'PROCESSING']))
                    .order_by(db.batch_queue_tasks.c.position).limit(1))
                if unfinished is None:
                    return {'type': 'done'}
                window_start = unfinished // CHECKPOINT_SIZE * CHECKPOINT_SIZE
                policy = {'version': 1, 'phase': 'PRIMARY', 'windowStart': window_start,
                    'windowEnd': min(session['total'], window_start + CHECKPOINT_SIZE),
                    'lastCheckpoint': window_start, 'finalPassStarted': False, 'finalTargets': []}
                await self._save_policy(connection, session, policy)
            rows = await self._policy_rows(connection, session, policy)
            # Settle terminal jobs even if their coordinator disappeared before /settle.
            for active_task in rows:
                if active_task['status'] == 'PROCESSING':
                    full = (await connection.execute(select(db.batch_queue_tasks).where(
                        db.batch_queue_tasks.c.session_id == session['session_id'],
                        db.batch_queue_tasks.c.position == active_task['position']))).mappings().one()
                    settled = await self._settle(connection, full)
                    active_task.update(status=settled['status'], failures=settled['failures'], error=settled['error'])
            policy, rows = await self._advance_policy(connection, session, rows, complete_rows=False)
            progress = await self._claim_progress(connection, policy, rows, session)
            if policy['phase'] == 'DONE':
                return {'type': 'done', 'retry': progress}
            tasks = db.batch_queue_tasks
            stage = tasks.c.position.in_(policy['finalTargets']) if policy['phase'] == 'FINAL' else (
                (tasks.c.position >= policy['windowStart']) & (tasks.c.position < policy['windowEnd']) &
                (tasks.c.failures == 0 if policy['phase'] == 'PRIMARY' else
                 (tasks.c.failures > 0) & (tasks.c.failures < MAX_FAILURES)))
            row = (await connection.execute(select(tasks).where(
                tasks.c.session_id == session['session_id'], tasks.c.status == 'PENDING', stage,
                automatic_retry_condition()
            ).order_by(case(((tasks.c.failures > 0) & (tasks.c.runner_id == runner_id), 1), else_=0),
                       tasks.c.position).limit(1).with_for_update(skip_locked=True))).mappings().first()
            if not row:
                return {'type': 'waiting', 'retry': progress}
            previous = None
            if row['job_id']:
                payload = await connection.scalar(select(db.jobs.c.payload).where(db.jobs.c.id == row['job_id']))
                previous = Job.model_validate(payload) if payload else None
                if previous and previous.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
                    raise ValueError('Previous queue attempt has not ended.')
            from app.models.filters import VahanFilters
            if not await capacity_available(connection, [runner_id]):
                return {'type': 'waiting'}
            job = Job(runnerId=runner_id, sessionId=session_id,
                filters=VahanFilters.model_validate(row['filters']), scenarioName=row['scenario_name'],
                status=JobStatus.ASSIGNED, ownerUsername=owner,
                retryOfJobId=previous.id if previous else None,
                caseId=(previous.case_id or previous.id) if previous else None)
            await PostgresJobRepository()._insert(connection, job)
            runner.current_job_id = str(job.id)
            runner.status = RunnerStatus.BUSY
            await connection.execute(update(db.runners).where(db.runners.c.id == runner_id).values(
                current_job_id=str(job.id), payload=runner_document(runner)))
            values = dict(status='PROCESSING', attempts=row['attempts'] + 1,
                runner_id=runner_id, job_id=str(job.id), error=row['error'] if row['failures'] else None, updated_at=now())
            await connection.execute(update(db.batch_queue_tasks).where(
                db.batch_queue_tasks.c.session_id == str(session_id),
                db.batch_queue_tasks.c.position == row['position']).values(**values))
        return {'type': 'assigned', 'task': task_document({**row, **values}, policy), 'jobId': str(job.id),
                'recovered': False, 'job': job, 'retry': progress}
