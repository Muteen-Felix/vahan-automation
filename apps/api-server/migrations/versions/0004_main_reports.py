"""Consolidate monthly facts into the main table; retain update history only."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0004_main_reports'
down_revision = '0003_annual_reports'
branch_labels = None
depends_on = None
MONTHS = ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')


def upgrade():
    op.create_table('main_reports',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('owner_key', sa.String(128), nullable=False),
        sa.Column('scope_key', sa.String(64), nullable=False),
        sa.Column('scope_label', sa.Text(), nullable=False), sa.Column('filters', JSONB(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('state', sa.Text(), nullable=False), sa.Column('rto', sa.Text(), nullable=False),
        sa.Column('rto_code', sa.String(64), nullable=False), sa.Column('maker', sa.Text(), nullable=False),
        *[sa.Column(month, sa.BigInteger(), nullable=True) for month in MONTHS],
        sa.Column('month_sources', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    for column in ('owner_key', 'scope_key', 'year'):
        op.create_index('ix_main_reports_' + column, 'main_reports', [column])
    op.create_table('report_update_history',
        sa.Column('source_key', sa.String(80), primary_key=True),
        sa.Column('owner_key', sa.String(128), nullable=False),
        sa.Column('scope_key', sa.String(64), nullable=False),
        sa.Column('scope_label', sa.Text(), nullable=False), sa.Column('filters', JSONB(), nullable=False),
        sa.Column('job_id', sa.String(36), sa.ForeignKey('jobs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.Text(), nullable=False), sa.Column('status', sa.String(24), nullable=False),
        sa.Column('years', JSONB(), nullable=False), sa.Column('states', JSONB(), nullable=False),
        sa.Column('rtos', JSONB(), nullable=False), sa.Column('details', JSONB(), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('imported_at', sa.DateTime(timezone=True), nullable=False))
    for column in ('owner_key', 'scope_key', 'imported_at'):
        op.create_index('ix_report_update_history_' + column, 'report_update_history', [column])
    columns = ', '.join(MONTHS)
    pivots = ', '.join(f'max(c.value) FILTER (WHERE c.month={i}) AS {month}' for i, month in enumerate(MONTHS, 1))
    op.execute(f"""INSERT INTO main_reports
        (id,owner_key,scope_key,scope_label,filters,year,state,rto,rto_code,maker,{columns},month_sources,created_at,updated_at)
        SELECT r.id,d.owner_key,r.dataset_id,d.label,d.filters,r.year,r.state,r.rto,r.rto_code,r.maker,
        {pivots}, COALESCE(jsonb_object_agg(c.month::text,
            jsonb_build_object('sourceKey',c.source_key,'observedAt',c.observed_at))
            FILTER (WHERE c.month IS NOT NULL),'{{}}'::jsonb),r.created_at,r.updated_at
        FROM annual_records r JOIN annual_datasets d ON d.id=r.dataset_id
        LEFT JOIN annual_cells c ON c.record_id=r.id GROUP BY r.id,d.id""")
    op.execute("""INSERT INTO report_update_history
        (source_key,owner_key,scope_key,scope_label,filters,job_id,name,status,years,states,rtos,details,observed_at,imported_at)
        SELECT i.source_key,d.owner_key,i.dataset_id,d.label,d.filters,i.job_id,i.name,i.status,
        i.years,i.states,i.rtos,i.details || CASE WHEN f.sha256 IS NOT NULL
            THEN jsonb_build_object('checksum',f.sha256) ELSE '{}'::jsonb END,i.observed_at,i.imported_at
        FROM annual_imports i JOIN annual_datasets d ON d.id=i.dataset_id
        LEFT JOIN stored_files f ON f.id=i.file_id""")
    # Verify every value and its original source/time before removing the redundant tables.
    values = ','.join(f"({i},r.{month})" for i, month in enumerate(MONTHS, 1))
    op.execute(f"""DO $$ BEGIN
        IF (SELECT count(*) FROM main_reports) <> (SELECT count(*) FROM annual_records)
           OR (SELECT count(*) FROM report_update_history) <> (SELECT count(*) FROM annual_imports)
           OR EXISTS (SELECT record_id,month,value,source_key,observed_at FROM annual_cells EXCEPT
             SELECT r.id,v.month,v.value,r.month_sources->v.month::text->>'sourceKey',
             (r.month_sources->v.month::text->>'observedAt')::timestamptz
             FROM main_reports r CROSS JOIN LATERAL (VALUES {values}) v(month,value) WHERE v.value IS NOT NULL)
           OR (SELECT count(*) FROM annual_cells) <>
             (SELECT count(*) FROM main_reports r CROSS JOIN LATERAL (VALUES {values}) v(month,value) WHERE v.value IS NOT NULL)
        THEN RAISE EXCEPTION 'Main-report migration verification failed; all changes were rolled back.';
        END IF; END $$""")
    op.execute("""UPDATE jobs j SET payload=j.payload || jsonb_build_object(
        'result_checksum',r.sha256,'main_report_saved_at',r.saved_at,
        'main_report_checksum',CASE WHEN r.result='DATA' THEN f.sha256 ELSE NULL END,
        'main_report_summary',COALESCE(i.details,'{}'::jsonb),
        'excel_file_name',NULL,'excel_file_size',NULL,'no_data_file_name',NULL)
        FROM report_results r LEFT JOIN LATERAL
          (SELECT sha256 FROM stored_files WHERE job_id=r.job_id AND kind='excel' LIMIT 1) f ON TRUE
        LEFT JOIN LATERAL
          (SELECT details FROM report_update_history WHERE job_id=r.job_id ORDER BY imported_at DESC LIMIT 1) i ON TRUE
        WHERE j.id=r.job_id""")
    for table in ('annual_cells', 'annual_imports', 'annual_records', 'annual_datasets',
                  'report_rows', 'report_results', 'file_rows'):
        op.drop_table(table)
    # The deployment takes and verifies a database backup first. CAPTCHA/failure artifacts remain operational.
    op.execute("DELETE FROM stored_files WHERE kind IN ('excel','no-data') OR (kind IN ('artifact','screenshot') AND name='result.png')")


def downgrade():
    raise RuntimeError('Restore the verified pre-migration backup to recover retired Excel/DOM snapshots.')
