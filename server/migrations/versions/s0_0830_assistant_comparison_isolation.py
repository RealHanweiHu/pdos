"""Register a physically separate read-only surface for parsed document comparison."""

from alembic import op

from migrations.schema_s0_0830 import (
    PREVIOUS_CHECK,
    PREVIOUS_GUARD,
    REPAIRED_CHECK,
    REPAIRED_GUARD,
)
from migrations.versions.s0_0778_native_pilot import ordinary_owner, require_functions

revision = "s0_0830"
down_revision = "s0_0829"
branch_labels = depends_on = None


def install(check, guard):
    connection = op.get_bind()
    op.execute("ALTER TABLE public.agent_tool_calls DROP CONSTRAINT kernel_execution_binding_shape")
    connection.exec_driver_sql(
        "ALTER TABLE public.agent_tool_calls ADD CONSTRAINT kernel_execution_binding_shape "
        + check,
        execution_options={"no_parameters": True},
    )
    connection.exec_driver_sql(guard, execution_options={"no_parameters": True})


def upgrade():
    ordinary_owner()
    require_functions(op.get_bind(), {"kernel_read_guard()": PREVIOUS_GUARD})
    install(REPAIRED_CHECK, REPAIRED_GUARD)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    require_functions(op.get_bind(), {"kernel_read_guard()": REPAIRED_GUARD})
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.agent_tool_calls
      WHERE execution_binding->>'isolation'='assistant_compare') THEN
      RAISE EXCEPTION 'Assistant comparison history requires s0_0830'; END IF; END $$""")
    install(PREVIOUS_CHECK, PREVIOUS_GUARD)
    op.execute("SET LOCAL ROLE NONE")
