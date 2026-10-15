"""Runner-state revision fencing, preflight gate generation and a server-issued check sequence.

Additive only (PLAN_STATE_VAHAN WP-S / WP-G):

* ``browser_states.revision``: monotonic counter; ``PUT /api/runner-state`` becomes a
  compare-and-swap so a write built from an older revision cannot commit after a newer one.
* ``ui_preflight_checks.gate_generation``: a PASS preflight is only accepted while it carries the
  current gate generation (stored in ``app_settings``); retire / invalidate bump the generation.
* ``ui_health_check_seq``: server-issued, strictly increasing order for health checks, so a late
  observation cannot overwrite a newer one (no dependence on the runner wall clock).

Old API and runner code ignore the new columns and sequence, so the migration is safe to apply
before the API and runners are replaced. The downgrade drops the additions; application rollback
does not require it.
"""
import sqlalchemy as sa
from alembic import op

revision = '0016_state_revision_gate_gen'
down_revision = '0015_remove_daily_schedules'
branch_labels = None
depends_on = None


def _columns(table):
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    # 0011 creates ``ui_preflight_checks`` from the *current* app schema, so on a fresh database
    # the column already exists; only add what is missing (idempotent).
    if 'revision' not in _columns('browser_states'):
        op.add_column('browser_states', sa.Column('revision', sa.BigInteger(), nullable=False, server_default='0'))
    if 'gate_generation' not in _columns('ui_preflight_checks'):
        op.add_column('ui_preflight_checks', sa.Column('gate_generation', sa.Integer(), nullable=False, server_default='0'))
    op.execute('CREATE SEQUENCE IF NOT EXISTS ui_health_check_seq')


def downgrade():
    op.execute('DROP SEQUENCE IF EXISTS ui_health_check_seq')
    if 'gate_generation' in _columns('ui_preflight_checks'):
        op.drop_column('ui_preflight_checks', 'gate_generation')
    if 'revision' in _columns('browser_states'):
        op.drop_column('browser_states', 'revision')

