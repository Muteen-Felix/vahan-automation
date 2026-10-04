"""Read-only comparison: pre-migration production vs a restored, migrated test copy."""
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asyncio
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

BASE = make_url(os.environ['DATABASE_URL'])
DEPLOYED_DATABASE = BASE.database
if os.environ.get('VAHAN_MIGRATION_SOURCE_DATABASE'):
    BASE = BASE.set(database=os.environ['VAHAN_MIGRATION_SOURCE_DATABASE'])
TARGET = os.environ.get('VAHAN_MIGRATION_TEST_DATABASE', '')
if not (TARGET.startswith('vahan_results_') and TARGET.endswith('_test')) and not (
        TARGET == DEPLOYED_DATABASE and os.environ.get('VAHAN_COMPARE_DEPLOYED_MAIN_REPORTS') == 'yes'):
    raise RuntimeError('A disposable vahan_results_*_test comparison database is required.')
MONTHS = ('jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec')

async def read(engine, query):
    async with engine.connect() as c:
        await c.execute(text('SET TRANSACTION READ ONLY'))
        return [tuple(row) for row in await c.execute(text(query))]

async def main():
    source = create_async_engine(BASE)
    target = create_async_engine(BASE.set(database=TARGET))
    try:
        old_rows = await read(source, '''SELECT r.id,d.owner_key,r.dataset_id,d.label,d.filters::text,
            r.year,r.state,r.rto,r.rto_code,r.maker,r.created_at,r.updated_at
            FROM annual_records r JOIN annual_datasets d ON d.id=r.dataset_id ORDER BY r.id''')
        new_rows = await read(target, '''SELECT id,owner_key,scope_key,scope_label,filters::text,
            year,state,rto,rto_code,maker,created_at,updated_at FROM main_reports ORDER BY id''')
        assert old_rows == new_rows, 'Manufacturer identity/filter/timestamp mismatch'
        old_cells = await read(source, 'SELECT record_id,month,value,source_key,observed_at FROM annual_cells ORDER BY record_id,month')
        values=','.join(f'({i},r.{m})' for i,m in enumerate(MONTHS,1))
        new_cells = await read(target, f'''SELECT r.id,v.month,v.value,
            (r.month_sources->v.month::text)->>'sourceKey',
            ((r.month_sources->v.month::text)->>'observedAt')::timestamptz
            FROM main_reports r CROSS JOIN LATERAL (VALUES {values}) v(month,value)
            WHERE v.value IS NOT NULL ORDER BY r.id,v.month''')
        assert old_cells == new_cells, 'Monthly value/provenance/time mismatch'
        old_history = await read(source, '''SELECT i.source_key,d.owner_key,i.dataset_id,d.label,d.filters::text,
            i.job_id,i.name,i.status,i.years::text,i.states::text,i.rtos::text,
            (i.details || CASE WHEN f.sha256 IS NOT NULL THEN jsonb_build_object('checksum',f.sha256)
                ELSE '{}'::jsonb END)::text,i.observed_at,i.imported_at
            FROM annual_imports i JOIN annual_datasets d ON d.id=i.dataset_id
            LEFT JOIN stored_files f ON f.id=i.file_id ORDER BY i.source_key''')
        new_history = await read(target, '''SELECT source_key,owner_key,scope_key,scope_label,filters::text,
            job_id,name,status,years::text,states::text,rtos::text,details::text,observed_at,imported_at
            FROM report_update_history ORDER BY source_key''')
        assert old_history == new_history, 'Update history mismatch'
        assert await read(source,"SELECT id,sha256 FROM stored_files WHERE kind='captcha' ORDER BY id") == await read(
            target,"SELECT id,sha256 FROM stored_files WHERE kind='captcha' ORDER BY id"), 'CAPTCHA operational files changed'
        assert not await read(target,"SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('annual_records','annual_cells','annual_datasets','annual_imports','file_rows','report_rows','report_results')")
        assert not await read(target,"SELECT id FROM stored_files WHERE kind IN ('excel','no-data') OR (kind='screenshot' AND name='result.png')")
        print(json.dumps({'manufacturerRows':len(new_rows),'monthValues':len(new_cells),'historyItems':len(new_history),
            'missingOrChanged':0,'extra':0,'originalDatesAndSourcesPreserved':True,'retiredReportTables':7}))
    finally:
        await source.dispose(); await target.dispose()

asyncio.run(main())
