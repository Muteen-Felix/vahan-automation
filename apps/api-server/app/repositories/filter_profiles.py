from datetime import datetime, timedelta, timezone
import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

from sqlalchemy import delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import engine, schema as db
from app.models.filter_profile import ProfileWrite


def now():
    return datetime.now(timezone.utc)


def document(row):
    return {'id': row['id'], 'name': row['name'], 'revision': row['revision'],
            'definition': row['definition'], 'updatedAt': row['updated_at'].isoformat()}


class FilterProfileRepository:
    async def list(self, owner):
        async with engine.connect() as connection:
            rows = (await connection.execute(select(db.filter_profiles).where(
                db.filter_profiles.c.owner_username == owner).order_by(db.filter_profiles.c.name))).mappings()
            return [document(row) for row in rows]

    async def get(self, owner, profile_id):
        async with engine.connect() as connection:
            row = (await connection.execute(select(db.filter_profiles).where(
                db.filter_profiles.c.owner_username == owner, db.filter_profiles.c.id == str(profile_id)))).mappings().first()
            if not row:
                raise LookupError('Filter profile not found.')
            return document(row)

    async def save(self, owner, command: ProfileWrite, profile_id=None):
        async with engine.begin() as connection:
            values = {'name': command.name, 'definition': command.definition.model_dump(mode='json', by_alias=True),
                      'updated_at': now()}
            if profile_id:
                row = (await connection.execute(select(db.filter_profiles).where(
                    db.filter_profiles.c.id == str(profile_id), db.filter_profiles.c.owner_username == owner)
                    .with_for_update())).mappings().first()
                if not row:
                    raise LookupError('Filter profile not found.')
                if command.revision != row['revision']:
                    raise ValueError('This profile was edited elsewhere. Reload before saving.')
                values['revision'] = row['revision'] + 1
                result = await connection.execute(update(db.filter_profiles).where(
                    db.filter_profiles.c.id == str(profile_id)).values(**values).returning(db.filter_profiles))
            else:
                result = await connection.execute(insert(db.filter_profiles).values(
                    id=str(uuid4()), owner_username=owner, created_at=now(), revision=1, **values)
                    .returning(db.filter_profiles))
            return document(result.mappings().one())

    async def delete(self, owner, profile_id, revision):
        async with engine.begin() as connection:
            row = (await connection.execute(select(db.filter_profiles).where(
                db.filter_profiles.c.id == str(profile_id), db.filter_profiles.c.owner_username == owner)
                .with_for_update())).mappings().first()
            if not row:
                raise LookupError('Filter profile not found.')
            if revision != row['revision']:
                raise ValueError('This profile was edited elsewhere. Reload before deleting.')
            await connection.execute(delete(db.filter_profiles).where(db.filter_profiles.c.id == str(profile_id)))


async def renew_lease(runner_id, token):
    async with engine.begin() as connection:
        updated = await connection.execute(update(db.runner_planning_leases).where(
            db.runner_planning_leases.c.runner_id == runner_id, db.runner_planning_leases.c.token == token)
            .values(expires_at=now() + timedelta(seconds=180)))
        if not updated.rowcount:
            raise PreflightUnavailable(runner_id,'WORKER_RESERVATION_EXPIRED',
                'The worker reservation expired before options finished loading. Filter options will retry automatically.')


class PreflightUnavailable(ValueError):
    """A selected worker cannot be checked right now; this is not DOM evidence."""

    def __init__(self, runner_id, code, message):
        super().__init__(message)
        self.runner_id = runner_id
        self.code = code


async def _renew_preflight_leases(runner_ids, token):
    async with engine.begin() as connection:
        updated = await connection.execute(update(db.runner_planning_leases).where(
            db.runner_planning_leases.c.runner_id.in_(runner_ids),
            db.runner_planning_leases.c.token == token)
            .values(expires_at=now() + timedelta(seconds=180)))
        if updated.rowcount != len(runner_ids):
            raise PreflightUnavailable(None, 'WORKER_RESERVATION_EXPIRED',
                'A selected worker reservation expired before the website check completed.')


@asynccontextmanager
async def reserve_preflight_runners(runner_ids, owner):
    """Reserve every selected idle worker atomically for one SQL-backed preflight."""
    from app.network_guard import require_connection
    try:
        await require_connection()
    except ValueError as error:
        if str(error).startswith('NETWORK_PAUSED:'):
            raise PreflightUnavailable(None, 'NETWORK_OFFLINE', str(error)) from error
        raise

    ids = list(dict.fromkeys(runner_ids))
    token = str(uuid4())
    unavailable = None
    async with engine.begin() as connection:
        rows = (await connection.execute(select(db.runners).where(
            db.runners.c.id.in_(ids)).order_by(db.runners.c.id).with_for_update())).mappings().all()
        by_id = {row['id']: row for row in rows}
        for runner_id in ids:
            row = by_id.get(runner_id)
            if not row:
                unavailable = PreflightUnavailable(runner_id, 'WORKER_NOT_REGISTERED',
                    f'{runner_id} is not connected to the worker pool yet.')
                break
            payload = row['payload'] or {}
            if not row['connected'] or not row['socket_id'] or payload.get('status') == 'RECONNECTING':
                unavailable = PreflightUnavailable(runner_id, 'WORKER_OFFLINE',
                    f'{runner_id} is reconnecting. The website check will retry when it is online.')
                break
            if row['current_job_id']:
                unavailable = PreflightUnavailable(runner_id, 'WORKER_BUSY',
                    f'{runner_id} is finishing a report. The website check will retry when it is idle.')
                break
            lease = await connection.scalar(select(db.runner_planning_leases.c.expires_at).where(
                db.runner_planning_leases.c.runner_id == runner_id).with_for_update())
            if lease and lease > now():
                unavailable = PreflightUnavailable(runner_id, 'WORKER_BUSY',
                    f'{runner_id} is already preparing filter options. The website check will retry when it is idle.')
                break

        if unavailable is None:
            expires_at = now() + timedelta(seconds=180)
            await connection.execute(pg_insert(db.runner_planning_leases).values([
                {'runner_id': runner_id, 'owner_username': owner, 'token': token, 'expires_at': expires_at}
                for runner_id in ids
            ]).on_conflict_do_update(index_elements=[db.runner_planning_leases.c.runner_id], set_={
                'token': token, 'owner_username': owner, 'expires_at': expires_at,
            }))
            reserved = {runner_id: by_id[runner_id]['socket_id'] for runner_id in ids}

    if unavailable:
        raise unavailable

    renewal_error = []
    async def renew_until_done():
        while True:
            await asyncio.sleep(25)
            try:
                await _renew_preflight_leases(ids, token)
            except Exception as error:
                renewal_error.append(error)
                return

    renewal = asyncio.create_task(renew_until_done())
    release = True
    try:
        yield {runner_id: (socket_id, token) for runner_id, socket_id in reserved.items()}
        if renewal_error:
            raise renewal_error[0]
    except asyncio.CancelledError:
        # The isolated browser checks may still be running. Keep the leases until
        # their crash-safe expiry so a scheduler cannot claim those workers early.
        release = False
        raise
    finally:
        renewal.cancel()
        try:
            await renewal
        except asyncio.CancelledError:
            pass
        if release:
            async with engine.begin() as connection:
                await connection.execute(delete(db.runner_planning_leases).where(
                    db.runner_planning_leases.c.runner_id.in_(ids),
                    db.runner_planning_leases.c.token == token))


@asynccontextmanager
async def reserve_options_runner(runner_id, owner):
    from app.network_guard import require_connection
    await require_connection()
    token = str(uuid4())
    async with engine.begin() as connection:
        runner = (await connection.execute(select(db.runners).where(db.runners.c.id == runner_id)
            .with_for_update())).mappings().first()
        if not runner:
            raise PreflightUnavailable(runner_id,'WORKER_NOT_REGISTERED','The selected worker is not registered. Filter options will retry when it is available.')
        if not runner['connected'] or not runner['socket_id']:
            raise PreflightUnavailable(runner_id,'WORKER_OFFLINE','The selected worker is reconnecting. Filter options will retry when it is online.')
        if runner['current_job_id']:
            raise PreflightUnavailable(runner_id,'WORKER_BUSY','The selected worker is finishing a report. Filter options will retry when it is idle.')
        lease = await connection.scalar(select(db.runner_planning_leases.c.expires_at).where(
            db.runner_planning_leases.c.runner_id == runner_id))
        if lease and lease > now():
            raise PreflightUnavailable(runner_id,'WORKER_BUSY','This worker is preparing filter options. Filter options will retry when it is idle.')
        await connection.execute(pg_insert(db.runner_planning_leases).values(
            runner_id=runner_id, owner_username=owner, token=token, expires_at=now() + timedelta(seconds=180))
            .on_conflict_do_update(index_elements=[db.runner_planning_leases.c.runner_id],
                                  set_={'token': token, 'owner_username': owner, 'expires_at': now() + timedelta(seconds=180)}))
        socket_id = runner['socket_id']
    release = True
    try:
        yield socket_id, token
    except asyncio.CancelledError:
        from app.realtime.server import sio
        try:
            result = await sio.call('runner:cancel-options', {'requestId': token}, to=socket_id, namespace='/runner', timeout=10)
            release = isinstance(result, dict) and bool(result.get('ok'))
        except Exception:
            release = False  # Crash-safe expiry protects an options operation whose cancellation was not acknowledged.
        raise
    finally:
        if release:
            async with engine.begin() as connection:
                await connection.execute(delete(db.runner_planning_leases).where(
                    db.runner_planning_leases.c.runner_id == runner_id, db.runner_planning_leases.c.token == token))
