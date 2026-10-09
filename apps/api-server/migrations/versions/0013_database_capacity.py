"""Relational job query keys and indexes for bounded worker/report traffic."""
from alembic import op
from sqlalchemy import text

revision = '0013_database_capacity'
down_revision = '0012_auth_session_limits'
branch_labels = None
depends_on = None

INDEXES = {
    'ix_jobs_session_created': 'jobs (session_id, created_at, id)',
    'ix_jobs_owner_created': 'jobs (owner_username, created_at DESC, id)',
    'ix_jobs_retry_of': 'jobs (retry_of_job_id) WHERE retry_of_job_id IS NOT NULL',
    'ix_jobs_active': "jobs (runner_id, session_id) WHERE status NOT IN ('COMPLETED','NO_DATA','FAILED','CANCELLED')",
    'ix_queue_session_status_position': 'batch_queue_tasks (session_id, status, position)',
    'ix_main_reports_scope_year_order': 'main_reports (scope_key, year, lower(state), lower(rto), lower(maker), id)',
    'ix_report_history_scope_imported': 'report_update_history (scope_key, imported_at DESC, source_key)',
    'ix_report_history_years': 'report_update_history USING gin (years)',
    'ix_job_events_job_created': 'job_events (job_id, created_at)',
    'ix_audit_events_created': 'audit_events (created_at DESC, id)',
    'ix_report_sessions_owner_created': 'report_sessions (owner_username, created_at DESC, id)',
    'ix_stored_files_kind_job_created': 'stored_files (kind, job_id, created_at DESC)',
}


def upgrade():
    # Idempotent DDL permits retry after an interrupted concurrent index build.
    op.execute("SET LOCAL lock_timeout = '5s'")
    for column, kind in [('case_id', 'varchar(36)'), ('retry_of_job_id', 'varchar(36)'),
                         ('scenario_name', 'text'), ('source', "varchar(16) NOT NULL DEFAULT 'new'")]:
        op.execute(f'ALTER TABLE jobs ADD COLUMN IF NOT EXISTS {column} {kind}')
    op.execute("""UPDATE jobs SET
        case_id = NULLIF(payload->>'case_id', ''),
        retry_of_job_id = NULLIF(payload->>'retry_of_job_id', ''),
        scenario_name = payload->>'scenario_name',
        source = COALESCE(payload->>'source', 'new')
        WHERE case_id IS DISTINCT FROM NULLIF(payload->>'case_id', '')
           OR retry_of_job_id IS DISTINCT FROM NULLIF(payload->>'retry_of_job_id', '')
           OR scenario_name IS DISTINCT FROM payload->>'scenario_name'
           OR source IS DISTINCT FROM COALESCE(payload->>'source', 'new')""")
    for table in ('jobs', 'batch_queue_tasks', 'main_reports', 'report_update_history'):
        op.execute(f'ALTER TABLE {table} SET (autovacuum_vacuum_scale_factor=0.05, autovacuum_analyze_scale_factor=0.02)')
    with op.get_context().autocommit_block():
        connection = op.get_bind()
        for name, definition in INDEXES.items():
            valid = connection.scalar(text('SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)'), {'name': name})
            if valid is False:
                op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS {name}')
            op.execute(f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {definition}')
    for table in ('jobs', 'batch_queue_tasks', 'main_reports', 'report_update_history'):
        op.execute(f'ANALYZE {table}')


def downgrade():
    with op.get_context().autocommit_block():
        for name in reversed(INDEXES):
            op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS {name}')
    for table in ('jobs', 'batch_queue_tasks', 'main_reports', 'report_update_history'):
        op.execute(f'ALTER TABLE {table} RESET (autovacuum_vacuum_scale_factor, autovacuum_analyze_scale_factor)')
    for column in ('source', 'scenario_name', 'retry_of_job_id', 'case_id'):
        op.drop_column('jobs', column)
