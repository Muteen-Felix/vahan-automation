"""Bound dashboard sessions; old non-expiring sessions require a new login."""
from alembic import op
import sqlalchemy as sa

revision = '0012_auth_session_limits'
down_revision = '0011_ui_contract'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('auth_sessions', sa.Column('expires_at', sa.DateTime(timezone=True)))
    op.add_column('auth_sessions', sa.Column('last_activity_at', sa.DateTime(timezone=True)))
    op.execute("UPDATE auth_sessions SET revoked = TRUE, expires_at = created_at + INTERVAL '12 hours', last_activity_at = created_at")
    op.alter_column('auth_sessions', 'expires_at', nullable=False)
    op.alter_column('auth_sessions', 'last_activity_at', nullable=False)


def downgrade():
    op.drop_column('auth_sessions', 'last_activity_at')
    op.drop_column('auth_sessions', 'expires_at')
