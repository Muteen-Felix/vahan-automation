"""Durable shared queue for independent State/RTO report cases."""
from datetime import datetime, timezone
import re
from uuid import UUID

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import engine, schema as db
from app.models.job import Job, JobStatus
from app.models.runner import Runner, RunnerStatus
from app.repositories.postgres import PostgresJobRepository, runner_document

MAX_FAILURES = 2
MAX_ACTIVE_WORKERS = 10
TERMINAL_TASKS = {'COMPLETED', 'NO_DATA', 'FAILED'}


def now():
    return datetime.now(timezone.utc)


def task_document(row):
    return {
        'position': row['position'], 'name': row['scenario_name'],
        'status': row['status'], 'attempts': row['attempts'],
        'failures': row['failures'], 'runnerId': row['runner_id'],
        'jobId': row['job_id'], 'error': row['error'],
    }


class BatchQueueRepository:
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
        job_row = (await connection.execute(select(db.jobs.c.payload).where(
            db.jobs.c.id == row['job_id']))).scalar_one_or_none()
        if not job_row:
            return row
        job = Job.model_validate(job_row)
        if job.status not in {JobStatus.COMPLETED, JobStatus.NO_DATA, JobStatus.FAILED, JobStatus.CANCELLED}:
            return row
        if job.status in {JobStatus.COMPLETED, JobStatus.NO_DATA}:
            status, failures = job.status.value, row['failures']
        elif job.status == JobStatus.CANCELLED:
            status, failures = 'PENDING', row['failures']
        else:
            failures = row['failures'] + 1
            status = 'FAILED' if failures >= MAX_FAILURES else 'PENDING'
        values = dict(status=status, failures=failures, error=job.error, updated_at=now())
        await connection.execute(update(db.batch_queue_tasks).where(
            db.batch_queue_tasks.c.session_id == row['session_id'],
            db.batch_queue_tasks.c.position == row['position']).values(**values))
        return {**row, **values}

    async def _reconcile_successful_retries(self, connection, rows):
        failed = {row['job_id']: row for row in rows if row['status'] == 'FAILED' and row['job_id']}
        if not failed:
            return rows
        retry_rows = (await connection.execute(select(db.jobs.c.id, db.jobs.c.runner_id,
            db.jobs.c.status, db.jobs.c.filters, db.jobs.c.payload).where(
            db.jobs.c.session_id == rows[0]['session_id'],
            db.jobs.c.status.in_(['COMPLETED', 'NO_DATA']),
            db.jobs.c.payload['retry_of_job_id'].as_string().in_(list(failed))
        ).order_by(db.jobs.c.updated_at.desc()))).mappings().all()
        replacements = {}
        for retry in retry_rows:
            previous_id = retry['payload'].get('retry_of_job_id')
            task = failed.get(previous_id)
            if (not task or task['position'] in replacements or retry['filters'] != task['filters']
                    or retry['payload'].get('scenario_name') != task['scenario_name']):
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
            rows = (await connection.execute(select(db.batch_queue_tasks).where(
                db.batch_queue_tasks.c.session_id == str(session_id)).order_by(
                db.batch_queue_tasks.c.position).with_for_update())).mappings().all()
            rows = await self._reconcile_successful_retries(connection, rows)
            tasks = [task_document(await self._settle(connection, row)) for row in rows]
        return {'sessionId': str(session_id), 'status': session['status'], 'maxWorkers': session['max_workers'], 'tasks': tasks}

    async def settle(self, session_id: UUID, owner: str, position: int):
        async with engine.begin() as connection:
            await self._session(connection, session_id, owner)
            row = (await connection.execute(select(db.batch_queue_tasks).where(
                db.batch_queue_tasks.c.session_id == str(session_id),
                db.batch_queue_tasks.c.position == position).with_for_update())).mappings().first()
            if not row:
                raise LookupError('Queue case not found.')
            return task_document(await self._settle(connection, row))

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
            from app.worker_pool import assignment_status
            allocation, count = await assignment_status(connection, runner_id)
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
            row = (await connection.execute(select(db.batch_queue_tasks).where(
                db.batch_queue_tasks.c.session_id == str(session_id),
                db.batch_queue_tasks.c.status == 'PENDING',
                or_(db.batch_queue_tasks.c.failures == 0,
                    session['max_workers'] == 1,
                    db.batch_queue_tasks.c.runner_id.is_(None),
                    db.batch_queue_tasks.c.runner_id != runner_id)).order_by(
                db.batch_queue_tasks.c.position).limit(1).with_for_update(skip_locked=True))).mappings().first()
            if not row:
                # A client may vanish after a job ends but before it calls
                # /settle. Reconcile at most ten active attempts, then offer
                # any newly requeued work to this available runner.
                processing = (await connection.execute(select(db.batch_queue_tasks).where(
                    db.batch_queue_tasks.c.session_id == str(session_id),
                    db.batch_queue_tasks.c.status == 'PROCESSING').order_by(
                    db.batch_queue_tasks.c.position).limit(10).with_for_update(skip_locked=True))).mappings().all()
                for active_task in processing:
                    await self._settle(connection, active_task)
                row = (await connection.execute(select(db.batch_queue_tasks).where(
                    db.batch_queue_tasks.c.session_id == str(session_id),
                    db.batch_queue_tasks.c.status == 'PENDING',
                    or_(db.batch_queue_tasks.c.failures == 0,
                        session['max_workers'] == 1,
                        db.batch_queue_tasks.c.runner_id.is_(None),
                        db.batch_queue_tasks.c.runner_id != runner_id)).order_by(
                    db.batch_queue_tasks.c.position).limit(1).with_for_update(skip_locked=True))).mappings().first()
            if not row:
                unfinished = await connection.scalar(select(db.batch_queue_tasks.c.position).where(
                    db.batch_queue_tasks.c.session_id == str(session_id),
                    db.batch_queue_tasks.c.status.in_(['PENDING', 'PROCESSING'])).limit(1))
                return {'type': 'waiting' if unfinished is not None else 'done'}
            previous = None
            if row['job_id']:
                payload = await connection.scalar(select(db.jobs.c.payload).where(db.jobs.c.id == row['job_id']))
                previous = Job.model_validate(payload) if payload else None
                if previous and previous.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
                    raise ValueError('Previous queue attempt has not ended.')
            from app.models.filters import VahanFilters
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
                runner_id=runner_id, job_id=str(job.id), error=None, updated_at=now())
            await connection.execute(update(db.batch_queue_tasks).where(
                db.batch_queue_tasks.c.session_id == str(session_id),
                db.batch_queue_tasks.c.position == row['position']).values(**values))
        return {'type': 'assigned', 'task': task_document({**row, **values}), 'jobId': str(job.id),
                'recovered': False, 'job': job}
