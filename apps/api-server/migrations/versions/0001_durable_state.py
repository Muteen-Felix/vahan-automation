"""Initial durable users, sessions, jobs, events, files, rows, settings and browser state."""
from alembic import op
from migrations.schema_v1 import metadata

revision = "0001_durable_state"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    metadata.create_all(op.get_bind())

def downgrade():
    metadata.drop_all(op.get_bind())
