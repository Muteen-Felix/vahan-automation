"""Share report identities across accounts and merge existing duplicate facts."""
import copy
import hashlib
import json
import re
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0006_shared_main_reports'
down_revision = '0005_merge_session_heads'
branch_labels = None
depends_on = None
MONTHS = ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')
CONTEXT = {'states', 'rtos', 'makers', 'fromYear', 'toYear', 'reportYear', 'reportMonth',
           'fromDate', 'toDate', 'autoApply', 'autoExport', 'xAxis', 'yAxis'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def scope_filters(filters):
    clean = lambda value: re.sub(r'\s+', ' ', str(value)).strip().upper()
    return {key: sorted({clean(v) for v in value}) if isinstance(value, list) else clean(value)
            for key, value in filters.items() if key not in CONTEXT and value not in (None, '', [])}


def consolidate(rows, source_times=None):
    """First committed non-null month wins; retain all overlapping source evidence."""
    source_times = source_times or {}
    groups = {}
    for original in sorted(rows, key=lambda r: (r['created_at'], r['id'])):
        filters = scope_filters(original['filters'])
        scope = digest(filters)
        identity = digest([scope, original['year'], original['state'].casefold(),
                           (original['rto_code'] or original['rto']).casefold(), original['maker'].casefold()])
        groups.setdefault(identity, []).append(original)
    merged, overlaps, conflicts = [], 0, 0
    for identity, originals in groups.items():
        target = copy.deepcopy(dict(originals[0]))
        target.pop('owner_key')
        filters = scope_filters(target['filters'])
        target.update(id=identity, scope_key=digest(filters), filters=filters,
            created_at=min(r['created_at'] for r in originals),
            updated_at=max(r['updated_at'] for r in originals))
        target['month_sources'] = {}
        for index, month in enumerate(MONTHS, 1):
            key = str(index)
            candidates = [r for r in originals if r[month] is not None]
            candidates.sort(key=lambda r: (source_times.get(
                r['month_sources'].get(key, {}).get('sourceKey'), r['created_at']), r['id']))
            if not candidates:
                target[month] = None
                continue
            winner = candidates[0]
            target[month] = winner[month]
            provenance = copy.deepcopy(winner['month_sources'].get(key, {}))
            for row in candidates[1:]:
                overlaps += 1
                conflict = winner[month] != row[month]
                conflicts += int(conflict)
                provenance.setdefault('mergedSources', []).append({
                    'recordId': row['id'], 'contributor': row['owner_key'], 'value': row[month],
                    'source': copy.deepcopy(row['month_sources'].get(key, {})), 'conflict': conflict})
            target['month_sources'][key] = provenance
        merged.append(target)
    return merged, {'beforeRows': len(rows), 'afterRows': len(merged),
                    'overlappingMonths': overlaps, 'conflictingMonths': conflicts}


def upgrade():
    connection = op.get_bind()
    connection.execute(sa.text('LOCK TABLE main_reports, report_update_history IN ACCESS EXCLUSIVE MODE'))
    original = connection.execute(sa.text('SELECT * FROM main_reports')).mappings().all()
    history = connection.execute(sa.text('SELECT source_key, filters, scope_label, imported_at FROM report_update_history')).mappings().all()
    merged, stats = consolidate(original, {h['source_key']: h['imported_at'] for h in history})
    # Re-key all facts inside one transaction; readers see either the old snapshot
    # or the complete shared snapshot. There is no intermediate partial table.
    connection.execute(sa.text('DELETE FROM main_reports'))
    op.drop_index('ix_main_reports_owner_key', table_name='main_reports')
    op.drop_column('main_reports', 'owner_key')
    columns = [sa.column(name, JSONB() if name in ('filters', 'month_sources') else sa.types.NullType())
               for name in merged[0]] if merged else []
    if merged:
        table = sa.table('main_reports', *columns)
        for start in range(0, len(merged), 300):
            connection.execute(sa.insert(table), merged[start:start + 300])
    ledger = sa.table('report_update_history', sa.column('source_key', sa.String()),
                      sa.column('scope_key', sa.String()), sa.column('filters', JSONB()))
    for item in history:
        filters = scope_filters(item['filters'])
        connection.execute(sa.update(ledger).where(ledger.c.source_key == item['source_key'])
                           .values(scope_key=digest(filters), filters=filters))
    actual = connection.execute(sa.text('SELECT * FROM main_reports ORDER BY id')).mappings().all()
    if [dict(row) for row in actual] != sorted(merged, key=lambda r: r['id']):
        raise RuntimeError('Shared-report migration verification failed; transaction rolled back.')
    if connection.scalar(sa.text('SELECT count(*) FROM report_update_history')) != len(history):
        raise RuntimeError('Shared-report migration changed the update ledger count.')
    # Preserve actors in the ledger for attribution; they no longer partition facts.
    print('Shared report migration:', json.dumps(stats, sort_keys=True))


def downgrade():
    raise RuntimeError('Restore the pre-shared-report backup to recover account-separated facts.')
