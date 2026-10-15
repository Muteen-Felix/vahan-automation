"""Progress for the latest report update run, independent of saved month cells."""
import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select

from app.db import engine, schema as db
from app.repositories.annual_reports import clean, context_year, dataset
from app.repositories.run_history import run_details

router = APIRouter(prefix='/annual-reports', tags=['annual-reports'])


class PlannedReport(BaseModel):
    name: str = Field(max_length=1000)
    filters: dict


class CoverageQuery(BaseModel):
    year: int = Field(ge=1900, le=9999)
    dataset: str = Field(default='', max_length=64)
    state: str = Field(default='', max_length=200)
    rto: str = Field(default='', max_length=200)
    scenarios: list[PlannedReport]


def has_office(filters):
    states, rtos = filters.get('states'), filters.get('rtos')
    return (isinstance(states, list) and len(states) == 1 and isinstance(states[0], str) and states[0].strip()
            and isinstance(rtos, list) and len(rtos) == 1 and isinstance(rtos[0], str) and rtos[0].strip())


def normalized(filters):
    return {key: sorted({clean(item).upper() for item in value}) if isinstance(value, list)
            else clean(value).upper() for key, value in filters.items()
            if key not in {'autoApply', 'autoExport'} and value not in (None, '', [])}


def filter_key(filters):
    return json.dumps(normalized(filters), sort_keys=True)


def empty_progress(year, dataset_id, matrix_loaded):
    return {'year': year, 'datasetId': dataset_id, 'hasRun': False, 'matrixLoaded': matrix_loaded,
            'total': 0, 'processed': 0, 'withData': 0, 'noData': 0, 'failed': 0,
            'pending': 0, 'running': 0, 'status': 'NO_RUN', 'startedAt': None, 'lastActivityAt': None}


@router.post('/coverage')
async def report_coverage(command: CoverageQuery, request: Request):
    username = request.state.authenticated_user
    own_scope = dataset(username, command.scenarios[0].filters) if command.scenarios else None
    selected = command.dataset or (own_scope['id'] if own_scope else '')
    matrix_loaded = bool(command.scenarios)
    sessions, tasks = db.batch_queue_sessions, db.batch_queue_tasks

    if command.dataset:
        async with engine.connect() as connection:
            scope = await connection.scalar(select(db.report_update_history.c.scope_key)
                .where(db.report_update_history.c.scope_key == selected).limit(1))
            if not scope:
                scope = await connection.scalar(select(db.main_reports.c.scope_key)
                    .where(db.main_reports.c.scope_key == selected).limit(1))
            if not scope:
                raise HTTPException(404, 'Report filters not found.')

    for scenario in command.scenarios:
        if not has_office(scenario.filters) or context_year(scenario.filters) != command.year:
            raise HTTPException(400, 'Each report must select one State, one RTO and the requested year.')

    # Use queue cases for this year and report scope. Saved monthly cells never
    # contribute to the progress value.
    has_year = select(tasks.c.position).where(tasks.c.session_id == sessions.c.session_id,
        tasks.c.filters['fromYear'].as_string() == str(command.year),
        tasks.c.filters['toYear'].as_string() == str(command.year)).exists()

    async with engine.connect() as connection:
        candidates = (await connection.execute(select(
            sessions.c.session_id, sessions.c.created_at,
        ).where(has_year).order_by(case((sessions.c.status == 'RUNNING', 0),
                        (sessions.c.status == 'PAUSED', 1),
                        (sessions.c.status == 'STOPPED', 2), else_=3),
                   sessions.c.updated_at.desc(), sessions.c.created_at.desc()).limit(1000))).mappings().all()

        for candidate in candidates:
            task_rows = (await connection.execute(select(tasks.c.filters, tasks.c.status).where(
                tasks.c.session_id == candidate['session_id'],
                tasks.c.filters['fromYear'].as_string() == str(command.year),
                tasks.c.filters['toYear'].as_string() == str(command.year)))).mappings().all()
            scoped_tasks = [row for row in task_rows if dataset(username, row['filters'])['id'] == selected]
            if not scoped_tasks:
                continue
            progress = (await run_details(connection, [candidate['session_id']])).get(candidate['session_id'])
            if not progress:
                continue
            counts = {status: sum(row['status'] == status for row in scoped_tasks)
                for status in ('COMPLETED', 'NO_DATA', 'FAILED', 'PENDING', 'PROCESSING')}
            processed = counts['COMPLETED'] + counts['NO_DATA'] + counts['FAILED']
            return {'year': command.year, 'datasetId': selected, 'hasRun': True,
                'matrixLoaded': matrix_loaded, 'total': len(scoped_tasks), 'processed': processed,
                'withData': counts['COMPLETED'], 'noData': counts['NO_DATA'],
                'failed': counts['FAILED'], 'pending': counts['PENDING'], 'running': counts['PROCESSING'],
                'status': progress['status'], 'startedAt': candidate['created_at'].isoformat(),
                'lastActivityAt': progress['lastActivityAt']}

    return empty_progress(command.year, selected, matrix_loaded)
