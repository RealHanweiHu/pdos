"""Retain native project sources without adding them to explicit material bindings."""

from alembic import op
from migrations.schema_s0_0850 import (
    DOWNGRADE_SQL,
    EMPTY_HISTORY_SQL,
    NATIVE_FUNCTIONS,
    NATIVE_POLICY_USING,
    POLICY_DOWN_SQL,
    POLICY_UP_SQL,
    PREVIOUS_FUNCTIONS,
    PREVIOUS_POLICY_USING,
    SCHEMA_SQL,
)
from migrations.versions.s0_0778_native_pilot import require_functions
from migrations.versions.s0_0843_dingtalk import administrative_migrator
from sqlalchemy import text

revision = "s0_0850"
down_revision = "s0_0849"
branch_labels = depends_on = None


def execute(statements):
    for sql in statements:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})


def require_policy(expected):
    actual = op.get_bind().scalar(text(
        "SELECT pg_get_expr(polqual,polrelid) FROM pg_policy "
        "WHERE polrelid='public.agent_runs'::regclass AND polname='kernel_source_audience'"
    ))
    if actual != expected:
        raise RuntimeError("Project source audience policy differs from the frozen predecessor")


def upgrade():
    administrative_migrator()
    op.execute("LOCK TABLE public.agent_runs IN SHARE ROW EXCLUSIVE MODE")
    require_policy(PREVIOUS_POLICY_USING)
    require_functions(op.get_bind(), PREVIOUS_FUNCTIONS)
    execute(SCHEMA_SQL)
    op.execute(POLICY_UP_SQL)
    require_policy(NATIVE_POLICY_USING)


def downgrade():
    administrative_migrator()
    execute(EMPTY_HISTORY_SQL)
    require_policy(NATIVE_POLICY_USING)
    require_functions(op.get_bind(), NATIVE_FUNCTIONS)
    execute(DOWNGRADE_SQL)
    op.execute(POLICY_DOWN_SQL)
    require_policy(PREVIOUS_POLICY_USING)
