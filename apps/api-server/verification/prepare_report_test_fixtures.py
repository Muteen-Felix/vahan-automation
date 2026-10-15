"""Build synthetic, populated fixtures for the historical read-only checks.

Requires a disposable PostgreSQL cluster and explicit *_test DATABASE_URL.
No production DB/workbook is read. Original dates and values are retained for
migration comparisons.
"""
import asyncio
from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import asyncpg
from openpyxl import Workbook
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
base = make_url(os.environ['DATABASE_URL'])
if not (base.database or '').endswith('_test'):
    raise RuntimeError('Use an explicitly disposable *_test PostgreSQL cluster.')

LEGACY_SOURCE = 'vahan_results_round2_legacy_source_test'
LEGACY_TARGET = 'vahan_results_round2_legacy_target_test'
SHARED_TARGET = 'vahan_results_round2_shared_target_test'
WORKBOOK_SOURCE = 'vahan_results_round2_workbook_source_test'
WORKBOOK_TARGET = 'vahan_results_round2_workbook_target_test'
STAMP = datetime(2024, 11, 1, tzinfo=timezone.utc)
FILTERS = {'states': ['Andaman & Nicobar'], 'rtos': ['Port Blair DTO - AN1'],
           'fromYear': '2024', 'toYear': '2024', 'yAxis': 'Maker', 'xAxis': 'Month Wise',
           'categoryGroups': ['Two Wheeler']}


def url(name, driver='postgresql+asyncpg'):
    if not name.startswith('vahan_results_round2_') or not name.endswith('_test'):
        raise RuntimeError('Invalid fixture database name.')
    return base.set(drivername=driver, database=name).render_as_string(hide_password=False)


def migrate(name, revision):
    env = {**os.environ, 'DATABASE_URL': url(name)}
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', revision], cwd=root, env=env, check=True)


async def connect(name):
    return await asyncpg.connect(url(name, 'postgresql'))


async def create(name):
    admin = await asyncpg.connect(base.set(drivername='postgresql', database='postgres').render_as_string(hide_password=False))
    try:
        if await admin.fetchval('SELECT 1 FROM pg_database WHERE datname=$1', name):
            raise RuntimeError('Fixture database already exists; choose a fresh disposable cluster.')
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()


def workbook():
    book = Workbook()
    sheet = book.active
    sheet.append(['Maker', 'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'TOTAL'])
    for maker in range(3):
        values = [maker + month for month in range(1, 11)]
        sheet.append([f'Synthetic Maker {maker}', *values, sum(values)])
    output = BytesIO()
    book.save(output); book.close()
    return output.getvalue()


async def seed_source(name, legacy=False):
    from app.models.job import Job, JobStatus
    from app.repositories.postgres import job_document
    connection = await connect(name)
    job = Job(runnerId='synthetic-source', ownerUsername='fixture-owner', status=JobStatus.WAITING_RESULT,
              filters=FILTERS, resultObservedAt=STAMP)
    content = workbook()
    try:
        await connection.execute("INSERT INTO users VALUES ($1,$2,$3,$4,$5,$6)",
                                 'fixture-owner', 'fixture', 'admin', True, '{}', STAMP)
        await connection.execute('INSERT INTO report_sessions (id,owner_username,created_at) VALUES ($1,$2,$3)',
                                 str(job.session_id), 'fixture-owner', STAMP)
        await connection.execute('INSERT INTO jobs (id,owner_username,session_id,runner_id,status,filters,payload,created_at,updated_at) '
                                 'VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)', str(job.id), 'fixture-owner', str(job.session_id),
                                 job.runner_id, job.status.value, json.dumps(FILTERS), json.dumps(job_document(job)), STAMP, STAMP)
        file_id = str(uuid4())
        import hashlib
        await connection.execute('INSERT INTO stored_files (id,owner_username,job_id,kind,name,mime_type,size,sha256,content,metadata,created_at) '
                                 'VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)', file_id, 'fixture-owner', str(job.id), 'excel',
                                 'synthetic-port-blair.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                 len(content), hashlib.sha256(content).hexdigest(), content, '{}', STAMP)
        if legacy:
            await connection.execute('INSERT INTO annual_datasets VALUES ($1,$2,$3,$4)',
                                     'fixture-scope', 'fixture-owner', 'Synthetic historical report', json.dumps(FILTERS))
            source = 'file:' + file_id
            await connection.execute('INSERT INTO annual_imports VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)',
                source, 'fixture-scope', file_id, str(job.id), 'Synthetic historical report', 'imported', '[2024]',
                json.dumps(FILTERS['states']), json.dumps(FILTERS['rtos']), '{"parsedRows":3}', STAMP, STAMP)
            for maker in range(3):
                record = f'fixture-record-{maker}'
                await connection.execute('INSERT INTO annual_records VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)',
                    record, 'fixture-scope', 2024, FILTERS['states'][0], FILTERS['rtos'][0], 'AN1', f'Synthetic Maker {maker}', STAMP, STAMP)
                for month in range(1, 11):
                    await connection.execute('INSERT INTO annual_cells VALUES ($1,$2,$3,$4,$5)', record, month, maker + month, source, STAMP)
        print(json.dumps({'database': name, 'synthetic': True, 'makers': 3, 'monthValues': 30}))
    finally:
        await connection.close()


async def seed_workbook_target():
    from app.models.job import Job, JobStatus
    from app.repositories.file_store import PostgresFileStore
    from app.services import services
    from app.db import engine
    await services.users.bootstrap('fixture-owner', 'fixture-only-password')
    job = await services.jobs.create(Job(runnerId='baseline', ownerUsername='fixture-owner', status=JobStatus.WAITING_RESULT, filters=FILTERS))
    result = await PostgresFileStore().commit_excel(job.id, 'baseline.xlsx', workbook(), observed_at=STAMP)
    assert result['summary']['parsedRows'] == 3
    assert result['summary']['newCells'] == 30
    await engine.dispose()


def clone(source, target):
    # URLs are passed only to the child environment, never printed in logs.
    container = os.environ['VAHAN_FIXTURE_POSTGRES_CONTAINER']
    user = base.username
    dump = subprocess.run(['docker', 'exec', container, 'pg_dump', '-U', user, source], capture_output=True, check=True).stdout
    subprocess.run(['docker', 'exec', '-i', container, 'psql', '-q', '-v', 'ON_ERROR_STOP=1', '-U', user, '-d', target],
                   input=dump, check=True)


def main():
    for name in [LEGACY_SOURCE, LEGACY_TARGET, SHARED_TARGET, WORKBOOK_SOURCE, WORKBOOK_TARGET]:
        asyncio.run(create(name))
    migrate(LEGACY_SOURCE, '0003_annual_reports')
    asyncio.run(seed_source(LEGACY_SOURCE, legacy=True))
    for name in [LEGACY_TARGET, SHARED_TARGET]:
        clone(LEGACY_SOURCE, name)
        migrate(name, '0005_merge_session_heads')
    migrate(WORKBOOK_SOURCE, 'head'); migrate(WORKBOOK_TARGET, 'head')
    asyncio.run(seed_source(WORKBOOK_SOURCE))
    subprocess.run([sys.executable, str(Path(__file__).resolve()), '--workbook-target'], cwd=root,
                   env={**os.environ, 'DATABASE_URL': url(WORKBOOK_TARGET)}, check=True)


if __name__ == '__main__':
    if '--workbook-target' in sys.argv:
        asyncio.run(seed_workbook_target())
    else:
        main()
