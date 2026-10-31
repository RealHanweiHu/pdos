"""Personal knowledge targets preserve original Runs and retained contributions."""

from alembic import op
from migrations.schema_s0_0841 import (
    DOWNGRADE_SQL,
    EMPTY_HISTORY_SQL,
    NATIVE_FUNCTIONS,
    PREVIOUS_FUNCTIONS,
    SCHEMA_SQL,
)
from migrations.versions.s0_0778_native_pilot import ordinary_owner, require_functions

revision = "s0_0841"
down_revision = "s0_0840"
branch_labels = depends_on = None


def execute(statements):
    for sql in statements:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})


def upgrade():
    ordinary_owner()
    require_functions(op.get_bind(), PREVIOUS_FUNCTIONS)
    execute(SCHEMA_SQL)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    execute(EMPTY_HISTORY_SQL)
    ordinary_owner()
    require_functions(op.get_bind(), NATIVE_FUNCTIONS)
    execute(DOWNGRADE_SQL)
    op.execute("SET LOCAL ROLE NONE")
