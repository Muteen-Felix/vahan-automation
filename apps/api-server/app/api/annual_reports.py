from fastapi import APIRouter, Query, Request, HTTPException
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from urllib.parse import quote
from sqlalchemy import String, cast, func, select, union_all
from sqlalchemy.dialects.postgresql import JSONB
from app.db import engine, schema as db
from app.repositories.annual_reports import saved_report_summary

router = APIRouter(prefix='/annual-reports', tags=['annual-reports'])


def like(value):
    return '%' + value.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


async def select_scope(connection, request, dataset):
    records, ledger = db.main_reports, db.report_update_history
    scopes = union_all(
        select(records.c.scope_key.label('id'), records.c.scope_label.label('label'),
               func.count().label('size')).group_by(records.c.scope_key, records.c.scope_label),
        select(ledger.c.scope_key.label('id'), ledger.c.scope_label.label('label'),
               func.count().filter(False).label('size')).group_by(ledger.c.scope_key, ledger.c.scope_label)).subquery()
    datasets = (await connection.execute(select(scopes.c.id, func.min(scopes.c.label).label('label'))
        .group_by(scopes.c.id)
        .order_by(func.sum(scopes.c.size).desc(), func.min(scopes.c.label)))).mappings().all()
    valid_ids = {d['id'] for d in datasets}
    selected = dataset if dataset in valid_ids else (datasets[0]['id'] if datasets and not dataset else '')
    return selected, datasets


def report_conditions(request, dataset, year, state, rto):
    records = db.main_reports
    conditions = [records.c.scope_key == dataset, records.c.year == year]
    if state.strip():
        conditions.append(records.c.state.ilike(like(state), escape='\\'))
    if rto.strip():
        conditions.append((records.c.rto + ' ' + records.c.rto_code).ilike(like(rto), escape='\\'))
    return conditions


def report_order():
    records = db.main_reports
    return (func.lower(records.c.state), func.lower(records.c.rto), func.lower(records.c.maker), records.c.id)


@router.get('')
async def annual_reports(request: Request, year: int = Query(2026, ge=2026, le=9999),
                         dataset: str = '', state: str = Query('', max_length=200),
                         rto: str = Query('', max_length=200), offset: int = Query(0, ge=0),
                         limit: int = Query(100, ge=1, le=500)):
    records = db.main_reports
    async with engine.connect() as connection:
        selected, datasets = await select_scope(connection, request, dataset)
        years = list(await connection.scalars(select(records.c.year)
            .where(records.c.year >= 2026).distinct().order_by(records.c.year)))
        conditions = report_conditions(request, selected, year, state, rto)
        summary = (await connection.execute(select(func.count().label('rows'),
            func.count(func.distinct(records.c.maker)).label('makers'),
            func.count(func.distinct(records.c.state + '|' + records.c.rto + '|' + records.c.rto_code)).label('offices'),
            func.max(records.c.updated_at).label('updatedAt')).select_from(records).where(*conditions))).mappings().one()
        options = [records.c.scope_key == selected, records.c.year == year]
        states = list(await connection.scalars(select(records.c.state)
            .where(*options).distinct().order_by(records.c.state)))
        rtos = list(await connection.scalars(select((records.c.rto + ' ' + records.c.rto_code).label('name'))
            .where(*options).distinct().order_by('name')))
        rows = (await connection.execute(select(records).where(*conditions)
            .order_by(*report_order())
            .offset(offset).limit(limit))).mappings().all()
        populated = (await connection.execute(select(*[func.bool_or(records.c[m].is_not(None)).label(m)
            for m in db.MONTH_COLUMNS]).where(*conditions))).mappings().one()
        ledger = db.report_update_history
        saved_conditions = [ledger.c.scope_key == selected, cast(ledger.c.years, JSONB).contains([year])]
        if state.strip():
            saved_conditions.append(cast(ledger.c.states, String).ilike(like(state), escape='\\'))
        if rto.strip():
            saved_conditions.append(cast(ledger.c.rtos, String).ilike(like(rto), escape='\\'))
        latest = (await connection.execute(select(ledger).where(*saved_conditions)
            .order_by(ledger.c.imported_at.desc(), ledger.c.source_key).limit(1))).mappings().first()
    return {'year': year, 'datasetId': selected, 'datasets': [dict(d) for d in datasets],
            'years': years or [2026], 'states': states, 'rtos': rtos, 'summary': dict(summary),
            'coverage': [i for i, m in enumerate(db.MONTH_COLUMNS, 1) if populated[m]],
            'lastSaved': saved_report_summary(latest) if latest else None,
            'offset': offset, 'limit': limit, 'rows': [{k: r[k] for k in
                ('id', 'state', 'rto', 'rto_code', 'maker', 'year', 'created_at', 'updated_at')} | {
                    'months': [r[m] for m in db.MONTH_COLUMNS]} for r in rows]}


@router.get('/history')
async def annual_history(request: Request, year: int = Query(2026, ge=2026, le=9999), dataset: str = '',
                         state: str = Query('', max_length=200), rto: str = Query('', max_length=200),
                         offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    ledger = db.report_update_history
    conditions = [cast(ledger.c.years, JSONB).contains([year])]
    if dataset:
        conditions.append(ledger.c.scope_key == dataset)
    if state.strip():
        conditions.append(cast(ledger.c.states, String).ilike(like(state), escape='\\'))
    if rto.strip():
        conditions.append(cast(ledger.c.rtos, String).ilike(like(rto), escape='\\'))
    query = select(ledger).where(*conditions)
    async with engine.connect() as connection:
        total = await connection.scalar(select(func.count()).select_from(query.subquery()))
        rows = (await connection.execute(query.order_by(ledger.c.imported_at.desc(), ledger.c.source_key)
            .offset(offset).limit(limit))).mappings().all()
    return {'total': total, 'offset': offset, 'limit': limit, 'rows': [dict(r) for r in rows]}


@router.get('/export')
async def export_annual_reports(request: Request, year: int = Query(2026, ge=2026, le=9999),
                                dataset: str = '', state: str = Query('', max_length=200),
                                rto: str = Query('', max_length=200),
                                confirm_all: bool = Query(False, alias='confirmAll')):
    if not state.strip() and not rto.strip() and not confirm_all:
        raise HTTPException(409, 'Confirm exporting the entire table before downloading Excel.')
    records = db.main_reports
    async with engine.connect() as connection:
        selected, _ = await select_scope(connection, request, dataset)
        # No pagination: one SQL statement supplies every matching row, with the UI's ordering.
        rows = (await connection.execute(select(records.c.state, records.c.rto, records.c.rto_code,
            records.c.maker, *[records.c[m] for m in db.MONTH_COLUMNS])
            .where(*report_conditions(request, selected, year, state, rto))
            .order_by(*report_order()).limit(1_048_574))).mappings().all()
    if not rows:
        raise HTTPException(404, 'No manufacturer rows match these filters.')
    if len(rows) > 1_048_573:
        raise HTTPException(413, 'The report exceeds the Excel worksheet limit. Narrow the State/RTO search.')
    from app.repositories.annual_export import build_workbook
    content, filename = await run_in_threadpool(build_workbook, rows, year, state.strip(), rto.strip())
    return Response(content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe=''),
                 'X-Report-Row-Count': str(len(rows)), 'Cache-Control': 'private, no-store'})
