"""Stop the upgrade while a saved Daily schedule still owns a report session (PLAN D-35, Q1 = A).

Runs immediately before ``0015_remove_daily_schedules``. If any ``automatic-report-schedule:*`` row has
``repeat = 'daily'`` and a non-empty ``sessionId`` the migration raises *before anything is written*, so the
whole upgrade rolls back: no schedule is deleted, no history or audit row is written and ``alembic_version``
stays where it was. The operator must let the run finish (preferred), or Stop/Delete the schedule on the old
version, and then upgrade again (docs/release/INSTALL.md section 7).

The condition deliberately ignores ``status``: ``status`` may be missing, ``null`` or unrecognised, and a
``status NOT IN (...)`` test would skip such rows in SQL. The text of ``DAILY_BLOCKING_SQL`` must stay identical
to ``DAILY_BLOCKING_SQL`` in ``scripts/deployment_guard.py`` (``--check-release``); the test
``verification/test_daily_schedule_removal.py`` checks both.

This revision only protects databases that have not applied ``0015`` yet. It has no schema effect and nothing to
downgrade.
"""
import logging

import sqlalchemy as sa
from alembic import op

revision = '0014a_daily_schedule_guard'
down_revision = '0014_postgresql_task_claims'
branch_labels = None
depends_on = None

SCHEDULE_LIKE = 'automatic-report-schedule:%'
DAILY_BLOCKING_SQL = "value->>'repeat' = 'daily' AND COALESCE(value->>'sessionId', '') <> ''"
log = logging.getLogger('alembic.runtime.migration')


def blocking_schedules(bind):
    # Same condition as deployment_guard.DAILY_BLOCKING_SQL. Only identifying, non-sensitive fields are read:
    # never the filter ``definition``.
    return bind.execute(sa.text(
        "SELECT key, value->>'owner', value->>'profileName', value->>'status' FROM app_settings "
        f"WHERE key LIKE :prefix AND {DAILY_BLOCKING_SQL} ORDER BY key"), {'prefix': SCHEDULE_LIKE}).all()


def upgrade():
    blocked = blocking_schedules(op.get_bind())
    if not blocked:
        return
    listing = '; '.join(
        f"id={key.removeprefix('automatic-report-schedule:')} owner={owner!r} name={name!r} status={status!r}"
        for key, owner, name, status in blocked)
    message = (
        f'0014a_daily_schedule_guard: {len(blocked)} saved Daily schedule(s) still own a report session; '
        'migration 0015 would delete them and leave the session without a schedule. Nothing was changed. '
        'On the OLD version let the run finish (preferred), or Stop or Delete the schedule, then upgrade again. '
        f'Schedules: {listing}')
    log.error(message)
    raise RuntimeError(message)


def downgrade():
    # No schema or data effect.
    pass
