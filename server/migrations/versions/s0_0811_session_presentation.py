"""Append-only human-owned session presentation without changing execution history."""

from alembic import op

from migrations.schema_s0_0811 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0811"
down_revision = "s0_0810"
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
    ordinary_owner()
    if op.get_bind().exec_driver_sql(
        "SELECT EXISTS(SELECT 1 FROM public.agent_session_presentations)"
    ).scalar():
        raise RuntimeError("Session presentation history exists; downgrade would discard it")
    for statement in DOWNGRADE_SQL:
        op.get_bind().exec_driver_sql(statement, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")
