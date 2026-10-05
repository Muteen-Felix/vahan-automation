from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select

from app.access import require_owner
from app.db import engine, schema as db

router = APIRouter(prefix='/maker-updates', tags=['maker-updates'])


def _run(row):
    return {'id': row['id'], 'year': row['year'], 'status': row['status'],
        'changedMakers': row['changed_makers'], 'states': row['states'],
        'createdAt': row['created_at'].isoformat(), 'updatedAt': row['updated_at'].isoformat()}


@router.get('')
async def latest_update(request: Request, year: int = Query(ge=2026, le=9999)):
    async with engine.connect() as connection:
        rows = (await connection.execute(select(db.maker_update_runs).where(
            db.maker_update_runs.c.year == year,
            db.maker_update_runs.c.owner_username == request.state.authenticated_user)
            .order_by(db.maker_update_runs.c.created_at.desc()).limit(20))).mappings().all()
    return [_run(row) for row in rows]


@router.get('/{run_id}')
async def get_update(run_id: UUID, request: Request):
    async with engine.connect() as connection:
        run = (await connection.execute(select(db.maker_update_runs).where(
            db.maker_update_runs.c.id == str(run_id)))).mappings().first()
        if not run:
            raise HTTPException(404, 'Maker update run not found.')
        require_owner(request, run['owner_username'])
        tasks = (await connection.execute(select(db.maker_update_tasks).where(
            db.maker_update_tasks.c.run_id == str(run_id)).order_by(
                db.maker_update_tasks.c.kind, db.maker_update_tasks.c.maker,
                db.maker_update_tasks.c.state, db.maker_update_tasks.c.rto))).mappings().all()
        locations = (await connection.execute(select(
            db.maker_office_index.c.maker,
            func.count(func.distinct(db.maker_office_index.c.state)).label('state_count'),
            func.count().label('rto_count')).where(
                db.maker_office_index.c.scope_key == run['scope_key'],
                db.maker_office_index.c.year == run['year']).group_by(
                    db.maker_office_index.c.maker))).mappings().all()
    return _run(run) | {
        'tasks': [{'id': task['id'], 'kind': task['kind'], 'maker': task['maker'],
            'state': task['state'], 'rto': task['rto'], 'status': task['status'],
            'jobId': task['job_id'], 'error': task['error']} for task in tasks],
        'locations': [{'maker': row['maker'], 'states': row['state_count'],
            'rtos': row['rto_count']} for row in locations],
    }
