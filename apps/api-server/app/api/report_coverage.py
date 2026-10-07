"""Coverage is proven by imported report data, never by attempted-job counts."""
from datetime import datetime
import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import cast, func, literal, select
from sqlalchemy.dialects.postgresql import JSONB

from app.db import engine, schema as db
from app.repositories.annual_reports import clean, context_year, dataset

router = APIRouter(prefix='/annual-reports', tags=['annual-reports'])
TERMINAL = {'COMPLETED', 'NO_DATA', 'FAILED', 'CANCELLED'}


class PlannedReport(BaseModel):
    name: str = Field(max_length=1000)
    filters: dict


class CoverageQuery(BaseModel):
    year: int = Field(ge=1900, le=9999)
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
        # Coverage needs filters and committed evidence, not browser images,
        # verification proofs or every historical attempt's full job payload.
        # Reduce repeated imports in SQL before decoding JSON in the API loop.
        empty_warnings = literal([], type_=JSONB)
        imports = (await connection.execute(select(
            db.jobs.c.filters,
            func.max(ledger.c.imported_at).label('imported_at'),
            func.bool_or(ledger.c.status != 'no-data').label('with_data'),
        ).select_from(ledger.join(db.jobs, ledger.c.job_id == db.jobs.c.id)).where(
            ledger.c.scope_key == selected,
            cast(ledger.c.years, JSONB).contains([command.year]),
            ledger.c.status.in_(['added', 'updated', 'unchanged', 'no-data']),
            func.coalesce(ledger.c.details['issueCount'].as_integer(), 0) == 0,
            func.coalesce(ledger.c.details['warnings'], empty_warnings) == empty_warnings,
            (ledger.c.status == 'no-data')
            | (func.coalesce(ledger.c.details['newCells'].as_integer(), 0) > 0)
            | (func.coalesce(ledger.c.details['duplicates'].as_integer(), 0) > 0)
            | (func.coalesce(ledger.c.details['replacedCells'].as_integer(), 0) > 0),
        ).group_by(db.jobs.c.filters))).mappings().all()
        active = await connection.scalar(select(db.jobs.c.id).where(
            db.jobs.c.owner_username == username, db.jobs.c.status.not_in(TERMINAL)).limit(1))
    planned, seen = [], set()
    for index, scenario in enumerate(command.scenarios):
        key = office(scenario.filters)
        if not key or context_year(scenario.filters) != command.year:
            raise HTTPException(400, 'Each report must select one State, one RTO and the requested year.')
        identity = filter_key(scenario.filters)
        if identity in seen:
            raise HTTPException(400, 'The office list contains duplicate filter combinations.')
        seen.add(identity)
        if dataset(username, scenario.filters)['id'] != selected:
            continue
        if command.state.strip().upper() not in key[0] or command.rto.strip().upper() not in key[1]:
            continue
        planned.append((index, scenario, normalized(scenario.filters)))
    successful = {}
    for item in imports:
        key = filter_key(item['filters'])
        previous = successful.get(key)
        # Existing saved values remain covered even if a later attempt fails or returns no data.
        latest_item = previous[0] if previous and previous[0]['imported_at'] > item['imported_at'] else item
        successful[key] = (latest_item, bool(previous and previous[1]) or item['with_data'])
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
    compatible = bool(planned) and all(
        dataset(username, scenario.filters)['id'] == selected for _, scenario, _ in planned)
    can_continue = compatible and command.year <= datetime.now().year and not active
    reason = ('A report is already running for this account.' if active else
              'Future report years cannot be crawled.' if command.year > datetime.now().year else
              'These report filters do not match the State–RTO matrix.' if not compatible else '')
    missing_set = set(missing)
    first_missing = next((describe(i, scenario) for i, scenario, _ in planned if i in missing_set), None)
    return {'year': command.year, 'datasetId': selected, 'total': len(planned), 'covered': len(covered),
            'withData': with_data, 'noData': no_data, 'missing': len(missing), 'missingIndices': missing,
            'coveredThrough': through, 'firstMissing': first_missing, 'lastSaved': latest,
            'canContinue': can_continue, 'blockedReason': reason, 'matrixLoaded': bool(command.scenarios)}
