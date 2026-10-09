"""Dedicated tenant identity, MFA, durable rate limits and SOC delivery."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from app.db import schema as db

revision = '0013_soc_controls'
down_revision = '0012_auth_session_limits'
branch_labels = None
depends_on = None


# Preserve the historical schema independently of current application metadata.
# Databases already on this branch must still upgrade through this revision.
legacy_outbox = sa.Table('soc_outbox', sa.MetaData(),
    sa.Column('id', sa.String(36), primary_key=True),
    sa.Column('payload', JSONB(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('delivered', sa.Boolean(), nullable=False, server_default='false'),
    sa.Column('delivered_at', sa.DateTime(timezone=True)),
    sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False))
sa.Index('ix_soc_delivery', legacy_outbox.c.next_attempt_at,
         postgresql_where=sa.text('NOT delivered'))


def upgrade():
    for table in [db.deployment_identity, db.user_mfa, db.security_rate_limits, legacy_outbox]:
        table.create(op.get_bind(), checkfirst=True)
    # Old sessions predate tenant binding and mandatory MFA. Do not upgrade
    # them silently to a stronger assurance level.
    op.execute('UPDATE auth_sessions SET revoked = TRUE')


def downgrade():
    for table in [legacy_outbox, db.security_rate_limits, db.user_mfa, db.deployment_identity]:
        table.drop(op.get_bind(), checkfirst=True)
