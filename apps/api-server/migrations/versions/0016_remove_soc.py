"""Retire the collector delivery queue while retaining application audit history.

Historical revision IDs stay valid for databases upgraded before this removal.
Downgrade restores the queue schema; discarded delivery records are not restored.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0016_remove_soc'
down_revision = '0014_merge_capacity_soc'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table('soc_outbox', if_exists=True)


def downgrade():
    op.create_table('soc_outbox',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('payload', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('delivered', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('delivered_at', sa.DateTime(timezone=True)),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_soc_delivery', 'soc_outbox', ['next_attempt_at'],
                    postgresql_where=sa.text('NOT delivered'))
