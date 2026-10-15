"""Annual manufacturer data with immutable monthly cells and an import ledger."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0003_annual_reports'
down_revision = '0002_report_results'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('annual_datasets',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('owner_key', sa.String(128), nullable=False),
        sa.Column('label', sa.Text(), nullable=False), sa.Column('filters', JSONB(), nullable=False))
    op.create_index('ix_annual_datasets_owner_key', 'annual_datasets', ['owner_key'])
    op.create_table('annual_records',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('dataset_id', sa.String(64), sa.ForeignKey('annual_datasets.id'), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('state', sa.Text(), nullable=False), sa.Column('rto', sa.Text(), nullable=False),
        sa.Column('rto_code', sa.String(64), nullable=False), sa.Column('maker', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_annual_records_dataset_id', 'annual_records', ['dataset_id'])
    op.create_index('ix_annual_records_year', 'annual_records', ['year'])
    op.create_table('annual_imports',
        sa.Column('source_key', sa.String(80), primary_key=True),
        sa.Column('dataset_id', sa.String(64), sa.ForeignKey('annual_datasets.id'), nullable=False),
        sa.Column('file_id', sa.String(36), sa.ForeignKey('stored_files.id', ondelete='SET NULL'), nullable=True),
        sa.Column('job_id', sa.String(36), sa.ForeignKey('jobs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.Text(), nullable=False), sa.Column('status', sa.String(24), nullable=False),
        sa.Column('years', JSONB(), nullable=False), sa.Column('states', JSONB(), nullable=False),
        sa.Column('rtos', JSONB(), nullable=False), sa.Column('details', JSONB(), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('imported_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_annual_imports_dataset_id', 'annual_imports', ['dataset_id'])
    op.create_index('ix_annual_imports_imported_at', 'annual_imports', ['imported_at'])
    op.create_table('annual_cells',
        sa.Column('record_id', sa.String(64), sa.ForeignKey('annual_records.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('month', sa.Integer(), primary_key=True), sa.Column('value', sa.BigInteger(), nullable=False),
        sa.Column('source_key', sa.String(80), sa.ForeignKey('annual_imports.source_key'), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    for table in ['annual_cells', 'annual_imports', 'annual_records', 'annual_datasets']:
        op.drop_table(table)
