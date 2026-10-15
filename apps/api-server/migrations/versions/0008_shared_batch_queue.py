"""Use one durable queue for parallel State/RTO reports."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0008_shared_batch_queue'
down_revision = '0007_maker_incremental_update'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('batch_queue_sessions',
        sa.Column('session_id', sa.String(36), sa.ForeignKey('report_sessions.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('owner_username', sa.String(128), sa.ForeignKey('users.username'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('total', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_batch_queue_sessions_owner_username', 'batch_queue_sessions', ['owner_username'])
    op.create_table('batch_queue_tasks',
        sa.Column('session_id', sa.String(36), sa.ForeignKey('batch_queue_sessions.session_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('position', sa.Integer(), primary_key=True),
        sa.Column('scenario_name', sa.Text(), nullable=False),
        sa.Column('filters', JSONB(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('failures', sa.Integer(), nullable=False),
        sa.Column('runner_id', sa.String(128)),
        sa.Column('job_id', sa.String(36), sa.ForeignKey('jobs.id', ondelete='SET NULL')),
        sa.Column('error', sa.Text()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_batch_queue_tasks_status', 'batch_queue_tasks', ['status'])
    op.create_index('ix_batch_queue_claim', 'batch_queue_tasks', ['session_id', 'position'],
        postgresql_where=sa.text("status = 'PENDING'"))
    op.create_index('ix_batch_queue_job', 'batch_queue_tasks', ['job_id'], unique=True,
        postgresql_where=sa.text('job_id IS NOT NULL'))


def downgrade():
    op.drop_table('batch_queue_tasks')
    op.drop_table('batch_queue_sessions')
