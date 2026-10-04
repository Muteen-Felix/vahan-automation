"""Verify a restored 0005 snapshot before/after sharing, in a disposable DB only."""
import asyncio
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
target = os.environ.get('VAHAN_SHARED_TEST_DATABASE', '')
if not target.startswith('vahan_results_') or not target.endswith('_test'):
    raise RuntimeError('A disposable vahan_results_*_test database is required.')
base_url = make_url(os.environ['DATABASE_URL'])
os.environ['DATABASE_URL'] = base_url.set(database=target).render_as_string(hide_password=False)
deployed = os.environ.get('VAHAN_COMPARE_DEPLOYED_SHARED_REPORTS') == 'yes'
from app.repositories.annual_reports import dataset, digest
MONTHS = ('jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec')


async def snapshot(url=None):
    engine = create_async_engine(url or os.environ['DATABASE_URL'])
    try:
        async with engine.connect() as connection:
            await connection.execute(text('SET TRANSACTION READ ONLY'))
            return {table: [dict(row) for row in (await connection.execute(text('SELECT * FROM '+table))).mappings()]
                    for table in ('main_reports','report_update_history','stored_files','jobs','report_sessions')}
    finally:
        await engine.dispose()


before = asyncio.run(snapshot())
if not deployed:
    subprocess.run([sys.executable, '-m', 'app.migrate'], check=True)
after = asyncio.run(snapshot(base_url if deployed else None))
old_history = {r['source_key']: r for r in before['report_update_history']}
new_history = {r['source_key']: r for r in after['report_update_history']}
assert old_history.keys() <= new_history.keys() if deployed else old_history.keys() == new_history.keys()
for key, old in old_history.items():
    new = new_history[key]
    assert new['scope_key'] == dataset(None, old['filters'])['id']
    for field in old:
        if field != 'scope_key':
            assert new[field] == old[field], ('history changed', field, key)
for table in ('stored_files','jobs','report_sessions'):
    key = lambda row: row['id']
    if deployed:
        existing = {row['id']: row for row in after[table]}
        assert all(existing.get(row['id']) == row for row in before[table]), table+' changed'
    else:
        assert sorted(before[table], key=key) == sorted(after[table], key=key), table+' changed'
groups = {}
for row in before['main_reports']:
    shared = dataset(None, row['filters'])['id']
    identity = digest([shared, row['year'], row['state'].casefold(),
                       (row['rto_code'] or row['rto']).casefold(), row['maker'].casefold()])
    groups.setdefault(identity, []).append(row)
actual = {r['id']: r for r in after['main_reports']}
assert groups.keys() <= actual.keys() if deployed else actual.keys() == groups.keys()
cells = overlapping = conflicts = 0
for identity, originals in groups.items():
    new = actual[identity]
    assert 'owner_key' not in new
    assert new['created_at'] == min(r['created_at'] for r in originals)
    expected_updated = max(r['updated_at'] for r in originals)
    assert new['updated_at'] >= expected_updated if deployed else new['updated_at'] == expected_updated
    for index, month in enumerate(MONTHS, 1):
        key = str(index)
        candidates = [r for r in originals if r[month] is not None]
        def saved_order(row):
            source = old_history.get(row['month_sources'].get(key, {}).get('sourceKey'))
            return (source['imported_at'] if source else row['created_at'], row['id'])
        candidates.sort(key=saved_order)
        if not candidates:
            if not deployed:
                assert new[month] is None
            continue
        cells += len(candidates)
        winner = candidates[0]
        assert new[month] == winner[month], ('winning value changed', identity, month)
        provenance = new['month_sources'][key]
        for field,value in winner['month_sources'].get(key, {}).items():
            assert provenance[field] == value
        alternatives = provenance.get('mergedSources', [])
        assert len(alternatives) == len(candidates)-1
        for old,alternative in zip(candidates[1:],alternatives):
            assert alternative['recordId']==old['id'] and alternative['contributor']==old['owner_key']
            assert alternative['value']==old[month] and alternative['source']==old['month_sources'].get(key,{})
            assert alternative['conflict']==(new[month]!=old[month])
            overlapping += 1
            conflicts += int(alternative['conflict'])
print(json.dumps({'migration':'passed','beforeRows':len(before['main_reports']),'sharedRows':len(actual),
    'allOriginalMonthValuesAccountedFor':cells,'overlappingMonths':overlapping,'conflictsPreserved':conflicts,
    'historyItemsUnchanged':len(old_history),'operationalJobsFilesSessionsUnchanged':True}))
