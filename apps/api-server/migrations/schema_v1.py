# Frozen initial schema. Add a new Alembic revision for subsequent changes.
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
    Column("created_at", DateTime(timezone=True), nullable=False))
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
file_rows = Table("file_rows", metadata,
    Column("file_id", ForeignKey("stored_files.id", ondelete="CASCADE"), primary_key=True),
    Column("sheet", String(128), primary_key=True), Column("row_number", Integer, primary_key=True),
    Column("cells", document, nullable=False))
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
