"""Project status, manufacturing documents and physical handoff fixed-source support."""

from alembic import op
from migrations.schema_s0_0849 import (
    DOWNGRADE_SQL,
    EMPTY_HISTORY_SQL,
    NATIVE_FUNCTIONS,
    PREVIOUS_FUNCTIONS,
    SCHEMA_SQL,
)
from migrations.versions.s0_0778_native_pilot import require_functions
from migrations.versions.s0_0843_dingtalk import administrative_migrator

revision = "s0_0849"
down_revision = "s0_0848"
branch_labels = depends_on = None


def execute(statements):
    for sql in statements:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})


def upgrade():
    administrative_migrator()
    require_functions(op.get_bind(), PREVIOUS_FUNCTIONS)
    execute(SCHEMA_SQL)


def downgrade():
    administrative_migrator()
    execute(EMPTY_HISTORY_SQL)
    require_functions(op.get_bind(), NATIVE_FUNCTIONS)
    execute(DOWNGRADE_SQL)
