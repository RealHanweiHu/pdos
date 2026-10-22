"""Preserve project privacy in newly admitted relative-service Runs."""

from alembic import op

from migrations.schema_s0_0794 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0794"
down_revision = "s0_0793"
branch_labels = None
depends_on = None


def _apply(statements):
    ordinary_owner()
    for statement in statements:
        op.get_bind().exec_driver_sql(statement, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def upgrade():
    _apply(SCHEMA_SQL)


def downgrade():
    _apply(DOWNGRADE_SQL)
