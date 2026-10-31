"""Keep deterministic own-summary channel copies bound to the original approved Run."""

from alembic import op
from migrations.schema_s0_0852 import (
    BASE_SQL,
    DOWN_SQL,
    LIFECYCLE_UP_SQL,
    NATIVE_FUNCTIONS,
    PREVIOUS_FUNCTIONS,
)
from migrations.versions.s0_0778_native_pilot import require_functions
from migrations.versions.s0_0843_dingtalk import administrative_migrator

revision = "s0_0852"
down_revision = "s0_0851"
branch_labels = depends_on = None


def execute(statements):
    for statement in statements:
        op.get_bind().exec_driver_sql(statement, execution_options={"no_parameters": True})


def upgrade():
    administrative_migrator()
    require_functions(op.get_bind(), PREVIOUS_FUNCTIONS)
    execute(BASE_SQL)
    execute(LIFECYCLE_UP_SQL)
    require_functions(op.get_bind(), NATIVE_FUNCTIONS)


def downgrade():
    administrative_migrator()
    op.execute("LOCK TABLE public.dingtalk_summary_deliveries IN ACCESS EXCLUSIVE MODE")
    require_functions(op.get_bind(), NATIVE_FUNCTIONS)
    execute(DOWN_SQL)
    require_functions(op.get_bind(), PREVIOUS_FUNCTIONS)
