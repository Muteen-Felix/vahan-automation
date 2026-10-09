"""Full workbook ingestion with observed-time ordering and retained value history."""
import hashlib
import json
import re
from datetime import datetime, timezone

from sqlalchemy import bindparam, select, update, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import engine, schema as db

MONTHS = ('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC')
MONTH_NAMES = set(MONTHS) | {'JANUARY', 'FEBRUARY', 'MARCH', 'APRIL', 'JUNE', 'JULY', 'AUGUST',
                           'SEPT', 'SEPTEMBER', 'OCTOBER', 'NOVEMBER', 'DECEMBER'}
CONTEXT_KEYS = {'states', 'rtos', 'makers', 'fromYear', 'toYear', 'reportYear', 'reportMonth',
                'fromDate', 'toDate', 'autoApply', 'autoExport', 'xAxis', 'yAxis'}


def clean(value):
    return re.sub(r'\s+', ' ', str('' if value is None else value)).strip()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def saved_report_summary(item):
    details = item['details']
    return {'datasetId': item['scope_key'], 'years': item['years'], 'states': item['states'],
            'rtos': item['rtos'], 'status': item['status'], 'savedAt': item['imported_at'].isoformat(),
            'observedAt': item['observed_at'].isoformat(), 'manufacturerRows': details.get('parsedRows', 0),
            'newRows': details.get('newRows', 0), 'newMonthValues': details.get('newCells', 0),
            'updatedMonthValues': details.get('replacedCells', 0),
            'alreadySavedMonthValues': details.get('duplicates', 0), 'conflicts': details.get('conflicts', 0)}


def dataset(owner, filters):
    scope = {}
    for key, value in filters.items():
        if key in CONTEXT_KEYS or value in (None, '', []):
            continue
        scope[key] = sorted({clean(v).upper() for v in value}) if isinstance(value, list) else clean(value).upper()
    parts = [', '.join(scope[key]) for key in ('categoryGroups', 'fuels', 'classes', 'emissions') if key in scope]
    default_subcategories = {'TWO WHEELER (INVALID CARRIAGE)', 'TWO WHEELER(NT)', 'TWO WHEELER(T)'}
    if 'subCategories' in scope and set(scope['subCategories']) != default_subcategories:
        parts.append(', '.join(scope['subCategories']))
    default_archives = {'ACTIVE_COMPLIANT', 'ACTIVE_NON_COMPLIANT', 'PERMANENT_ARCHIVE', 'TEMPORARY_ARCHIVE'}
    if 'archivedFlags' in scope and set(scope['archivedFlags']) != default_archives:
        parts.append(', '.join(scope['archivedFlags']))
    if scope.get('delhiNcr') not in (None, 'ALL STATES'):
        parts.append(scope['delhiNcr'])
    for key, title in (('evTypes', 'EV type'), ('statuses', 'Status'), ('ownerTypes', 'Owner type'),
                       ('vehicleType', 'Vehicle type'), ('fitness', 'Fitness')):
        if key in scope:
            value = ', '.join(scope[key]) if isinstance(scope[key], list) else scope[key]
            parts.append(f'{title}: {value}')
    label = ' · '.join(parts)
    # Report identity is shared. The actor is retained only in the update ledger.
    return {'id': digest(scope), 'owner_key': owner or '',
            'label': label or 'Uploaded manufacturer data', 'filters': scope}


def context_year(filters):
    years = {int(str(filters[k])) for k in ('fromYear', 'toYear', 'reportYear')
             if str(filters.get(k, '')).isdigit() and 1900 <= int(str(filters[k])) <= 9999}
    return next(iter(years)) if len(years) == 1 else None


def month_column(label, fallback_year):
    label = clean(label).upper()
    # Accept VAHAN 2026-Jan, Jan'26 and full month names; never infer a missing year across a range.
    match = re.fullmatch(r'(?:(\d{4})[\s\-/]+)?([A-Z]+)(?:[\s\-/\'’]+(\d{2}|\d{4}))?', label)
    if not match or match[2] not in MONTH_NAMES:
        return None
    raw_year = match[1] or match[3]
    year = int(raw_year) if raw_year else fallback_year
    if raw_year and len(raw_year) == 2:
        reference = fallback_year or datetime.now().year
        year += (reference // 100) * 100
        if year > reference + 50:
            year -= 100
        elif year < reference - 50:
            year += 100
    if not year or not 1900 <= year <= 9999:
        return None
    return year, MONTHS.index(match[2][:3]) + 1


def number(value):
    if value is None or clean(value) in ('', '-', '—'):
        return None
    if isinstance(value, bool):
        raise ValueError('Boolean count')
    text = clean(value).replace(',', '')
    if not re.fullmatch(r'\d+(?:\.0+)?', text):
        raise ValueError('Invalid registration count')
    result = int(text.split('.')[0])
    if result > 9223372036854775807:
        raise ValueError('Registration count exceeds SQL bigint')
    return result


def split_rto(value, code=''):
    value, code = clean(value), clean(code).upper()
    match = re.fullmatch(r'(.*?)\s*-\s*([A-Z]{2}\d+[A-Z]*)', value, re.I)
    if match:
        return clean(match[1]), code or match[2].upper()
    return value, code


def parse_rows(rows, filters):
    """Read all sheets, retain OTHERS as a maker group, and keep blanks distinct from zero."""
    headers, entries, issues = {}, {}, []
    stats = {'unresolvedMakers': 0, 'invalidCells': 0, 'missingContext': 0, 'sourceConflicts': 0}
    year = context_year(filters)
    states, rtos = filters.get('states', []), filters.get('rtos', [])
    for row in rows:
        cells = row['cells']
        sheet = row.get('sheet', 'Report')
        labels = [re.sub(r'[^a-z0-9]', '', clean(v).lower()) for v in cells]
        maker_col = next((i for i, v in enumerate(labels) if v in ('maker', 'manufacturer', 'manufacturername')), None)
        months = {i: parsed for i, v in enumerate(cells) if (parsed := month_column(v, year))}
        if maker_col is not None and months:
            headers[sheet] = (maker_col, months, {name: next((i for i, v in enumerate(labels) if v in names), None)
                for name, names in {'state': ('state', 'statename'), 'rto': ('rto', 'rtoname'),
                                    'rto_code': ('rtocode',)}.items()})
            continue
        if sheet not in headers:
            continue
        maker_col, months, cols = headers[sheet]
        get = lambda i: cells[i] if i is not None and i < len(cells) else None
        maker = clean(get(maker_col))
        if not maker or maker.lower() in ('total', 'grand total', 'page total', 'no record found'):
            continue
        if maker.casefold() == 'others':
            # VAHAN uses OTHERS as an aggregate manufacturer group. Store its
            # monthly totals under that exact label instead of dropping the row.
            maker = 'OTHERS'
        elif maker.casefold() in ('other', 'unknown'):
            stats['unresolvedMakers'] += 1
            issues.append(f'{sheet}:{row["row_number"]}: source contains "{maker}" without a manufacturer name.')
            continue
        state = clean(get(cols['state'])) or (clean(states[0]) if len(states) == 1 else '')
        rto, code = split_rto(get(cols['rto']) or (rtos[0] if len(rtos) == 1 else ''), get(cols['rto_code']))
        if not state or not (rto or code):
            stats['missingContext'] += 1
            issues.append(f'{sheet}:{row["row_number"]}: State/RTO is ambiguous or missing.')
            continue
        for col, (cell_year, month) in months.items():
            try:
                value = number(get(col))
            except ValueError:
                stats['invalidCells'] += 1
                issues.append(f'{sheet}:{row["row_number"]}: invalid {cell_year}-{month:02d} count for {maker}.')
                continue
            if value is None:
                continue
            key = (cell_year, state.casefold(), (code or rto).casefold(), maker.casefold())
            item = entries.setdefault(key, {'year': cell_year, 'state': state, 'rto': rto,
                                            'rto_code': code, 'maker': maker, 'months': {}})
            if month in item['months'] and item['months'][month] != value:
                stats['sourceConflicts'] += 1
                issues.append(f'{sheet}:{row["row_number"]}: conflicting duplicate manufacturer {maker}, month {month}.')
            else:
                item['months'][month] = value
    if not headers:
        issues.append('No manufacturer/month table with an unambiguous year (1900 onward) was found.')
    # Counts cover every issue; retain a bounded diagnostic sample rather than a huge response.
    return list(entries.values()), {**stats, 'issueCount': len(issues), 'warnings': issues[:30]}


async def import_rows(connection, *, source_key, name, rows, filters, owner, observed_at,
                      job_id=None, no_data=False, warning=None, strict=False, checksum=None,
                      replace_existing=False, update_newer=False):
    """Write full filter data and its update history in the caller's transaction."""
    scope = dataset(owner, filters)
    timestamp = datetime.now(timezone.utc)
    entries, details = parse_rows(rows, filters) if not no_data and not warning else ([], {
        'warnings': [warning] if warning else [], 'issueCount': int(bool(warning))})
    if strict and not no_data and (details['issueCount'] or not entries):
        raise ValueError('MAIN_REPORT_PARSE_FAILED: ' + '; '.join(details['warnings'] or ['No manufacturer data found.']))
    expected_year = context_year(filters)
    if strict and job_id and expected_year and any(entry['year'] != expected_year for entry in entries):
        raise ValueError(f'MAIN_REPORT_YEAR_MISMATCH: workbook does not match the selected year {expected_year}.')
    if replace_existing:
        selected = filters.get('makers', [])
        if len(selected) != 1 or len(filters.get('states', [])) != 1 or len(filters.get('rtos', [])) != 1:
            raise ValueError('A replacement requires one Maker, State and RTO.')
        expected_rto, expected_code = split_rto(filters['rtos'][0])
        for entry in entries:
            if (entry['maker'].casefold() != clean(selected[0]).casefold()
                    or entry['state'].casefold() != clean(filters['states'][0]).casefold()
                    or (entry['rto_code'] or entry['rto']).casefold() != (expected_code or expected_rto).casefold()):
                raise ValueError('Focused workbook contains another Maker, State or RTO.')
    claimed = await connection.scalar(pg_insert(db.report_update_history).values(
        source_key=source_key, owner_key=scope['owner_key'], scope_key=scope['id'],
        scope_label=scope['label'], filters=scope['filters'], job_id=job_id, name=name,
        status='processing', years=[], states=[], rtos=[], details={}, observed_at=observed_at,
        imported_at=timestamp).on_conflict_do_nothing().returning(db.report_update_history.c.source_key))
    if not claimed:
        return False
    # Serialize overlapping offices only. Different RTOs can commit in parallel.
    lock_ids = {int.from_bytes(bytes.fromhex(digest([scope['id'], e['year'], e['state'].casefold(),
                (e['rto_code'] or e['rto']).casefold()]))[:8], 'big', signed=True) for e in entries}
    for lock_id in sorted(lock_ids):
        await connection.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock_id})
    records = {}
    for entry in entries:
        record_id = digest([scope['id'], entry['year'], entry['state'].casefold(),
                            (entry['rto_code'] or entry['rto']).casefold(), entry['maker'].casefold()])
        records[record_id] = entry
    ids = sorted(records)
    existing = {}
    for start in range(0, len(ids), 500):
        existing.update({r['id']: dict(r) for r in (await connection.execute(select(db.main_reports)
            .where(db.main_reports.c.id.in_(ids[start:start + 500])))).mappings()})
    additions, index_rows, conflicts, duplicates, new_cells, replaced_cells = [], [], [], 0, 0, 0
    pending_updates = {}
    for record_id in ids:
        entry = records[record_id]
        previous = existing.get(record_id)
        value = previous or {k: v for k, v in entry.items() if k != 'months'} | {
            'id': record_id, 'scope_key': scope['id'],
            'scope_label': scope['label'], 'filters': scope['filters'], 'created_at': timestamp,
            'updated_at': timestamp, 'month_sources': {}, **dict.fromkeys(db.MONTH_COLUMNS)}
        changes = {}
        provenance = dict(value['month_sources'])
        provenance_changed = False
        for month, incoming in entry['months'].items():
            column = db.MONTH_COLUMNS[month - 1]
            stored = value[column]
            previous_source = provenance.get(str(month))
            previous_observed = value['updated_at']
            if isinstance(previous_source, dict):
                try:
                    previous_observed = datetime.fromisoformat(previous_source['observedAt'].replace('Z', '+00:00'))
                    if previous_observed.tzinfo is None:
                        previous_observed = previous_observed.replace(tzinfo=timezone.utc)
                except (KeyError, TypeError, ValueError, AttributeError):
                    pass
            newer = observed_at > previous_observed
            if stored is None:
                changes[column] = incoming
                provenance[str(month)] = {'sourceKey': source_key, 'observedAt': observed_at.isoformat()}
                new_cells += 1
            elif stored == incoming:
                duplicates += 1
                # An unchanged newer observation still prevents an older
                # in-flight response from overwriting this confirmed value.
                if update_newer and newer:
                    fresh_source = {'sourceKey': source_key, 'observedAt': observed_at.isoformat()}
                    if isinstance(previous_source, dict) and 'replaced' in previous_source:
                        fresh_source['replaced'] = previous_source['replaced']
                    provenance[str(month)] = fresh_source
                    provenance_changed = True
            elif replace_existing or (update_newer and newer):
                changes[column] = incoming
                provenance[str(month)] = {'sourceKey': source_key, 'observedAt': observed_at.isoformat(),
                    'replaced': {'value': stored, 'source': previous_source}}
                replaced_cells += 1
            else:
                conflicts.append({k: entry[k] for k in ('maker', 'state', 'rto', 'year')} | {
                    'month': month, 'stored': stored, 'incoming': incoming})
        if previous:
            if changes or provenance_changed:
                values = {**changes, 'month_sources': provenance, 'updated_at': timestamp}
                columns = tuple(sorted(values))
                pending_updates.setdefault(columns, []).append({'record_id': record_id,
                    **{'v_' + key: incoming for key, incoming in values.items()}})
        else:
            additions.append(value | changes | {'month_sources': provenance})
        index_rows.append((value | changes) | {'id': record_id})
    # Update changed values and fresh observations in batches rather than a
    # SQL round trip per Maker while ten workers are saving concurrently.
    for columns, values in pending_updates.items():
        statement = update(db.main_reports).where(db.main_reports.c.id == bindparam('record_id')).values(
            {key: bindparam('v_' + key) for key in columns})
        for start in range(0, len(values), 500):
            await connection.execute(statement, values[start:start + 500])
    for start in range(0, len(additions), 500):
        await connection.execute(pg_insert(db.main_reports).values(additions[start:start + 500]))
    offices = []
    for row in index_rows:
        office = {key: row[key] for key in ('id', 'scope_key', 'year', 'state', 'rto', 'rto_code', 'maker')}
        office.update({month: row[month] for month in db.MONTH_COLUMNS})
        office.update(total=sum(row[month] or 0 for month in db.MONTH_COLUMNS),
            source_job_id=job_id, observed_at=observed_at, updated_at=timestamp)
        offices.append(office)
    for start in range(0, len(offices), 300):
        statement = pg_insert(db.maker_office_index).values(offices[start:start + 300])
        await connection.execute(statement.on_conflict_do_update(
            index_elements=[db.maker_office_index.c.id],
            set_={key: statement.excluded[key] for key in offices[0] if key != 'id'},
            where=(statement.excluded.observed_at >= db.maker_office_index.c.observed_at) if update_newer else None))
    details.update(newRows=len(additions), newCells=new_cells, replacedCells=replaced_cells, duplicates=duplicates,
                   conflicts=len(conflicts), conflictExamples=conflicts[:20], parsedRows=len(records))
    if checksum:
        details['checksum'] = checksum
    status = 'no-data' if no_data else 'review' if details['issueCount'] or conflicts else 'updated' if replaced_cells else 'added' if new_cells else 'unchanged'
    await connection.execute(update(db.report_update_history).where(db.report_update_history.c.source_key == source_key).values(
        status=status, years=sorted({r['year'] for r in entries}) or ([context_year(filters)] if context_year(filters) else []),
        states=sorted({r['state'] for r in entries}) or filters.get('states', []),
        rtos=sorted({r['rto'] + (' - ' + r['rto_code'] if r['rto_code'] else '') for r in entries}) or filters.get('rtos', []),
        details=details))
    from app.db.read_cache import invalidate_annual_reports
    invalidate_annual_reports()
    return True


async def import_file(connection, file_id, rows, job=None, owner=None, name=None, observed_at=None):
    # Compatibility for operator imports; the source ID is metadata, never a stored file.
    filters = job.filters.model_dump(mode='json', by_alias=True) if job else {}
    return await import_rows(connection, source_key='file:' + file_id,
        job_id=str(job.id) if job else None, owner=job.owner_username if job else owner, filters=filters,
        name=name or file_id, observed_at=observed_at or datetime.now(timezone.utc), rows=rows, strict=True)


async def backfill():
    # Legacy SQL facts are transferred by migration 0004, before their old tables are removed.
    # New filters import synchronously, so no background sync or secondary tables are needed.
    return 0
