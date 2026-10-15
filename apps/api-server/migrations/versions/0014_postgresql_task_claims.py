"""Use the PostgreSQL task table as the worker queue without Redis outbox."""
from alembic import op
import sqlalchemy as sa


revision = '0014_postgresql_task_claims'
down_revision = '0013_redis_stream_queue'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index('ix_queue_outbox_pending', table_name='queue_outbox')
    op.drop_table('queue_outbox')


def downgrade():
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
        SELECT task.session_id, task.position, CURRENT_TIMESTAMP
        FROM batch_queue_tasks AS task
        JOIN batch_queue_sessions AS session USING (session_id)
        WHERE session.status = 'RUNNING'
          AND task.status IN ('PENDING', 'PROCESSING')
    """)
