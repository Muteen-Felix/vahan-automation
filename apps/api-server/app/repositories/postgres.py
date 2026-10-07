from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, update, delete, insert, func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import engine
from app.config import settings
from app.db import schema as db
from app.models.job import Job, JobStatus, can_transition
from app.models.runner import Runner, RunnerStatus
from app.models.ui_health import UiHealthSchedule
from app.state_codec import encode_user_state, decode_user_state

TERMINAL = {JobStatus.COMPLETED, JobStatus.NO_DATA, JobStatus.FAILED, JobStatus.CANCELLED}

def now():
    return datetime.now(timezone.utc)

def require_test_database():
    from sqlalchemy.engine import make_url
    name = make_url(settings.database_url).database or ''
    if os.environ.get('VAHAN_ALLOW_DATABASE_CLEAR') != 'test-only' or not name.endswith('_test'):
        raise RuntimeError('Bulk clear is disabled. Use a dedicated test database and explicit test-only flag.')

def job_document(job):
    payload = job.model_dump(mode="json")
    payload["captcha_image_data_url"] = job.captcha_image_data_url
    payload["successful_apply_click_ids"] = job.successful_apply_click_ids
    return payload

async def save_job(connection, job, event="updated"):
    await connection.execute(update(db.jobs).where(db.jobs.c.id == str(job.id)).values(
        status=job.status.value, payload=job_document(job), updated_at=job.updated_at))
    await connection.execute(insert(db.job_events).values(id=str(uuid4()), job_id=str(job.id),
        event=event, payload=job.model_dump(mode='json', by_alias=True), created_at=now()))

def runner_document(runner):
    return {**runner.model_dump(mode="json"), "socket_id": runner.socket_id}

async def release_runner(connection, runner_id, job_id):
    row = (await connection.execute(select(db.runners).where(db.runners.c.id == runner_id).with_for_update())).mappings().first()
    if row and row["current_job_id"] == str(job_id):
        runner = Runner.model_validate(row["payload"])
        runner.current_job_id = None
        if runner.status != RunnerStatus.RECONNECTING:
            runner.status = RunnerStatus.ONLINE
        await connection.execute(update(db.runners).where(db.runners.c.id == runner_id).values(
            current_job_id=None, payload=runner_document(runner)))

class PostgresJobRepository:
    async def create(self, job):
        async with engine.begin() as connection:
            await self._insert(connection, job)
        return job.model_copy(deep=True)

    async def _insert(self, connection, job):
        if job.retry_of_job_id:
            payload = await connection.scalar(select(db.jobs.c.payload).where(
                db.jobs.c.id == str(job.retry_of_job_id)).with_for_update())
            previous = Job.model_validate(payload) if payload else None
            if not previous or previous.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
                raise ValueError('Only an existing failed or stopped job can be retried.')
            if (previous.owner_username != job.owner_username or previous.session_id != job.session_id
                    or previous.filters != job.filters or previous.source != job.source
                    or previous.update_kind != job.update_kind or previous.update_run_id != job.update_run_id
                    or previous.update_task_id != job.update_task_id):
                raise ValueError('Retry must preserve the original owner, session, filters and source.')
            child = await connection.scalar(select(db.jobs.c.id).where(
                db.jobs.c.payload['retry_of_job_id'].as_string() == str(previous.id)).limit(1))
            if child:
                raise ValueError('This job already has a retry. Retry the latest failed attempt instead.')
            job.case_id = previous.case_id or previous.id
        else:
            job.case_id = job.id
        await connection.execute(pg_insert(db.report_sessions).values(id=str(job.session_id),
            owner_username=job.owner_username, created_at=job.created_at).on_conflict_do_nothing())
        session = (await connection.execute(select(db.report_sessions).where(
            db.report_sessions.c.id == str(job.session_id)).with_for_update())).mappings().one()
        if session['owner_username'] != job.owner_username:
            raise ValueError('Report session belongs to another user.')
        if session['deleted_at'] is not None:
            raise ValueError('Report session was deleted. Restore it before continuing or retrying.')
        await connection.execute(insert(db.jobs).values(id=str(job.id), owner_username=job.owner_username,
            session_id=str(job.session_id), runner_id=job.runner_id, status=job.status.value,
            filters=job.filters.model_dump(mode="json", by_alias=True), payload=job_document(job),
            created_at=job.created_at, updated_at=job.updated_at))
        await connection.execute(insert(db.job_events).values(id=str(uuid4()), job_id=str(job.id),
            event="created", payload={"status": job.status.value}, created_at=now()))

    async def assign(self, job):
        async with engine.begin() as connection:
            from app.worker_pool import assignment_allowed
            if not await assignment_allowed(connection, job.runner_id):
                raise ValueError('This Docker worker is stopped or its pool is being updated.')
            row = (await connection.execute(select(db.runners).where(db.runners.c.id == job.runner_id).with_for_update())).mappings().first()
            if not row or not row["connected"] or row["current_job_id"]:
                return None
            reserved = await connection.scalar(select(db.runner_planning_leases.c.runner_id).where(
                db.runner_planning_leases.c.runner_id == job.runner_id,
                db.runner_planning_leases.c.expires_at > now()))
            if reserved:
                return None
            runner = Runner.model_validate(row["payload"])
            if runner.status == RunnerStatus.RECONNECTING:
                return None
            from app.repositories.maker_updates import validate_update_job
            task_id = await validate_update_job(connection, job)
            await self._insert(connection, job)
            if task_id:
                await connection.execute(update(db.maker_update_tasks).where(
                    db.maker_update_tasks.c.id == task_id).values(
                    status='RUNNING', job_id=str(job.id), error=None, updated_at=now()))
            runner.current_job_id = str(job.id)
            runner.status = RunnerStatus.BUSY
            await connection.execute(update(db.runners).where(db.runners.c.id == job.runner_id).values(
                current_job_id=str(job.id), payload=runner_document(runner)))
        return job

    async def get(self, job_id):
        async with engine.connect() as connection:
            payload = await connection.scalar(select(db.jobs.c.payload).where(db.jobs.c.id == str(job_id)))
        return Job.model_validate(payload) if payload else None

    async def _change(self, job_id, operation, event='updated'):
        async with engine.begin() as connection:
            payload = await connection.scalar(select(db.jobs.c.payload).where(db.jobs.c.id == str(job_id)).with_for_update())
            if not payload:
                return None
            job = Job.model_validate(payload)
            if not await operation(job, connection):
                return None
            job.touch()
            await save_job(connection, job, event)
            if job.update_task_id and job.status in {JobStatus.FAILED, JobStatus.CANCELLED}:
                await connection.execute(update(db.maker_update_tasks).where(
                    db.maker_update_tasks.c.id == job.update_task_id,
                    db.maker_update_tasks.c.job_id == str(job.id)).values(
                    status='FAILED', error=job.error or job.status.value, updated_at=now()))
            if job.status in TERMINAL:
                await release_runner(connection, job.runner_id, job.id)
        return job

    async def update_status(self, job_id, status, *, error=None, captcha_id=None, captcha_image_data_url=None,
                            expected_status=None, expected_captcha_id=None):
        async def operation(job, connection):
            if expected_status is not None and job.status != expected_status:
                return False
            if expected_captcha_id is not None and job.captcha_id != expected_captcha_id:
                return False
            if not can_transition(job.status, status):
                return False
            job.status, job.error = status, error
            if captcha_id is not None:
                job.captcha_id = captcha_id
            if captcha_image_data_url is not None:
                job.captcha_image_data_url = captcha_image_data_url
            return True
        return await self._change(job_id, operation)

    async def transition_status(self, job_id, status, *, error=None, no_data_writer=None):
        async def operation(job, connection):
            if not can_transition(job.status, status):
                return False
            if status == JobStatus.COMPLETED and not (job.main_report_checksum and job.main_report_saved_at):
                return False
            if status == JobStatus.NO_DATA and not (job.result_checksum and job.main_report_saved_at
                                                    and job.result_message == 'No record found'):
                return False
            job.status, job.error = status, error
            return True
        return await self._change(job_id, operation)

    async def set_excel_file(self, job_id, *, file_name, file_size):
        async def operation(job, connection):
            if job.status != JobStatus.WAITING_RESULT:
                return False
            job.excel_file_name, job.excel_file_size = file_name, file_size
            return True
        return await self._change(job_id, operation)

    async def set_no_data_file(self, job_id, file_name):
        async def operation(job, connection):
            job.no_data_file_name = file_name
            return True
        return await self._change(job_id, operation)

    async def record_successful_apply_click(self, job_id, click_id):
        async def operation(job, connection):
            if job.status not in {JobStatus.SUBMITTING, JobStatus.WAITING_RESULT}:
                return False
            if click_id not in job.successful_apply_click_ids:
                job.successful_apply_click_ids.append(click_id)
                job.successful_apply_count += 1
            return True
        return await self._change(job_id, operation)

    async def record_filter_execution(self, job_id, runner_id, phase, execution):
        from app.models.filter_execution import validate_against_job
        async def operation(job, connection):
            required = JobStatus.FILLING_FILTERS if phase == 'filled' else JobStatus.SUBMITTING
            if job.runner_id != runner_id or job.status != required:
                return False
            validate_against_job(execution, job.filters)
            job.filter_execution[phase] = execution.model_dump(mode='json', by_alias=True)
            return True
        return await self._change(job_id, operation, 'filters-verified')

    async def list_all(self, owner=None):
        query = select(db.jobs.c.payload).order_by(db.jobs.c.created_at.desc())
        if owner:
            query = query.where(db.jobs.c.owner_username == owner)
        async with engine.connect() as connection:
            return [Job.model_validate(value) for value in (await connection.execute(query)).scalars()]

    async def clear(self):
        require_test_database()
        async with engine.begin() as connection:
            await connection.execute(update(db.runners).values(current_job_id=None))
            await connection.execute(delete(db.stored_files).where(db.stored_files.c.job_id.is_not(None)))
            await connection.execute(delete(db.jobs))
            await connection.execute(delete(db.report_sessions))

class PostgresRunnerRegistry:
    async def register(self, *, runner_id, name, socket_id, version=None, source="new"):
        async with engine.begin() as connection:
            previous = (await connection.execute(select(db.runners).where(db.runners.c.id == runner_id).with_for_update())).mappings().first()
            job_id = previous["current_job_id"] if previous else None
            runner = Runner(id=runner_id, name=name, socketId=socket_id, version=version, source=source,
                currentJobId=job_id, status=RunnerStatus.BUSY if job_id else RunnerStatus.ONLINE)
            statement = pg_insert(db.runners).values(id=runner_id, socket_id=socket_id, connected=True,
                current_job_id=job_id, payload=runner_document(runner))
            await connection.execute(statement.on_conflict_do_update(index_elements=[db.runners.c.id],
                set_={"socket_id": socket_id, "connected": True, "payload": runner_document(runner)}))
        return runner

    async def get(self, runner_id):
        async with engine.connect() as connection:
            payload = await connection.scalar(select(db.runners.c.payload).where(db.runners.c.id == runner_id, db.runners.c.connected.is_(True)))
        return Runner.model_validate(payload) if payload else None

    async def get_by_socket(self, socket_id):
        async with engine.connect() as connection:
            payload = await connection.scalar(select(db.runners.c.payload).where(db.runners.c.socket_id == socket_id, db.runners.c.connected.is_(True)))
        return Runner.model_validate(payload) if payload else None

    async def list(self):
        async with engine.connect() as connection:
            runners = [Runner.model_validate(p) for p in (await connection.execute(select(db.runners.c.payload).where(db.runners.c.connected.is_(True)))).scalars()]
            reserved = set((await connection.execute(select(db.runner_planning_leases.c.runner_id).where(
                db.runner_planning_leases.c.expires_at > now()))).scalars())
            for runner in runners:
                if runner.id in reserved:
                    runner.status = RunnerStatus.BUSY
            return runners

    async def _edit(self, runner_id, operation):
        async with engine.begin() as connection:
            payload = await connection.scalar(select(db.runners.c.payload).where(db.runners.c.id == runner_id).with_for_update())
            if not payload:
                return None
            runner = Runner.model_validate(payload)
            operation(runner)
            runner.last_seen_at = now()
            await connection.execute(update(db.runners).where(db.runners.c.id == runner_id).values(
                payload=runner_document(runner), current_job_id=runner.current_job_id))
        return runner

    async def heartbeat(self, socket_id):
        async with engine.begin() as connection:
            row = (await connection.execute(select(db.runners).where(
                db.runners.c.socket_id == socket_id,
                db.runners.c.connected.is_(True)).with_for_update())).mappings().first()
            if not row:
                return None
            runner = Runner.model_validate(row["payload"])
            runner.status = RunnerStatus.BUSY if row["current_job_id"] else RunnerStatus.ONLINE
            runner.last_seen_at = now()
            await connection.execute(update(db.runners).where(db.runners.c.id == runner.id).values(
                payload=runner_document(runner)))
        return runner

    async def set_job(self, runner_id, job_id):
        def edit(runner):
            runner.current_job_id = job_id
            runner.status = RunnerStatus.BUSY if job_id else RunnerStatus.ONLINE
        return await self._edit(runner_id, edit)

    async def release_job(self, runner_id, job_id):
        async with engine.begin() as connection:
            await release_runner(connection, runner_id, job_id)
        return await self.get(runner_id)

    async def mark_reconnecting(self, socket_id):
        async with engine.begin() as connection:
            row = (await connection.execute(select(db.runners).where(
                db.runners.c.socket_id == socket_id,
                db.runners.c.connected.is_(True)).with_for_update())).mappings().first()
            if not row:
                return None
            runner = Runner.model_validate(row["payload"])
            runner.status = RunnerStatus.RECONNECTING
            runner.last_seen_at = now()
            await connection.execute(update(db.runners).where(db.runners.c.id == runner.id).values(
                payload=runner_document(runner)))
        return runner

    async def remove_by_socket(self, socket_id):
        async with engine.begin() as connection:
            payload = await connection.scalar(select(db.runners.c.payload).where(db.runners.c.socket_id == socket_id).with_for_update())
            if not payload:
                return None
            await connection.execute(update(db.runners).where(db.runners.c.socket_id == socket_id).values(connected=False, socket_id=None))
        return Runner.model_validate(payload)

    async def clear(self):
        require_test_database()
        async with engine.begin() as connection:
            await connection.execute(delete(db.runners))

class PostgresStateStore:
    async def get(self, key, default=None):
        async with engine.connect() as connection:
            value = await connection.scalar(select(db.app_settings.c.value).where(db.app_settings.c.key == key))
        return value if value is not None else default

    async def put(self, key, value):
        async with engine.begin() as connection:
            await connection.execute(pg_insert(db.app_settings).values(key=key, value=value).on_conflict_do_update(
                index_elements=[db.app_settings.c.key], set_={"value": value}))

class PostgresScheduleRepository:
    async def get(self):
        value = await PostgresStateStore().get("ui-health-schedule")
        if value is None:
            return await self.update(3)
        return UiHealthSchedule.model_validate(value)

    async def update(self, interval_days):
        schedule = UiHealthSchedule.for_interval(interval_days)
        await PostgresStateStore().put("ui-health-schedule", schedule.model_dump(mode="json"))
        return schedule

    async def record_check(self):
        schedule = await self.get()
        return await self.update(schedule.interval_days)

    async def clear(self):
        require_test_database()
        await self.update(3)

def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000).hex()
    return f"pbkdf2_sha256$600000${salt}${digest}"

def check_password(password, encoded):
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or iterations != "600000":
            return False
        return hmac.compare_digest(hash_password(password, salt), encoded)
    except (ValueError, TypeError):
        return False

def session_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()

class PostgresUsers:
    async def bootstrap(self, username, password):
        if not username or len(password) < 12:
            return
        hashed = await asyncio.to_thread(hash_password, password)
        async with engine.begin() as connection:
            await connection.execute(pg_insert(db.users).values(username=username, password_hash=hashed,
                role="admin", active=True, profile={}, created_at=now()).on_conflict_do_nothing())

    async def get(self, username):
        async with engine.connect() as connection:
            row = (await connection.execute(select(db.users).where(db.users.c.username == username))).mappings().first()
        return dict(row) if row else None

    async def authenticate(self, username, password):
        user = await self.get(username)
        # Perform one expensive hash even for unknown usernames.
        encoded = user["password_hash"] if user else 'pbkdf2_sha256$600000$' + '0' * 32 + '$' + '0' * 64
        valid = await asyncio.to_thread(check_password, password, encoded)
        return user if user and user["active"] and valid else None

    async def create_session(self, username):
        raw = secrets.token_urlsafe(32)
        async with engine.begin() as connection:
            await connection.execute(insert(db.auth_sessions).values(id=session_hash(raw), username=username,
                revoked=False, created_at=now()))
        return raw

    async def session_user(self, username, session_id):
        async with engine.connect() as connection:
            row = (await connection.execute(select(db.users).join(db.auth_sessions,
                db.auth_sessions.c.username == db.users.c.username).where(db.users.c.username == username,
                db.users.c.active.is_(True), db.auth_sessions.c.id == session_hash(session_id),
                db.auth_sessions.c.revoked.is_(False)))).mappings().first()
        return dict(row) if row else None

    async def revoke(self, session_id):
        async with engine.begin() as connection:
            await connection.execute(update(db.auth_sessions).where(db.auth_sessions.c.id == session_hash(session_id)).values(revoked=True))

    async def list(self):
        async with engine.connect() as connection:
            return [dict(row) for row in (await connection.execute(select(db.users.c.username, db.users.c.role,
                db.users.c.active, db.users.c.profile, db.users.c.created_at))).mappings()]

    async def create(self, username, password, role="user", profile=None):
        hashed = await asyncio.to_thread(hash_password, password)
        async with engine.begin() as connection:
            await connection.execute(insert(db.users).values(username=username, password_hash=hashed,
                role=role, active=True, profile=profile or {}, created_at=now()))

    async def state(self, username):
        async with engine.connect() as connection:
            rows = (await connection.execute(select(db.user_state).where(db.user_state.c.username == username))).mappings()
            return {row["key"]: decode_user_state(row["value"]) for row in rows}

    async def put_state(self, username, key, value):
        value = encode_user_state(value)
        async with engine.begin() as connection:
            await connection.execute(pg_insert(db.user_state).values(username=username, key=key, value=value,
                updated_at=now()).on_conflict_do_update(index_elements=[db.user_state.c.username, db.user_state.c.key],
                set_={"value": value, "updated_at": now()}))

async def recover_after_restart():
    """Keep history; fail interrupted browser actions rather than replaying a submission."""
    repository = PostgresJobRepository()
    async with engine.connect() as connection:
        payloads = (await connection.execute(select(db.jobs.c.payload).where(db.jobs.c.status.not_in([s.value for s in TERMINAL])))).scalars().all()
    for payload in payloads:
        job = Job.model_validate(payload)
        if job.status not in TERMINAL:
            await repository.update_status(job.id, JobStatus.FAILED, error="API restarted; browser context must be restarted. Retry this report explicitly.")
    async with engine.begin() as connection:
            await connection.execute(delete(db.runner_planning_leases))
            await connection.execute(update(db.runners).values(connected=False, socket_id=None, current_job_id=None))

async def audit(actor, event, payload):
    async with engine.begin() as connection:
        await connection.execute(insert(db.audit_events).values(id=str(uuid4()), actor=actor,
            event=event, payload=payload, created_at=now()))
