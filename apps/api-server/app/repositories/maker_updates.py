"""Incremental Maker snapshots, office discovery and focused report updates."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import schema as db
from app.models.job import UpdateKind
from app.repositories.annual_reports import clean, context_year, dataset, digest, month_column, number, split_rto


def _values(row):
    return tuple(row.get(month) for month in db.MONTH_COLUMNS)


def _month_values(months):
    return {name: months.get(index) for index, name in enumerate(db.MONTH_COLUMNS, 1)}


def parse_summary(rows, year, axis):
    """Fail closed on partial/ambiguous workbooks; preserve blank versus zero."""
    if axis not in ('maker', 'rto') or not year:
        raise ValueError('A single calendar year and a known report axis are required.')
    headers, entries, problems = {}, {}, []
    for row in rows:
        sheet, cells = row.get('sheet', 'Report'), row['cells']
        labels = [''.join(ch for ch in clean(v).lower() if ch.isalnum()) for v in cells]
        names = ('maker', 'manufacturer', 'manufacturername') if axis == 'maker' else (
            'rto', 'rtowise', 'rtoname', 'registeringauthority', 'registeringauthorityname')
        name_col = next((i for i, label in enumerate(labels) if label in names), None)
        columns = {i: parsed for i, value in enumerate(cells) if (parsed := month_column(value, year))}
        if name_col is not None and columns:
            if any(cell_year != year for cell_year, _ in columns.values()):
                problems.append(f'{sheet}:{row["row_number"]}: workbook contains another year.')
            total_col = next((i for i, label in enumerate(labels) if label == 'total'), None)
            headers[sheet] = (name_col, columns, total_col)
            continue
        if sheet not in headers:
            continue
        name_col, columns, total_col = headers[sheet]
        get = lambda index: cells[index] if index is not None and index < len(cells) else None
        label = clean(get(name_col))
        if not label or label.casefold() in ('total', 'grand total', 'page total', 'no record found'):
            continue
        if label.casefold() == 'others' and axis == 'maker':
            label = 'OTHERS'
        key = label.casefold()
        values = {}
        for index, (cell_year, month) in columns.items():
            if cell_year != year:
                continue
            try:
                values[month] = number(get(index))
            except ValueError:
                problems.append(f'{sheet}:{row["row_number"]}: invalid {label} month {month}.')
        if not any(value is not None for value in values.values()):
            continue
        if key in entries:
            problems.append(f'{sheet}:{row["row_number"]}: duplicate {axis} {label}.')
            continue
        try:
            total = number(get(total_col)) if total_col is not None else None
        except ValueError:
            problems.append(f'{sheet}:{row["row_number"]}: invalid total for {label}.')
            continue
        computed = sum(value or 0 for value in values.values())
        if total is not None and total != computed:
            problems.append(f'{sheet}:{row["row_number"]}: total differs from monthly values for {label}.')
        entries[key] = {'label': label, 'months': values, 'total': computed}
    if not headers:
        problems.append(f'No {axis}/month table was found.')
    if not entries:
        problems.append(f'No {axis} data rows were found.')
    if problems:
        raise ValueError('MAKER_UPDATE_PARSE_FAILED: ' + '; '.join(problems[:20]))
    return list(entries.values())


async def validate_update_job(connection, job):
    """Validate job metadata within the runner-assignment transaction."""
    kind = job.update_kind
    filters = job.filters.model_dump(mode='json', by_alias=True)
    if kind == UpdateKind.NORMAL:
        if job.update_run_id or job.update_task_id:
            raise ValueError('Ordinary jobs cannot reference a Maker update run.')
        return
    if kind == UpdateKind.GLOBAL:
        if job.update_run_id or job.update_task_id or len(set(filters.get('states', []))) < 30 or filters.get('rtos') or filters.get('makers'):
            raise ValueError('Global Maker scan requires all States and no RTO or Maker filter.')
        if filters.get('yAxis') != 'Maker' or filters.get('xAxis') != 'Month Wise' or not context_year(filters):
            raise ValueError('Global Maker scan requires Maker / Month Wise and one year.')
        scope = dataset(job.owner_username, filters)
        unfinished = await connection.scalar(select(db.maker_update_runs.c.id).where(
            db.maker_update_runs.c.scope_key == scope['id'], db.maker_update_runs.c.year == context_year(filters),
            db.maker_update_runs.c.status == 'RUNNING').limit(1))
        if unfinished:
            raise ValueError('Resume the unfinished Maker update before starting another scan.')
        return
    if not job.update_run_id or not job.update_task_id or len(filters.get('states', [])) != 1 or len(filters.get('makers', [])) != 1:
        raise ValueError('Focused Maker job requires its run, task, State and Maker.')
    task = (await connection.execute(select(db.maker_update_tasks).where(
        db.maker_update_tasks.c.id == job.update_task_id).with_for_update())).mappings().first()
    run = (await connection.execute(select(db.maker_update_runs).where(
        db.maker_update_runs.c.id == str(job.update_run_id)).with_for_update())).mappings().first()
    if not task or not run or task['run_id'] != str(job.update_run_id) or task['kind'] != kind.value:
        raise ValueError('Maker update task was not found in this run.')
    if run['status'] != 'RUNNING' or task['status'] not in ('PENDING', 'FAILED'):
        raise ValueError('Maker update task is not ready to run.')
    if run['owner_username'] != job.owner_username or run['scope_key'] != dataset(job.owner_username, filters)['id'] or run['year'] != context_year(filters):
        raise ValueError('Maker update filters do not match their run.')
    if filters['states'][0].casefold() != task['state'].casefold() or filters['makers'][0].casefold() != task['maker'].casefold():
        raise ValueError('Maker update State or Maker does not match its task.')
    if kind == UpdateKind.DISCOVER:
        if filters.get('rtos') or filters.get('yAxis') != 'RTO Wise' or filters.get('xAxis') != 'Month Wise':
            raise ValueError('Discovery needs RTO / Month Wise without an RTO selection.')
    elif (len(filters.get('rtos', [])) != 1 or filters['rtos'][0].casefold() != task['rto'].casefold()
          or filters.get('yAxis') != 'Maker' or filters.get('xAxis') != 'Month Wise'):
        raise ValueError('Refresh needs Maker / Month Wise for its exact RTO.')
    return task['id']


async def commit_global(connection, job, rows, checksum, observed_at):
    filters = job.filters.model_dump(mode='json', by_alias=True)
    scope, year = dataset(job.owner_username, filters), context_year(filters)
    parsed = parse_summary(rows, year, 'maker')
    previous = {row['maker'].casefold(): row for row in (await connection.execute(
        select(db.maker_global_reports).where(db.maker_global_reports.c.scope_key == scope['id'],
            db.maker_global_reports.c.year == year))).mappings()}
    current = {item['label'].casefold(): item for item in parsed}
    first_scan = not previous
    changed = sorted((current[key]['label'] if key in current else previous[key]['maker'])
        for key in previous.keys() | current.keys()
        if not first_scan and (key not in previous or key not in current or
            _values(previous[key]) != tuple(current[key]['months'].get(i) for i in range(1, 13))))
    timestamp = datetime.now(timezone.utc)
    # Replace this scope/year snapshot only after every sheet has parsed successfully.
    await connection.execute(delete(db.maker_global_reports).where(
        db.maker_global_reports.c.scope_key == scope['id'], db.maker_global_reports.c.year == year))
    for item in parsed:
        await connection.execute(pg_insert(db.maker_global_reports).values(
            id=digest([scope['id'], year, item['label'].casefold()]), scope_key=scope['id'], year=year,
            maker=item['label'], **_month_values(item['months']), total=item['total'],
            source_job_id=str(job.id), checksum=checksum, observed_at=observed_at, updated_at=timestamp))
    await connection.execute(pg_insert(db.maker_update_runs).values(
        id=str(job.id), owner_username=job.owner_username, scope_key=scope['id'], year=year,
        status='BASELINE' if first_scan else 'RUNNING' if changed else 'UNCHANGED',
        changed_makers=changed, states=filters['states'], created_at=timestamp, updated_at=timestamp))
    if first_scan:
        # The existing main table already maps known Maker -> State -> RTO.
        columns = ('id', 'scope_key', 'year', 'maker', 'state', 'rto', 'rto_code',
            *db.MONTH_COLUMNS, 'total', 'source_job_id', 'observed_at', 'updated_at')
        total = sum((func.coalesce(db.main_reports.c[month], 0) for month in db.MONTH_COLUMNS), 0)
        source = select(*(db.main_reports.c[column] for column in columns[:7]),
            *(db.main_reports.c[month] for month in db.MONTH_COLUMNS), total,
            literal(None), literal(observed_at), literal(timestamp)).where(
                db.main_reports.c.scope_key == scope['id'], db.main_reports.c.year == year)
        await connection.execute(pg_insert(db.maker_office_index).from_select(columns, source)
            .on_conflict_do_nothing())
    for maker in changed:
        for state in filters['states']:
            task_id = digest([str(job.id), 'DISCOVER', maker.casefold(), state.casefold()])
            await connection.execute(pg_insert(db.maker_update_tasks).values(
                id=task_id, run_id=str(job.id), kind='DISCOVER', maker=maker, state=state,
                rto='', rto_code='', status='PENDING', job_id=None, error=None,
                updated_at=timestamp))
    return {'parsedRows': len(parsed), 'changedMakers': changed, 'baseline': first_scan,
            'newRows': len(parsed) if first_scan else 0, 'newCells': 0, 'duplicates': 0, 'conflicts': 0}


async def _finish_task(connection, job):
    await connection.execute(update(db.maker_update_tasks).where(
        db.maker_update_tasks.c.id == job.update_task_id,
        db.maker_update_tasks.c.job_id == str(job.id)).values(
            status='DONE', error=None, updated_at=datetime.now(timezone.utc)))
    pending = await connection.scalar(select(db.maker_update_tasks.c.id).where(
        db.maker_update_tasks.c.run_id == str(job.update_run_id),
        db.maker_update_tasks.c.status != 'DONE').limit(1))
    if not pending:
        await connection.execute(update(db.maker_update_runs).where(
            db.maker_update_runs.c.id == str(job.update_run_id)).values(
                status='COMPLETED', updated_at=datetime.now(timezone.utc)))


async def commit_discovery(connection, job, rows, observed_at, *, no_data=False):
    task = (await connection.execute(select(db.maker_update_tasks).where(
        db.maker_update_tasks.c.id == job.update_task_id).with_for_update())).mappings().one()
    if task['job_id'] != str(job.id) or task['status'] != 'RUNNING':
        raise ValueError('Discovery task is not assigned to this job.')
    filters = job.filters.model_dump(mode='json', by_alias=True)
    scope, year = dataset(job.owner_username, filters), context_year(filters)
    parsed = [] if no_data else parse_summary(rows, year, 'rto')
    old_main = (await connection.execute(select(db.main_reports).where(
        db.main_reports.c.scope_key == scope['id'], db.main_reports.c.year == year,
        func.lower(db.main_reports.c.state) == task['state'].lower(),
        func.lower(db.main_reports.c.maker) == task['maker'].lower()))).mappings().all()
    prior = {(row['rto_code'] or row['rto']).casefold(): row for row in old_main}
    discovered = {}
    for item in parsed:
        rto, code = split_rto(item['label'])
        if not rto and not code:
            raise ValueError('RTO discovery returned an unnamed office.')
        if not code:
            matches = [row for row in old_main if row['rto'].casefold() == rto.casefold()]
            if len(matches) == 1:
                code = matches[0]['rto_code']
            elif len(matches) > 1:
                raise ValueError(f'RTO discovery cannot identify {rto} uniquely.')
            else:
                raise ValueError(f'New RTO {rto} has no code; cannot select its focused office safely.')
        key = (code or rto).casefold()
        if key in discovered:
            raise ValueError(f'RTO discovery returned duplicate office {item["label"]}.')
        discovered[key] = (rto, code, item)
    timestamp = datetime.now(timezone.utc)
    await connection.execute(delete(db.maker_office_index).where(
        db.maker_office_index.c.scope_key == scope['id'], db.maker_office_index.c.year == year,
        func.lower(db.maker_office_index.c.maker) == task['maker'].lower(),
        func.lower(db.maker_office_index.c.state) == task['state'].lower()))
    for key, (rto, code, item) in discovered.items():
        record_id = digest([scope['id'], year, task['state'].casefold(), key, task['maker'].casefold()])
        await connection.execute(pg_insert(db.maker_office_index).values(
            id=record_id, scope_key=scope['id'], year=year, maker=task['maker'], state=task['state'],
            rto=rto, rto_code=code, **_month_values(item['months']), total=item['total'],
            source_job_id=str(job.id), observed_at=observed_at, updated_at=timestamp))
    changed = []
    for key in prior.keys() | discovered.keys():
        old = prior.get(key)
        item = discovered.get(key)
        if item:
            rto, code, report = item
            values = tuple(report['months'].get(i) for i in range(1, 13))
        else:
            rto, code = old['rto'], old['rto_code']
            values = tuple(0 if old[month] is not None else None for month in db.MONTH_COLUMNS)
        if old and _values(old) == values:
            continue
        if not old and not any(value for value in values if value is not None):
            continue
        rto_label = rto + (' - ' + code if code else '')
        changed.append(rto_label)
        task_id = digest([str(job.update_run_id), 'REFRESH', task['maker'].casefold(),
            task['state'].casefold(), key])
        await connection.execute(pg_insert(db.maker_update_tasks).values(
            id=task_id, run_id=str(job.update_run_id), kind='REFRESH', maker=task['maker'],
            state=task['state'], rto=rto_label, rto_code=code, status='PENDING',
            job_id=None, error=None, updated_at=timestamp).on_conflict_do_nothing())
    await _finish_task(connection, job)
    remaining_discovery = await connection.scalar(select(db.maker_update_tasks.c.id).where(
        db.maker_update_tasks.c.run_id == str(job.update_run_id),
        db.maker_update_tasks.c.kind == 'DISCOVER',
        db.maker_update_tasks.c.status != 'DONE').limit(1))
    if not remaining_discovery:
        run = (await connection.execute(select(db.maker_update_runs).where(
            db.maker_update_runs.c.id == str(job.update_run_id)))).mappings().one()
        for maker in run['changed_makers']:
            global_row = (await connection.execute(select(db.maker_global_reports).where(
                db.maker_global_reports.c.scope_key == scope['id'],
                db.maker_global_reports.c.year == year,
                func.lower(db.maker_global_reports.c.maker) == maker.lower()))).mappings().first()
            office_rows = (await connection.execute(select(db.maker_office_index).where(
                db.maker_office_index.c.scope_key == scope['id'],
                db.maker_office_index.c.year == year,
                func.lower(db.maker_office_index.c.maker) == maker.lower()))).mappings().all()
            for month in db.MONTH_COLUMNS:
                expected = global_row[month] if global_row else 0
                if expected is not None and sum(row[month] or 0 for row in office_rows) != expected:
                    raise ValueError(f'State/RTO discovery does not reconcile with the all-State total for {maker} / {month}.')
    return {'parsedRows': len(parsed), 'changedRtos': changed, 'newRows': 0,
            'newCells': 0, 'duplicates': 0, 'conflicts': 0}


async def finish_refresh(connection, job):
    await _finish_task(connection, job)


async def validate_refresh_workbook(connection, job, rows):
    from app.repositories.annual_reports import parse_rows
    filters = job.filters.model_dump(mode='json', by_alias=True)
    entries, details = parse_rows(rows, filters)
    if details['issueCount'] or len(entries) != 1:
        raise ValueError('Focused Maker workbook must contain exactly one valid Maker/RTO row.')
    task = (await connection.execute(select(db.maker_update_tasks).where(
        db.maker_update_tasks.c.id == job.update_task_id))).mappings().one()
    entry = entries[0]
    if (entry['maker'].casefold() != task['maker'].casefold()
            or entry['state'].casefold() != task['state'].casefold()
            or (entry['rto_code'] or entry['rto']).casefold() !=
                (task['rto_code'] or split_rto(task['rto'])[0]).casefold()):
        raise ValueError('Focused workbook does not match its Maker, State and RTO task.')
    scope = dataset(job.owner_username, filters)['id']
    office = (await connection.execute(select(db.maker_office_index).where(
        db.maker_office_index.c.scope_key == scope,
        db.maker_office_index.c.year == context_year(filters),
        func.lower(db.maker_office_index.c.maker) == task['maker'].lower(),
        func.lower(db.maker_office_index.c.state) == task['state'].lower(),
        db.maker_office_index.c.rto_code == task['rto_code']))).mappings().first()
    if not office and any(value for value in entry['months'].values()):
        raise ValueError('Focused workbook conflicts with an RTO that disappeared from discovery.')
    if office:
        for month, column in enumerate(db.MONTH_COLUMNS, 1):
            expected = office[column]
            if expected is not None and entry['months'].get(month) != expected:
                raise ValueError(f'Focused workbook differs from State/RTO discovery for {task["maker"]} / {column}.')


async def clear_no_data_refresh(connection, job):
    task = (await connection.execute(select(db.maker_update_tasks).where(
        db.maker_update_tasks.c.id == job.update_task_id).with_for_update())).mappings().one()
    scope = dataset(job.owner_username, job.filters.model_dump(mode='json', by_alias=True))
    year = context_year(job.filters.model_dump(mode='json', by_alias=True))
    office_rto, _ = split_rto(task['rto'])
    main_rto_match = (db.main_reports.c.rto_code == task['rto_code']) if task['rto_code'] else (
        (db.main_reports.c.rto_code == '') & (db.main_reports.c.rto == office_rto))
    index_rto_match = (db.maker_office_index.c.rto_code == task['rto_code']) if task['rto_code'] else (
        (db.maker_office_index.c.rto_code == '') & (db.maker_office_index.c.rto == office_rto))
    previous = (await connection.execute(select(db.main_reports).where(
        db.main_reports.c.scope_key == scope['id'], db.main_reports.c.year == year,
        func.lower(db.main_reports.c.state) == task['state'].lower(),
        func.lower(db.main_reports.c.maker) == task['maker'].lower(),
        main_rto_match).with_for_update())).mappings().all()
    office = (await connection.execute(select(db.maker_office_index).where(
        db.maker_office_index.c.scope_key == scope['id'], db.maker_office_index.c.year == year,
        func.lower(db.maker_office_index.c.state) == task['state'].lower(),
        func.lower(db.maker_office_index.c.maker) == task['maker'].lower(),
        index_rto_match))).mappings().first()
    if office and office['total'] > 0:
        raise ValueError('Focused report has no data although State/RTO discovery found registrations; retry this office.')
    timestamp = datetime.now(timezone.utc)
    for row in previous:
        sources = dict(row['month_sources'])
        changes = {month: 0 for month in db.MONTH_COLUMNS if row[month] is not None}
        for index, month in enumerate(db.MONTH_COLUMNS, 1):
            if month in changes:
                sources[str(index)] = {'sourceKey': 'job:' + str(job.id), 'observedAt': timestamp.isoformat()}
        await connection.execute(update(db.main_reports).where(db.main_reports.c.id == row['id']).values(
            **changes, month_sources=sources, updated_at=timestamp))
    if office:
        await connection.execute(delete(db.maker_office_index).where(db.maker_office_index.c.id == office['id']))
    await _finish_task(connection, job)
    return {'parsedRows': 0, 'replacedRows': len(previous), 'newRows': 0,
            'newCells': 0, 'duplicates': 0, 'conflicts': 0}
