"""Verified UI contract versions and run preflight records."""
from alembic import op
from app.db import schema
revision='0011_ui_contract'
down_revision='0010_filter_profiles'
branch_labels=None
depends_on=None
def upgrade():
    schema.ui_contract_versions.create(op.get_bind());schema.ui_preflight_checks.create(op.get_bind())
def downgrade():
    schema.ui_preflight_checks.drop(op.get_bind());schema.ui_contract_versions.drop(op.get_bind())
