"""Durable PostgreSQL schema. JSONB retains complete versioned application payloads."""
from sqlalchemy import (
    MetaData, Table, Column, String, Text, Boolean, Integer, BigInteger,
    DateTime, LargeBinary, ForeignKey, JSON, Index, UniqueConstraint,
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
