"""Coverage is proven by imported report data, never by attempted-job counts."""
from datetime import datetime
import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db import engine, schema as db
from app.repositories.annual_reports import clean, context_year, dataset

router = APIRouter(prefix='/annual-reports', tags=['annual-reports'])
TERMINAL = {'COMPLETED', 'NO_DATA', 'FAILED', 'CANCELLED'}


class PlannedReport(BaseModel):
    name: str = Field(max_length=1000)
    filters: dict


class CoverageQuery(BaseModel):
    year: int = Field(ge=2026, le=9999)
    dataset: str = Field(default='', max_length=64)
    state: str = Field(default='', max_length=200)
    rto: str = Field(default='', max_length=200)
    scenarios: list[PlannedReport] = Field(max_length=5000)


def normalized(filters):
    return {key: sorted({clean(item).upper() for item in value}) if isinstance(value, list)
            else clean(value).upper() for key, value in filters.items()
            if key not in {'autoApply', 'autoExport'} and value not in (None, '', [])}


def filter_key(filters):
    return json.dumps(normalized(filters), sort_keys=True)


def office(filters):
    states, rtos = filters.get('states', []), filters.get('rtos', [])
    if len(states) != 1 or len(rtos) != 1:
        return None
    return clean(states[0]).upper(), clean(rtos[0]).upper()


def describe(index, scenario):
    return {'index': index, 'state': scenario.filters['states'][0],
            'rto': scenario.filters['rtos'][0], 'name': scenario.name}


@router.post('/coverage')
async def report_coverage(command: CoverageQuery, request: Request):
    username = request.state.authenticated_user
    own_scope = dataset(username, command.scenarios[0].filters) if command.scenarios else None
    selected = command.dataset or (own_scope['id'] if own_scope else '')
    ledger = db.report_update_history
    async with engine.connect() as connection:
        scope = await connection.scalar(select(ledger.c.scope_key)
            .where(ledger.c.scope_key == selected).limit(1))
        if command.dataset and not scope:
            scope = await connection.scalar(select(db.main_reports.c.scope_key)
                .where(db.main_reports.c.scope_key == selected).limit(1))
            if not scope:
                raise HTTPException(404, 'Report filters not found.')
        # Shared coverage includes committed imports by every account. Job control
        # and the active-run guard remain attached to the requesting account.
        imports = (await connection.execute(select(ledger).where(ledger.c.scope_key == selected)
            .order_by(ledger.c.imported_at, ledger.c.source_key))).mappings().all()
        job_ids = [item['job_id'] for item in imports if item['job_id']]
        jobs = (await connection.execute(select(db.jobs).where(db.jobs.c.id.in_(job_ids))
            .order_by(db.jobs.c.created_at, db.jobs.c.id))).mappings().all()
        active = await connection.scalar(select(db.jobs.c.id).where(
            db.jobs.c.owner_username == username, db.jobs.c.status.not_in(TERMINAL)).limit(1))
    job_by_id = {job['id']: job for job in jobs}
    planned, seen = [], set()
    for index, scenario in enumerate(command.scenarios):
        key = office(scenario.filters)
        if not key or context_year(scenario.filters) != command.year:
            raise HTTPException(400, 'Each report must select one State, one RTO and the requested year.')
        if key in seen:
            raise HTTPException(400, 'The office list contains duplicate reports.')
        seen.add(key)
        if command.state.strip().upper() not in key[0] or command.rto.strip().upper() not in key[1]:
            continue
        planned.append((index, scenario, normalized(scenario.filters)))
    successful = {}
    for item in imports:
        job = job_by_id.get(item['job_id'])
        if not job or command.year not in item['years'] or item['status'] not in {'added', 'unchanged', 'no-data'}:
            continue
        details = item['details']
        if details.get('issueCount') or details.get('warnings'):
            continue
        if item['status'] != 'no-data' and not any(details.get(k, 0) for k in ('newCells', 'duplicates')):
            continue
        key = filter_key(job['filters'])
        previous = successful.get(key)
        # Existing saved values remain covered even if a later attempt fails or returns no data.
        successful[key] = (item, bool(previous and previous[1]) or item['status'] != 'no-data')
    covered, missing, with_data, no_data, through = [], [], 0, 0, 0
    gap = False
    latest = None
    for index, scenario, filters in planned:
        evidence = successful.get(filter_key(filters))
        if evidence:
            covered.append(index)
            with_data += int(evidence[1])
            no_data += int(not evidence[1])
            if not gap:
                through += 1
            item = evidence[0]
            if latest is None or item['imported_at'] > latest['savedAt']:
                latest = describe(index, scenario) | {'savedAt': item['imported_at']}
        else:
            gap = True
            missing.append(index)
    compatible = bool(own_scope) and selected == own_scope['id'] and all(
        dataset(username, scenario.filters)['id'] == selected for _, scenario, _ in planned)
    can_continue = compatible and command.year == datetime.now().year and not active
    reason = ('A report is already running for this account.' if active else
              'Run continuation is available for the current calendar year only.' if command.year != datetime.now().year else
              'These report filters do not match the State–RTO matrix.' if not compatible else '')
    missing_set = set(missing)
    first_missing = next((describe(i, scenario) for i, scenario, _ in planned if i in missing_set), None)
    return {'year': command.year, 'datasetId': selected, 'total': len(planned), 'covered': len(covered),
            'withData': with_data, 'noData': no_data, 'missing': len(missing), 'missingIndices': missing,
            'coveredThrough': through, 'firstMissing': first_missing, 'lastSaved': latest,
            'canContinue': can_continue, 'blockedReason': reason, 'matrixLoaded': bool(command.scenarios)}
