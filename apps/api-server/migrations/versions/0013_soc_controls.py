"""Dedicated tenant identity, MFA, durable rate limits and SOC delivery."""
from alembic import op
from app.db import schema as db

revision = '0013_soc_controls'
down_revision = '0012_auth_session_limits'
branch_labels = None
depends_on = None


def upgrade():
    for table in [db.deployment_identity, db.user_mfa, db.security_rate_limits, db.soc_outbox]:
        table.create(op.get_bind(), checkfirst=True)
    # Old sessions predate tenant binding and mandatory MFA. Do not upgrade
    # them silently to a stronger assurance level.
    op.execute('UPDATE auth_sessions SET revoked = TRUE')


def downgrade():
    for table in [db.soc_outbox, db.security_rate_limits, db.user_mfa, db.deployment_identity]:
        table.drop(op.get_bind(), checkfirst=True)
