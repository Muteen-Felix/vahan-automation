from fastapi import APIRouter, Query, Request, HTTPException
from fastapi.responses import FileResponse
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
async def annual_reports(request: Request, year: int = Query(2026, ge=1900, le=9999),
                         dataset: str = '', state: str = Query('', max_length=200),
                         rto: str = Query('', max_length=200), offset: int = Query(0, ge=0),
                         limit: int = Query(100, ge=1, le=500)):
    from app.db.read_cache import summary_read
    role = getattr(request.state, 'authenticated_role', 'user')
    key = ('annual',role,year,dataset,state.strip(),rto.strip(),offset,limit)
    return await summary_read(key,lambda:_annual_report_rows(request,year,dataset,state,rto,offset,limit))



async def _annual_report_rows(request: Request, year: int = Query(2026, ge=1900, le=9999),
                         dataset: str = '', state: str = Query('', max_length=200),
                         rto: str = Query('', max_length=200), offset: int = Query(0, ge=0),
                         limit: int = Query(100, ge=1, le=500)):
    records = db.main_reports
    async with engine.connect() as connection:
        connection = await connection.execution_options(isolation_level='REPEATABLE READ')
        selected, datasets = await select_scope(connection, request, dataset)
        years = list(await connection.scalars(select(records.c.year)
            .where(records.c.scope_key == selected, records.c.year >= 1900)
            .distinct().order_by(records.c.year.desc())))
        conditions = report_conditions(request, selected, year, state, rto)
        aggregates = (await connection.execute(select(func.count().label('rows'),
            func.count(func.distinct(records.c.maker)).label('makers'),
            func.count(func.distinct(records.c.state + '|' + records.c.rto + '|' + records.c.rto_code)).label('offices'),
            func.max(records.c.updated_at).label('updatedAt'),
            *[func.bool_or(records.c[m].is_not(None)).label(m) for m in db.MONTH_COLUMNS],
        ).select_from(records).where(*conditions))).mappings().one()
        summary = {key: aggregates[key] for key in ('rows', 'makers', 'offices', 'updatedAt')}
        options = [records.c.scope_key == selected, records.c.year == year]
        states = list(await connection.scalars(select(records.c.state)
            .where(*options).distinct().order_by(records.c.state)))
        rtos = list(await connection.scalars(select((records.c.rto + ' ' + records.c.rto_code).label('name'))
            .where(*options).distinct().order_by('name')))
        rows = (await connection.execute(select(*[records.c[key] for key in
            ('id', 'state', 'rto', 'rto_code', 'maker', 'year', 'created_at', 'updated_at', *db.MONTH_COLUMNS)]).where(*conditions)
            .order_by(*report_order())
            .offset(offset).limit(limit))).mappings().all()
        ledger = db.report_update_history
        saved_conditions = [ledger.c.scope_key == selected, cast(ledger.c.years, JSONB).contains([year])]
        if state.strip():
            saved_conditions.append(cast(ledger.c.states, String).ilike(like(state), escape='\\'))
        if rto.strip():
            saved_conditions.append(cast(ledger.c.rtos, String).ilike(like(rto), escape='\\'))
        latest = (await connection.execute(select(ledger).where(*saved_conditions)
            .order_by(ledger.c.imported_at.desc(), ledger.c.source_key).limit(1))).mappings().first()
    return {'year': year, 'datasetId': selected, 'datasets': [dict(d) for d in datasets],
            'years': years, 'states': states, 'rtos': rtos, 'summary': dict(summary),
            'coverage': [i for i, m in enumerate(db.MONTH_COLUMNS, 1) if aggregates[m]],
            'lastSaved': saved_report_summary(latest) if latest else None,
            'offset': offset, 'limit': limit, 'rows': [{k: r[k] for k in
                ('id', 'state', 'rto', 'rto_code', 'maker', 'year', 'created_at', 'updated_at')} | {
                    'months': [r[m] for m in db.MONTH_COLUMNS]} for r in rows]}



@router.get('/history')
async def annual_history(request: Request, year: int = Query(2026, ge=1900, le=9999), dataset: str = '',
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


class TemporaryWorkbookResponse(FileResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            from pathlib import Path
            Path(self.path).unlink(missing_ok=True)


@router.get('/export')
async def export_annual_reports(request: Request, year: int = Query(2026, ge=1900, le=9999),
                                dataset: str = '', state: str = Query('', max_length=200),
                                rto: str = Query('', max_length=200),
                                confirm_all: bool = Query(False, alias='confirmAll')):
    if not state.strip() and not rto.strip() and not confirm_all:
        raise HTTPException(409, 'Confirm exporting the entire table before downloading Excel.')
    from app.db.pressure import bulk_operation
    from app.config import settings
    from app.security_limits import consume
    await consume('export:global', 4, 60)
    await consume(f'export:{request.state.authenticated_user}', 2, 60)
    from app.repositories.annual_export import WorkbookWriter
    from pathlib import Path
    import os, tempfile
    records = db.main_reports
    writer, path = None, None
    async with bulk_operation():
        try:
            async with engine.connect() as raw:
                connection = await raw.execution_options(isolation_level='REPEATABLE READ')
                async with connection.begin():
                    from sqlalchemy import text
                    await connection.execute(text('SET TRANSACTION READ ONLY'))
                    selected, _ = await select_scope(connection, request, dataset)
                    conditions = report_conditions(request, selected, year, state, rto)
                    stats = (await connection.execute(select(func.count().label('rows'),
                        func.count(func.distinct(func.row(records.c.state, records.c.rto, records.c.rto_code))).label('offices'),
                        func.count(func.distinct(records.c.state)).label('states'),
                        func.min(records.c.state).label('state'), func.min(records.c.rto).label('rto'),
                        func.min(records.c.rto_code).label('code')).where(*conditions))).mappings().one()
                    count = stats['rows']
                    if not count:
                        raise HTTPException(404, 'No manufacturer rows match these filters.')
                    if count > min(1_048_573, settings.max_export_rows):
                        raise HTTPException(413, f'The report exceeds {settings.max_export_rows:,} rows. Narrow the State/RTO search.')
                    title_state = stats['state'] if stats['states'] == 1 else ('Multiple States' if state or rto else 'All States')
                    office = stats['rto'] + (' - ' + stats['code'] if stats['code'] else '') if stats['offices'] == 1 else ('Selected RTOs' if rto else 'All RTOs')
                    writer = WorkbookWriter(f'Maker Month Wise Data of {office}, {title_state} ({year})', year, count)
                    query = select(records.c.state,records.c.rto,records.c.rto_code,records.c.maker,
                        *[records.c[m] for m in db.MONTH_COLUMNS]).where(*conditions).order_by(*report_order())
                    async with connection.stream(query) as result:
                        stream = result.mappings()
                        while batch := await stream.fetchmany(1000):
                            await run_in_threadpool(writer.append, batch)
            # Release the DB connection before compressing the XLSX.
            descriptor, path = tempfile.mkstemp(prefix='vahan-export-', suffix='.xlsx')
            os.close(descriptor)
            await run_in_threadpool(writer.save, path)
            return TemporaryWorkbookResponse(path, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(writer.filename,safe=''),
                         'X-Report-Row-Count':str(count),'Cache-Control':'private, no-store'})
        except BaseException:
            if path:Path(path).unlink(missing_ok=True)
            if writer:writer.abort()
            raise
