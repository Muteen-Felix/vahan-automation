"""Recoverable deletion of report sessions from run history."""
from alembic import op
import sqlalchemy as sa

revision = '0004_session_trash'
down_revision = '0003_annual_reports'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('report_sessions', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('report_sessions', 'deleted_at')
