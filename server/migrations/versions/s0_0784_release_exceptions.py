"""Independent named bounded exceptions and withdrawals."""

from alembic import op
from sqlalchemy import text

from migrations.schema_s0_0784 import (
    DOWNGRADE_SQL,
    EXCEPTION_DEADLINE,
    EXCEPTION_FUNCTIONS,
    PREVIOUS_DEADLINE,
    PREVIOUS_FUNCTIONS,
    SCHEMA_SQL,
)
from migrations.versions.s0_0778_native_pilot import ordinary_owner, require_functions

revision = "s0_0784"
down_revision = "s0_0783"
branch_labels = None
depends_on = None


def _apply(functions, deadline, statements):
    ordinary_owner()
    connection = op.get_bind()
    connection.exec_driver_sql("LOCK TABLE public.confirmations IN ACCESS EXCLUSIVE MODE")
    actual = connection.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='public.confirmations'::regclass "
            "AND conname='ck_confirmations_decision_deadline'"
        )
    )
    if actual != deadline:
        raise RuntimeError("Release exception requires its exact reviewed confirmation predecessor")
    require_functions(connection, functions)
    for statement in statements:
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def upgrade():
    _apply(PREVIOUS_FUNCTIONS, PREVIOUS_DEADLINE, SCHEMA_SQL)


def downgrade():
    _apply(EXCEPTION_FUNCTIONS, EXCEPTION_DEADLINE, DOWNGRADE_SQL)
