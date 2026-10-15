"""Persist the selected concurrency for each queue; old sessions retain ten."""
from alembic import op
import sqlalchemy as sa

revision = '0009_queue_worker_count'
down_revision = '0008_shared_batch_queue'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('batch_queue_sessions', sa.Column('max_workers', sa.Integer(), nullable=False, server_default='10'))
    op.create_check_constraint('ck_batch_queue_worker_count', 'batch_queue_sessions', 'max_workers BETWEEN 1 AND 10')

def downgrade():
    op.drop_constraint('ck_batch_queue_worker_count', 'batch_queue_sessions', type_='check')
    op.drop_column('batch_queue_sessions', 'max_workers')
