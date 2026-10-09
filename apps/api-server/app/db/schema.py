"""Durable PostgreSQL schema. JSONB retains complete versioned application payloads."""
from sqlalchemy import (
    MetaData, Table, Column, String, Text, Boolean, Integer, BigInteger,
    DateTime, LargeBinary, ForeignKey, JSON, Index, UniqueConstraint, CheckConstraint, text, func,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
document = JSON().with_variant(JSONB(), "postgresql")
users = Table("users", metadata,
    Column("username", String(128), primary_key=True),
    Column("password_hash", Text, nullable=False),
    Column("role", String(16), nullable=False),
    Column("active", Boolean, nullable=False),
    Column("profile", document, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False))
auth_sessions = Table("auth_sessions", metadata,
    Column("id", String(64), primary_key=True),
    Column("username", ForeignKey("users.username"), nullable=False, index=True),
    Column("revoked", Boolean, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("last_activity_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False))
report_sessions = Table("report_sessions", metadata,
    Column("id", String(36), primary_key=True),
    Column("owner_username", ForeignKey("users.username"), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("deleted_at", DateTime(timezone=True), nullable=True))
jobs = Table("jobs", metadata,
    Column("id", String(36), primary_key=True),
    Column("owner_username", ForeignKey("users.username"), nullable=True, index=True),
    Column("session_id", ForeignKey("report_sessions.id"), nullable=False, index=True),
    Column("runner_id", String(128), nullable=False, index=True),
    Column("status", String(32), nullable=False, index=True),
    Column('case_id', String(36)),
    Column('retry_of_job_id', String(36)),
    Column('scenario_name', Text),
    Column('source', String(16), nullable=False, server_default=text("'new'")),
    Column("filters", document, nullable=False),
    Column("payload", document, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False))
runners = Table("runners", metadata,
    Column("id", String(128), primary_key=True),
    Column("socket_id", String(128), nullable=True, unique=True),
    Column("connected", Boolean, nullable=False),
    Column("current_job_id", ForeignKey("jobs.id"), nullable=True),
    Column("payload", document, nullable=False))
batch_queue_sessions = Table("batch_queue_sessions", metadata,
    Column("session_id", ForeignKey("report_sessions.id", ondelete="CASCADE"), primary_key=True),
    Column("owner_username", ForeignKey("users.username"), nullable=False, index=True),
    Column("status", String(16), nullable=False),
    Column("total", Integer, nullable=False),
    Column("max_workers", Integer, nullable=False, server_default=text('10')),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint('max_workers BETWEEN 1 AND 10', name='ck_batch_queue_worker_count'))
batch_queue_tasks = Table("batch_queue_tasks", metadata,
    Column("session_id", ForeignKey("batch_queue_sessions.session_id", ondelete="CASCADE"), primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("scenario_name", Text, nullable=False),
    Column("filters", document, nullable=False),
    Column("status", String(16), nullable=False, index=True),
    Column("attempts", Integer, nullable=False),
    Column("failures", Integer, nullable=False),
    Column("runner_id", String(128)),
    Column("job_id", ForeignKey("jobs.id", ondelete="SET NULL")),
    Column("error", Text),
    Column("updated_at", DateTime(timezone=True), nullable=False))
Index('ix_batch_queue_claim', batch_queue_tasks.c.session_id, batch_queue_tasks.c.position,
      postgresql_where=text("status = 'PENDING'"))
Index('ix_batch_queue_job', batch_queue_tasks.c.job_id, unique=True,
      postgresql_where=text('job_id IS NOT NULL'))
job_events = Table("job_events", metadata,
    Column("id", String(36), primary_key=True),
    Column("job_id", ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("event", String(64), nullable=False),
    Column("payload", document, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False))
app_settings = Table("app_settings", metadata,
    Column("key", String(128), primary_key=True), Column("value", document, nullable=False))
user_state = Table("user_state", metadata,
    Column("username", ForeignKey("users.username"), primary_key=True),
    Column("key", String(128), primary_key=True),
    Column("value", document, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False))
filter_profiles = Table('filter_profiles', metadata,
    Column('id', String(36), primary_key=True),
    Column('owner_username', ForeignKey('users.username'), nullable=False, index=True),
    Column('name', String(120), nullable=False), Column('definition', document, nullable=False),
    Column('revision', Integer, nullable=False),
    Column('created_at', DateTime(timezone=True), nullable=False),
    Column('updated_at', DateTime(timezone=True), nullable=False))
runner_planning_leases = Table('runner_planning_leases', metadata,
    Column('runner_id', ForeignKey('runners.id', ondelete='CASCADE'), primary_key=True),
    Column('owner_username', ForeignKey('users.username'), nullable=False),
    Column('token', String(36), nullable=False), Column('expires_at', DateTime(timezone=True), nullable=False))
stored_files = Table("stored_files", metadata,
    Column("id", String(36), primary_key=True),
    Column("owner_username", ForeignKey("users.username"), nullable=True, index=True),
    Column("job_id", ForeignKey("jobs.id"), nullable=True, index=True),
    Column("kind", String(32), nullable=False), Column("name", Text, nullable=False),
    Column("mime_type", String(128), nullable=False),
    Column("size", BigInteger, nullable=False), Column("sha256", String(64), nullable=False, index=True),
    Column("content", LargeBinary, nullable=False), Column("metadata", document, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("job_id", "kind", "name", name="uq_job_file"))
ui_health_checks = Table("ui_health_checks", metadata,
    Column("id", String(128), primary_key=True), Column("check_date", String(10), nullable=False, index=True),
    Column("payload", document, nullable=False), Column("csv_row", document, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False))
browser_states = Table("browser_states", metadata,
    Column("runner_id", String(128), primary_key=True),
    Column("encrypted_state", LargeBinary, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False))
audit_events = Table('audit_events', metadata,
    Column('id', String(36), primary_key=True),
    Column('actor', String(128), nullable=True, index=True),
    Column('event', String(128), nullable=False, index=True),
    Column('payload', document, nullable=False),
    Column('created_at', DateTime(timezone=True), nullable=False))
Index("ix_jobs_filters_gin", jobs.c.filters, postgresql_using="gin")
deployment_identity = Table('deployment_identity', metadata,
    Column('id', Integer, primary_key=True),
    Column('tenant_id', String(64), nullable=False),
    CheckConstraint('id = 1', name='ck_single_deployment_identity'))
user_mfa = Table('user_mfa', metadata,
    Column('username', ForeignKey('users.username', ondelete='CASCADE'), primary_key=True),
    Column('secret', LargeBinary), Column('pending_secret', LargeBinary),
    Column('pending_expires_at', DateTime(timezone=True)),
    Column('last_counter', BigInteger, nullable=False, server_default='-1'),
    Column('recovery_hashes', document, nullable=False, server_default='[]'))
security_rate_limits = Table('security_rate_limits', metadata,
    Column('key', String(64), primary_key=True),
    Column('started_at', DateTime(timezone=True), nullable=False),
    Column('hits', Integer, nullable=False))
soc_outbox = Table('soc_outbox', metadata,
    Column('id', String(36), primary_key=True), Column('payload', document, nullable=False),
    Column('created_at', DateTime(timezone=True), nullable=False),
    Column('delivered', Boolean, nullable=False, server_default='false'),
    Column('delivered_at', DateTime(timezone=True)),
    Column('attempts', Integer, nullable=False, server_default='0'),
    Column('next_attempt_at', DateTime(timezone=True), nullable=False))
Index('ix_soc_delivery', soc_outbox.c.next_attempt_at,
      postgresql_where=text('NOT delivered'))
MONTH_COLUMNS = ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')
main_reports = Table('main_reports', metadata,
    Column('id', String(64), primary_key=True),
    Column('scope_key', String(64), nullable=False, index=True),
    Column('scope_label', Text, nullable=False), Column('filters', document, nullable=False),
    Column('year', Integer, nullable=False, index=True),
    Column('state', Text, nullable=False), Column('rto', Text, nullable=False),
    Column('rto_code', String(64), nullable=False), Column('maker', Text, nullable=False),
    *[Column(month, BigInteger, nullable=True) for month in MONTH_COLUMNS],
    Column('month_sources', document, nullable=False),
    Column('created_at', DateTime(timezone=True), nullable=False),
    Column('updated_at', DateTime(timezone=True), nullable=False))
report_update_history = Table('report_update_history', metadata,
    Column('source_key', String(80), primary_key=True),
    Column('owner_key', String(128), nullable=False, index=True),
    Column('scope_key', String(64), nullable=False, index=True),
    Column('scope_label', Text, nullable=False), Column('filters', document, nullable=False),
    Column('job_id', ForeignKey('jobs.id', ondelete='SET NULL'), nullable=True),
    Column('name', Text, nullable=False), Column('status', String(24), nullable=False),
    Column('years', document, nullable=False), Column('states', document, nullable=False),
    Column('rtos', document, nullable=False), Column('details', document, nullable=False),
    Column('observed_at', DateTime(timezone=True), nullable=False),
    Column('imported_at', DateTime(timezone=True), nullable=False, index=True))

# The all-State Maker workbook is a separate grain from main_reports (RTO/Maker).
maker_global_reports = Table('maker_global_reports', metadata,
    Column('id', String(64), primary_key=True),
    Column('scope_key', String(64), nullable=False, index=True),
    Column('year', Integer, nullable=False, index=True),
    Column('maker', Text, nullable=False),
    *[Column(month, BigInteger, nullable=True) for month in MONTH_COLUMNS],
    Column('total', BigInteger, nullable=False),
    Column('source_job_id', ForeignKey('jobs.id', ondelete='SET NULL'), nullable=True),
    Column('checksum', String(64), nullable=False),
    Column('observed_at', DateTime(timezone=True), nullable=False),
    Column('updated_at', DateTime(timezone=True), nullable=False),
    UniqueConstraint('scope_key', 'year', 'maker', name='uq_maker_global_scope_year_maker'))
maker_office_index = Table('maker_office_index', metadata,
    Column('id', String(64), primary_key=True),
    Column('scope_key', String(64), nullable=False, index=True),
    Column('year', Integer, nullable=False, index=True),
    Column('maker', Text, nullable=False),
    Column('state', Text, nullable=False),
    Column('rto', Text, nullable=False),
    Column('rto_code', String(64), nullable=False),
    *[Column(month, BigInteger, nullable=True) for month in MONTH_COLUMNS],
    Column('total', BigInteger, nullable=False),
    Column('source_job_id', ForeignKey('jobs.id', ondelete='SET NULL'), nullable=True),
    Column('observed_at', DateTime(timezone=True), nullable=False),
    Column('updated_at', DateTime(timezone=True), nullable=False))
Index('ix_maker_office_lookup', maker_office_index.c.scope_key,
      maker_office_index.c.year, maker_office_index.c.maker)
maker_update_runs = Table('maker_update_runs', metadata,
    Column('id', String(36), primary_key=True),
    Column('owner_username', ForeignKey('users.username'), nullable=True, index=True),
    Column('scope_key', String(64), nullable=False, index=True),
    Column('year', Integer, nullable=False),
    Column('status', String(32), nullable=False),
    Column('changed_makers', document, nullable=False),
    Column('states', document, nullable=False),
    Column('created_at', DateTime(timezone=True), nullable=False),
    Column('updated_at', DateTime(timezone=True), nullable=False))
maker_update_tasks = Table('maker_update_tasks', metadata,
    Column('id', String(64), primary_key=True),
    Column('run_id', ForeignKey('maker_update_runs.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('kind', String(16), nullable=False),
    Column('maker', Text, nullable=False),
    Column('state', Text, nullable=False),
    Column('rto', Text, nullable=False),
    Column('rto_code', String(64), nullable=False),
    Column('status', String(16), nullable=False),
    Column('job_id', ForeignKey('jobs.id', ondelete='SET NULL'), nullable=True),
    Column('error', Text, nullable=True),
    Column('updated_at', DateTime(timezone=True), nullable=False))

ui_contract_versions = Table('ui_contract_versions', metadata,
    Column('id', String(36), primary_key=True), Column('revision', Integer, nullable=False, unique=True),
    Column('fingerprint', String(64), nullable=False, unique=True), Column('controls', document, nullable=False),
    Column('created_at', DateTime(timezone=True), nullable=False))
ui_preflight_checks = Table('ui_preflight_checks', metadata,
    Column('id', String(36), primary_key=True), Column('owner_username', ForeignKey('users.username'), nullable=False),
    Column('runner_ids', document, nullable=False), Column('version_id', String(36)),
    Column('status', String(24), nullable=False), Column('reports', document, nullable=False),
    Column('created_at', DateTime(timezone=True), nullable=False))

# Query keys stay relational; large JSON/bytea values are never index INCLUDE columns.
Index('ix_jobs_session_created', jobs.c.session_id, jobs.c.created_at, jobs.c.id)
Index('ix_jobs_owner_created', jobs.c.owner_username, jobs.c.created_at.desc(), jobs.c.id)
Index('ix_jobs_retry_of', jobs.c.retry_of_job_id,
      postgresql_where=text('retry_of_job_id IS NOT NULL'))
Index('ix_jobs_active', jobs.c.runner_id, jobs.c.session_id,
      postgresql_where=text("status NOT IN ('COMPLETED','NO_DATA','FAILED','CANCELLED')"))
Index('ix_queue_session_status_position', batch_queue_tasks.c.session_id,
      batch_queue_tasks.c.status, batch_queue_tasks.c.position)
Index('ix_main_reports_scope_year_order', main_reports.c.scope_key, main_reports.c.year,
      func.lower(main_reports.c.state), func.lower(main_reports.c.rto),
      func.lower(main_reports.c.maker), main_reports.c.id)
Index('ix_report_history_scope_imported', report_update_history.c.scope_key,
      report_update_history.c.imported_at.desc(), report_update_history.c.source_key)
Index('ix_report_history_years', report_update_history.c.years, postgresql_using='gin')
Index('ix_job_events_job_created', job_events.c.job_id, job_events.c.created_at)
Index('ix_audit_events_created', audit_events.c.created_at.desc(), audit_events.c.id)
Index('ix_report_sessions_owner_created', report_sessions.c.owner_username,
      report_sessions.c.created_at.desc(), report_sessions.c.id)
Index('ix_stored_files_kind_job_created', stored_files.c.kind, stored_files.c.job_id,
      stored_files.c.created_at.desc())
