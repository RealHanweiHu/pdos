"""Permit pre-model category originals with exact source and security scope."""
from alembic import op
from migrations.schema_s0_0406 import UPGRADE_SQL, DOWNGRADE_SQL
revision = "s0_0406"
down_revision = "s0_0405"
branch_labels = None
depends_on = None

def upgrade():
    for statement in UPGRADE_SQL:
        op.execute(statement)

def downgrade():
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
