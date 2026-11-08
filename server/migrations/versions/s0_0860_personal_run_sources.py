"""P91: a personal Run may pin its Human requester's currently readable sources.

Placeholder revision s0_0860; re-sequence onto the actual head at integration.
"""

from alembic import op

from migrations.schema_s0_0860 import (
    DOWNGRADE_SQL,
    EMPTY_HISTORY_SQL,
    PERSONAL_FUNCTIONS,
    PREVIOUS_FUNCTIONS,
    SCHEMA_SQL,
)
from migrations.versions.s0_0778_native_pilot import require_functions
from migrations.versions.s0_0843_dingtalk import administrative_migrator

revision = "s0_0860"
down_revision = "s0_0855"
branch_labels = depends_on = None


def execute(statements):
    for sql in statements:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})


def upgrade():
    administrative_migrator()
    op.execute("LOCK TABLE public.agent_runs IN SHARE ROW EXCLUSIVE MODE")
    require_functions(op.get_bind(), PREVIOUS_FUNCTIONS)
    execute(SCHEMA_SQL)
    require_functions(op.get_bind(), PERSONAL_FUNCTIONS)


def downgrade():
    administrative_migrator()
    execute(EMPTY_HISTORY_SQL)
    require_functions(op.get_bind(), PERSONAL_FUNCTIONS)
    execute(DOWNGRADE_SQL)
    require_functions(op.get_bind(), PREVIOUS_FUNCTIONS)
