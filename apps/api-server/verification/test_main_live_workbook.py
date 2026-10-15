"""Replay a real populated workbook into a migrated disposable DB, never production."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import asyncio
from uuid import uuid4
from sqlalchemy import select, text, delete
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
BASE=make_url(os.environ['DATABASE_URL'])
if os.environ.get('VAHAN_MIGRATION_SOURCE_DATABASE'):
    BASE=BASE.set(database=os.environ['VAHAN_MIGRATION_SOURCE_DATABASE'])
TARGET=os.environ.get('VAHAN_MIGRATION_TEST_DATABASE','')
if not TARGET.startswith('vahan_results_') or not TARGET.endswith('_test'):
    raise RuntimeError('Disposable vahan_results_*_test required.')
os.environ['DATABASE_URL']=BASE.set(database=TARGET).render_as_string(hide_password=False)
from app.db import engine,schema as db
from app.models.job import Job,JobStatus
from app.repositories.postgres import PostgresJobRepository
from app.repositories.file_store import PostgresFileStore

async def main():
    source=create_async_engine(BASE)
    job=None
    source_key=None
    try:
        async with source.connect() as c:
            original=(await c.execute(text("""SELECT f.content,j.payload FROM stored_files f JOIN jobs j ON j.id=f.job_id
                WHERE f.kind='excel' AND j.filters->>'rtos' ILIKE '%Port Blair DTO - AN1%'
                ORDER BY f.created_at DESC LIMIT 1"""))).mappings().one()
        old=Job.model_validate(original['payload'])
        job=Job(runnerId='isolated-main-replay-'+str(uuid4()),ownerUsername=old.owner_username,
            filters=old.filters,status=JobStatus.WAITING_RESULT,scenarioName='Isolated real workbook replay')
        await PostgresJobRepository().create(job)
        source_key='job:'+str(job.id)
        store=PostgresFileStore()
        first=await store.commit_excel(job.id,'port-blair.xlsx',original['content'],observed_at=old.result_observed_at)
        assert first['status']=='COMPLETED'
        assert first['summary']['parsedRows']==3
        assert first['summary']['newRows']==0 and first['summary']['newCells']==0
        assert first['summary']['duplicates']==30
        assert (await store.commit_excel(job.id,'port-blair.xlsx',original['content']))==first
        async with engine.connect() as c:
            assert not await c.scalar(select(db.stored_files.c.id).where(db.stored_files.c.job_id==str(job.id)))
            assert await c.scalar(select(db.jobs.c.status).where(db.jobs.c.id==str(job.id)))=='COMPLETED'
            ledger=(await c.execute(select(db.report_update_history).where(db.report_update_history.c.source_key==source_key))).mappings().one()
            assert ledger['status']=='unchanged' and ledger['observed_at'].tzinfo
        print(json.dumps({'realCase':'Port Blair DTO - AN1','status':first['status'],
            'manufacturers':3,'monthValuesAlreadySaved':30,'duplicateRowsAdded':0,'SQLFileCopies':0}))
    finally:
        if job:
            async with engine.begin() as c:
                await c.execute(delete(db.report_update_history).where(db.report_update_history.c.source_key==source_key))
                await c.execute(delete(db.jobs).where(db.jobs.c.id==str(job.id)))
                await c.execute(delete(db.report_sessions).where(db.report_sessions.c.id==str(job.session_id)))
        await source.dispose(); await engine.dispose()
asyncio.run(main())
