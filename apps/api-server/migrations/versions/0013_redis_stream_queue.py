"""Use a durable SQL outbox for Redis worker notifications and remove the ten-worker ceiling."""
from alembic import op
import sqlalchemy as sa


revision = '0013_redis_stream_queue'
down_revision = '0012_auth_session_limits'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('ck_batch_queue_worker_count', 'batch_queue_sessions', type_='check')
    op.create_check_constraint('ck_batch_queue_worker_count', 'batch_queue_sessions', 'max_workers >= 1')
    op.alter_column('batch_queue_sessions', 'max_workers', existing_type=sa.Integer(), server_default='1')
    op.create_table(
        'queue_outbox',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_queue_outbox_pending', 'queue_outbox', ['published_at', 'id'])
    op.execute("""
        INSERT INTO queue_outbox (session_id, position, created_at)
        SELECT session_id, position, CURRENT_TIMESTAMP
        FROM batch_queue_tasks
        WHERE status IN ('PENDING', 'PROCESSING')
    """)


def downgrade():
    op.drop_index('ix_queue_outbox_pending', table_name='queue_outbox')
    op.drop_table('queue_outbox')
    op.execute("UPDATE batch_queue_sessions SET max_workers = 10 WHERE max_workers > 10")
    op.alter_column('batch_queue_sessions', 'max_workers', existing_type=sa.Integer(), server_default='10')
    op.drop_constraint('ck_batch_queue_worker_count', 'batch_queue_sessions', type_='check')
    op.create_check_constraint('ck_batch_queue_worker_count', 'batch_queue_sessions', 'max_workers BETWEEN 1 AND 10')
