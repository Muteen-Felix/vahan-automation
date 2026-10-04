"""Store confirmed State/RTO outcomes and DOM table rows with full timestamps."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0002_report_results'
down_revision = '0001_durable_state'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('report_results',
        sa.Column('job_id', sa.String(36), sa.ForeignKey('jobs.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('result', sa.String(16), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('states', JSONB(), nullable=False), sa.Column('rtos', JSONB(), nullable=False),
        sa.Column('filters', JSONB(), nullable=False), sa.Column('page_url', sa.Text(), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('saved_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False), sa.Column('tables', JSONB(), nullable=False))
    op.create_index('ix_report_results_result', 'report_results', ['result'])
    op.create_table('report_rows',
        sa.Column('job_id', sa.String(36), sa.ForeignKey('report_results.job_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('table_index', sa.Integer(), primary_key=True),
        sa.Column('row_number', sa.Integer(), primary_key=True),
        sa.Column('section', sa.String(8), nullable=False),
        sa.Column('cells', JSONB(), nullable=False), sa.Column('spans', JSONB(), nullable=False))


def downgrade():
    op.drop_table('report_rows')
    op.drop_table('report_results')
