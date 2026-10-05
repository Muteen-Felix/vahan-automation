"""Exercise baseline -> changed Maker -> one changed RTO on a disposable *_test DB."""
import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import make_url

from app.db import engine, schema as db
from app.models.filters import VahanFilters
from app.models.job import Job
from app.repositories.annual_reports import dataset, import_rows
from app.repositories.maker_updates import commit_discovery, commit_global, finish_refresh, validate_refresh_workbook

if not (make_url(os.environ.get('DATABASE_URL', '')).database or '').endswith('_test'):
    raise RuntimeError('This verification requires a disposable *_test database.')


def filters(states, rtos=(), makers=(), y_axis='Maker'):
    return {'states': list(states), 'rtos': list(rtos), 'makers': list(makers),
        'archivedFlags': ['ACTIVE_COMPLIANT', 'ACTIVE_NON_COMPLIANT', 'PERMANENT_ARCHIVE', 'TEMPORARY_ARCHIVE'],
        'period': 'CALENDAR YEAR', 'fromYear': '2026', 'toYear': '2026', 'delhiNcr': 'ALL STATES',
        'categoryGroups': ['Two Wheeler'], 'subCategories': ['TWO WHEELER (Invalid Carriage)', 'TWO WHEELER(NT)', 'TWO WHEELER(T)'],
        'fuels': ['ELECTRIC(BOV)', 'PURE EV'], 'yAxis': y_axis, 'xAxis': 'Month Wise',
        'autoApply': True, 'autoExport': True}


def sheet(axis, label, count):
    return [
        {'sheet': 'Report', 'row_number': 1, 'cells': [axis, '2026-Jan', 'Total']},
        {'sheet': 'Report', 'row_number': 2, 'cells': [label, count, count]},
    ]


def maker_sheet(pairs):
    return ([{'sheet': 'Report', 'row_number': 1, 'cells': ['Maker', '2026-Jan', 'Total']}]
        + [{'sheet': 'Report', 'row_number': index + 2, 'cells': [maker, count, count]}
           for index, (maker, count) in enumerate(pairs)])


async def add_job(connection, filters_value):
    job = Job(runnerId='test-runner', filters=VahanFilters.model_validate(filters_value), ownerUsername='smoke')
    await connection.execute(insert(db.report_sessions).values(
        id=str(job.session_id), owner_username='smoke', created_at=job.created_at))
    await connection.execute(insert(db.jobs).values(id=str(job.id), owner_username='smoke',
        session_id=str(job.session_id), runner_id=job.runner_id, status=job.status.value,
        filters=filters_value, payload=job.model_dump(mode='json', by_alias=True),
        created_at=job.created_at, updated_at=job.updated_at))
    return job


async def main():
    stamp = datetime.now(timezone.utc)
    async with engine.begin() as connection:
        await connection.execute(insert(db.users).values(username='smoke', password_hash='test',
            role='admin', active=True, profile={}, created_at=stamp))
        for state, office, count in [('State A', 'Office A - AA1', 7), ('State B', 'Office B - BB2', 3)]:
            report_filters = filters([state], [office])
            await import_rows(connection, source_key='smoke:' + state, name='old',
                rows=sheet('Maker', 'OTHERS', count), filters=report_filters,
                owner='smoke', observed_at=stamp, strict=True)
        global_filters = filters(['State A', 'State B'])
        baseline = await add_job(connection, global_filters)
        result = await commit_global(connection, baseline, sheet('Maker', 'OTHERS', 10), 'a' * 64, stamp)
        assert result['baseline'] and result['changedMakers'] == []
        changed = await add_job(connection, global_filters)
        result = await commit_global(connection, changed, sheet('Maker', 'OTHERS', 12), 'b' * 64, stamp)
        assert result['changedMakers'] == ['OTHERS']
        tasks = (await connection.execute(select(db.maker_update_tasks).where(
            db.maker_update_tasks.c.run_id == str(changed.id)))).mappings().all()
        assert len(tasks) == 2
        for task in tasks:
            state = task['state']
            discovery_filters = filters([state], makers=['OTHERS'], y_axis='RTO Wise')
            discovery = await add_job(connection, discovery_filters)
            discovery.update_run_id, discovery.update_task_id = changed.id, task['id']
            await connection.execute(update(db.maker_update_tasks).where(
                db.maker_update_tasks.c.id == task['id']).values(status='RUNNING', job_id=str(discovery.id)))
            office, count = ('Office A - AA1', 9) if state == 'State A' else ('Office B - BB2', 3)
            await commit_discovery(connection, discovery, sheet('RTO', office, count), stamp)
        refresh_tasks = (await connection.execute(select(db.maker_update_tasks).where(
            db.maker_update_tasks.c.run_id == str(changed.id),
            db.maker_update_tasks.c.kind == 'REFRESH'))).mappings().all()
        assert len(refresh_tasks) == 1 and refresh_tasks[0]['state'] == 'State A'
        refresh_filter = filters(['State A'], ['Office A - AA1'], ['OTHERS'])
        refresh = await add_job(connection, refresh_filter)
        refresh.update_run_id, refresh.update_task_id = changed.id, refresh_tasks[0]['id']
        await connection.execute(update(db.maker_update_tasks).where(
            db.maker_update_tasks.c.id == refresh.update_task_id).values(status='RUNNING', job_id=str(refresh.id)))
        await validate_refresh_workbook(connection, refresh, sheet('Maker', 'OTHERS', 9))
        await import_rows(connection, source_key='smoke:refresh', name='new',
            rows=sheet('Maker', 'OTHERS', 9), filters=refresh_filter, owner='smoke',
            observed_at=stamp, strict=True, replace_existing=True, job_id=str(refresh.id))
        await finish_refresh(connection, refresh)
        scope = dataset('smoke', global_filters)['id']
        main_rows = (await connection.execute(select(db.main_reports).where(
            db.main_reports.c.scope_key == scope).order_by(db.main_reports.c.state))).mappings().all()
        assert [(row['state'], row['jan']) for row in main_rows] == [('State A', 9), ('State B', 3)]
        status = await connection.scalar(select(db.maker_update_runs.c.status).where(
            db.maker_update_runs.c.id == str(changed.id)))
        assert status == 'COMPLETED'
        new_maker = await add_job(connection, global_filters)
        result = await commit_global(connection, new_maker,
            maker_sheet([('OTHERS', 12), ('NEW MAKER', 5)]), 'c' * 64, stamp)
        assert result['changedMakers'] == ['NEW MAKER']
        tasks = (await connection.execute(select(db.maker_update_tasks).where(
            db.maker_update_tasks.c.run_id == str(new_maker.id)))).mappings().all()
        assert len(tasks) == 2
        for task in tasks:
            discovery = await add_job(connection, filters([task['state']], makers=['NEW MAKER'], y_axis='RTO Wise'))
            discovery.update_run_id, discovery.update_task_id = new_maker.id, task['id']
            await connection.execute(update(db.maker_update_tasks).where(
                db.maker_update_tasks.c.id == task['id']).values(status='RUNNING', job_id=str(discovery.id)))
            if task['state'] == 'State A':
                await commit_discovery(connection, discovery, sheet('RTO', 'Office C - AA3', 5), stamp)
            else:
                await commit_discovery(connection, discovery, [], stamp, no_data=True)
        new_tasks = (await connection.execute(select(db.maker_update_tasks).where(
            db.maker_update_tasks.c.run_id == str(new_maker.id),
            db.maker_update_tasks.c.kind == 'REFRESH'))).mappings().all()
        assert len(new_tasks) == 1 and new_tasks[0]['rto_code'] == 'AA3'
        new_filter = filters(['State A'], ['Office C - AA3'], ['NEW MAKER'])
        new_job = await add_job(connection, new_filter)
        new_job.update_run_id, new_job.update_task_id = new_maker.id, new_tasks[0]['id']
        await connection.execute(update(db.maker_update_tasks).where(
            db.maker_update_tasks.c.id == new_job.update_task_id).values(status='RUNNING', job_id=str(new_job.id)))
        await validate_refresh_workbook(connection, new_job, sheet('Maker', 'NEW MAKER', 5))
        await import_rows(connection, source_key='smoke:new-maker', name='new maker',
            rows=sheet('Maker', 'NEW MAKER', 5), filters=new_filter, owner='smoke',
            observed_at=stamp, strict=True, replace_existing=True, job_id=str(new_job.id))
        await finish_refresh(connection, new_job)
        new_count = await connection.scalar(select(db.main_reports.c.jan).where(
            db.main_reports.c.scope_key == scope, db.main_reports.c.maker == 'NEW MAKER'))
        assert new_count == 5
    await engine.dispose()
    print('Maker update smoke passed: baseline, changed RTO, new Maker, no-data discovery, SQL replacement.')


asyncio.run(main())
