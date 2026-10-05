"""Track all-State Maker snapshots and focused State/RTO refreshes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0007_maker_incremental_update'
down_revision = '0006_shared_main_reports'
branch_labels = None
depends_on = None
MONTHS = ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')


def upgrade():
    op.create_table('maker_global_reports',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('scope_key', sa.String(64), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('maker', sa.Text(), nullable=False),
        *(sa.Column(month, sa.BigInteger(), nullable=True) for month in MONTHS),
        sa.Column('total', sa.BigInteger(), nullable=False),
        sa.Column('source_job_id', sa.String(36), sa.ForeignKey('jobs.id', ondelete='SET NULL')),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('scope_key', 'year', 'maker', name='uq_maker_global_scope_year_maker'))
    op.create_index('ix_maker_global_reports_scope_key', 'maker_global_reports', ['scope_key'])
    op.create_index('ix_maker_global_reports_year', 'maker_global_reports', ['year'])
    op.create_table('maker_office_index',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('scope_key', sa.String(64), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('maker', sa.Text(), nullable=False),
        sa.Column('state', sa.Text(), nullable=False),
        sa.Column('rto', sa.Text(), nullable=False),
        sa.Column('rto_code', sa.String(64), nullable=False),
        *(sa.Column(month, sa.BigInteger(), nullable=True) for month in MONTHS),
        sa.Column('total', sa.BigInteger(), nullable=False),
        sa.Column('source_job_id', sa.String(36), sa.ForeignKey('jobs.id', ondelete='SET NULL')),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_maker_office_index_scope_key', 'maker_office_index', ['scope_key'])
    op.create_index('ix_maker_office_index_year', 'maker_office_index', ['year'])
    op.create_index('ix_maker_office_lookup', 'maker_office_index', ['scope_key', 'year', 'maker'])
    op.create_table('maker_update_runs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_username', sa.String(128), sa.ForeignKey('users.username'), index=True),
        sa.Column('scope_key', sa.String(64), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('changed_makers', JSONB(), nullable=False),
        sa.Column('states', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_maker_update_runs_scope_key', 'maker_update_runs', ['scope_key'])
    op.create_table('maker_update_tasks',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('maker_update_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('maker', sa.Text(), nullable=False),
        sa.Column('state', sa.Text(), nullable=False),
        sa.Column('rto', sa.Text(), nullable=False),
        sa.Column('rto_code', sa.String(64), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('job_id', sa.String(36), sa.ForeignKey('jobs.id', ondelete='SET NULL')),
        sa.Column('error', sa.Text()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_maker_update_tasks_run_id', 'maker_update_tasks', ['run_id'])


def downgrade():
    op.drop_table('maker_update_tasks')
    op.drop_table('maker_update_runs')
    op.drop_table('maker_office_index')
    op.drop_table('maker_global_reports')
