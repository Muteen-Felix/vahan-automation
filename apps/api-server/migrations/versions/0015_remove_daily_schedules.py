"""Remove saved Daily run schedules (PLAN D-35: only Once and Monthly are supported).

Only rows of ``app_settings`` whose key starts with ``automatic-report-schedule:`` and whose
``repeat`` is ``daily`` are deleted. Before a row is deleted, the run metadata that the Run
History page reads from the schedule row (filter name, profile, start time, last progress) is
copied to ``report-run-history:<session>`` so earlier runs keep their name. Reports, jobs,
sessions, queue tables, attempts and every other row are left untouched; the migration verifies
that and raises (rolling the whole transaction back) if any other table or schedule changed.

The deleted ids and the count are printed (visible in the ``migrate`` service log) and stored in
``app_settings`` under ``migration-audit:0015_remove_daily_schedules`` (ids and non-sensitive
metadata only, never the filter definition). The preceding revision ``0014a_daily_schedule_guard``
aborts the upgrade before this one runs when a Daily schedule still owns a session, so only Daily
schedules without a ``sessionId`` reach this migration (PLAN D-35, Q1 = A). The downgrade cannot
restore deleted schedules; use the pre-upgrade backup.
"""
import json
import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = '0015_remove_daily_schedules'
down_revision = '0014a_daily_schedule_guard'
branch_labels = None
depends_on = None

SCHEDULE_PREFIX = 'automatic-report-schedule:'
HISTORY_PREFIX = 'report-run-history:'
AUDIT_KEY = 'migration-audit:0015_remove_daily_schedules'
KEEP_TABLES_OUT_OF_COUNT = {'app_settings', 'alembic_version'}

document = sa.JSON().with_variant(JSONB(), 'postgresql')
settings = sa.table('app_settings', sa.column('key', sa.String), sa.column('value', document))
queues = sa.table('batch_queue_sessions', sa.column('session_id', sa.String), sa.column('created_at', sa.DateTime(timezone=True)))
log = logging.getLogger('alembic.runtime.migration')


def say(message):
    log.info(message)
    print(message, flush=True)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str)


def table_counts(bind):
    inspector = sa.inspect(bind)
    return {name: bind.execute(sa.text(f'SELECT count(*) FROM "{name}"')).scalar_one()
            for name in sorted(inspector.get_table_names()) if name not in KEEP_TABLES_OUT_OF_COUNT}


def schedule_rows(bind, daily):
    repeat = settings.c.value['repeat'].as_string()
    condition = (repeat == 'daily') if daily else sa.or_(repeat.is_(None), repeat != 'daily')
    query = sa.select(settings.c.key, settings.c.value).where(settings.c.key.like(SCHEDULE_PREFIX + '%'), condition)
    if daily:
        query = query.with_for_update()
    return bind.execute(query.order_by(settings.c.key)).all()


def progress_snapshot(value):
    total, done = value.get('total') or 0, value.get('done') or 0
    return {'status': value.get('status'), 'totalCases': total, 'processed': done,
            'withData': value.get('withData') or 0, 'noData': value.get('noData') or 0,
            'failed': value.get('failed') or 0, 'pending': max(total - done, 0), 'running': 0,
            'lastActivityAt': value.get('updatedAt'), 'finishedAt': value.get('lastFinishedAt'),
            'source': 'migration-0015'}


def preserve_history(bind, value):
    for session_id in sorted({value.get('sessionId'), value.get('lastSessionId')} - {None}):
        started_at = bind.execute(sa.select(queues.c.created_at).where(queues.c.session_id == session_id)).scalar()
        if started_at is None:
            continue
        bind.execute(sa.text(
            'INSERT INTO app_settings (key, value) VALUES (:key, CAST(:value AS jsonb)) ON CONFLICT (key) DO NOTHING'),
            {'key': HISTORY_PREFIX + session_id, 'value': canonical({
                'profileId': str(value.get('profileId')), 'filterName': value.get('profileName'),
                'startedAt': started_at.isoformat(), 'progress': progress_snapshot(value)})})


def upgrade():
    bind = op.get_bind()
    counts_before = table_counts(bind)
    others_before = {key: canonical(value) for key, value in schedule_rows(bind, daily=False)}
    daily = schedule_rows(bind, daily=True)
    removed = [{'id': key.removeprefix(SCHEDULE_PREFIX), 'owner': value.get('owner'),
                'profileName': value.get('profileName'), 'status': value.get('status'),
                'hadActiveSession': bool(value.get('sessionId'))} for key, value in daily]
    for _, value in daily:
        preserve_history(bind, value)
    if daily:
        bind.execute(sa.delete(settings).where(settings.c.key.in_([key for key, _ in daily])))

    if table_counts(bind) != counts_before:
        raise RuntimeError('0015_remove_daily_schedules would change a table other than app_settings; aborting.')
    if {key: canonical(value) for key, value in schedule_rows(bind, daily=False)} != others_before:
        raise RuntimeError('0015_remove_daily_schedules would change a non-Daily schedule; aborting.')
    if schedule_rows(bind, daily=True):
        raise RuntimeError('0015_remove_daily_schedules left Daily schedules behind; aborting.')

    say(f'0015_remove_daily_schedules: deleted {len(removed)} Daily schedule(s); kept {len(others_before)} '
        f'Once/Monthly schedule(s); ids={[item["id"] for item in removed]}')
    if removed:
        previous = bind.execute(sa.select(settings.c.value).where(settings.c.key == AUDIT_KEY)).scalar()
        entries = (previous or {}).get('removed', []) + removed
        bind.execute(sa.text('DELETE FROM app_settings WHERE key = :key'), {'key': AUDIT_KEY})
        bind.execute(sa.text('INSERT INTO app_settings (key, value) VALUES (:key, CAST(:value AS jsonb))'),
                     {'key': AUDIT_KEY, 'value': canonical({
                         'migration': revision, 'decision': 'D-35', 'count': len(entries), 'removed': entries,
                         'keptNonDailySchedules': len(others_before),
                         'at': datetime.now(timezone.utc).isoformat(timespec='seconds')})})


def downgrade():
    say('0015_remove_daily_schedules: downgrade does not restore deleted Daily schedules; use the pre-upgrade backup.')
