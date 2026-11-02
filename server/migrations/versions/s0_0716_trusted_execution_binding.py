"""Bind T0 execution to actual model result and loaded skill facts."""

from alembic import op

from migrations.schema_s0_0716 import DOWNGRADE_SQL, UPGRADE_SQL

revision = "s0_0716"
down_revision = "s0_0715"
branch_labels = None
depends_on = None


def upgrade():
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade():
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
