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
            raise ValueError('The options reservation expired. Retry the preview.')


@asynccontextmanager
async def reserve_options_runner(runner_id, owner):
    token = str(uuid4())
    async with engine.begin() as connection:
        runner = (await connection.execute(select(db.runners).where(db.runners.c.id == runner_id)
            .with_for_update())).mappings().first()
        if not runner or not runner['connected'] or runner['current_job_id'] or not runner['socket_id']:
            raise ValueError('Choose an online, idle worker to load filter options.')
        lease = await connection.scalar(select(db.runner_planning_leases.c.expires_at).where(
            db.runner_planning_leases.c.runner_id == runner_id))
        if lease and lease > now():
            raise ValueError('This worker is preparing another filter preview. Try another idle worker.')
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
