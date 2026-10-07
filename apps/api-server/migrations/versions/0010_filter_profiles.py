"""Saved filter definitions and short, crash-safe options reservations."""
from alembic import op
from app.db import schema

revision = '0010_filter_profiles'
down_revision = '0009_queue_worker_count'
branch_labels = None
depends_on = None

def upgrade():
    schema.filter_profiles.create(op.get_bind())
    schema.runner_planning_leases.create(op.get_bind())

def downgrade():
    schema.runner_planning_leases.drop(op.get_bind())
    schema.filter_profiles.drop(op.get_bind())
