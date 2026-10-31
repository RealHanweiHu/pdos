"""Knowledge source compatibility and DingTalk controlled metadata row locks."""

from alembic import op
from migrations.candidates.dingtalk_fence import DOWNGRADE_SQL as FENCE_DOWN
from migrations.candidates.dingtalk_fence import SCHEMA_SQL as FENCE_UP
from migrations.schema_s0_0845 import (
    DOWNGRADE_SQL,
    EMPTY_HISTORY_SQL,
    NATIVE_FUNCTIONS,
    PREVIOUS_FUNCTIONS,
    SCHEMA_SQL,
)
from migrations.versions.s0_0778_native_pilot import ordinary_owner, require_functions
from migrations.versions.s0_0843_dingtalk import administrative_migrator

revision = "s0_0845"
down_revision = "s0_0844"
branch_labels = depends_on = None


def execute(statements):
    for sql in statements:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})


def upgrade():
    administrative_migrator()
    ordinary_owner()
    require_functions(op.get_bind(), PREVIOUS_FUNCTIONS)
    execute(SCHEMA_SQL)
    administrative_migrator()
    execute(FENCE_UP)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    administrative_migrator()
    execute(EMPTY_HISTORY_SQL)
    ordinary_owner()
    require_functions(op.get_bind(), NATIVE_FUNCTIONS)
    execute(DOWNGRADE_SQL)
    administrative_migrator()
    execute(FENCE_DOWN)
    op.execute("SET LOCAL ROLE NONE")
