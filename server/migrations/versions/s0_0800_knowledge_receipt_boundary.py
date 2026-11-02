"""Register named knowledge confirmation and dispatch receipt ACL by real type."""

from alembic import op
from sqlalchemy import text

from migrations.schema_s0_0800 import (
    DOWNGRADE_SQL,
    KNOWLEDGE_FUNCTIONS,
    NEW_CHECK,
    OLD_CHECKS,
    SCHEMA_SQL,
)
from migrations.versions.s0_0778_native_pilot import ordinary_owner, require_functions

revision = "s0_0800"
down_revision = "s0_0799"
branch_labels = None
depends_on = None


def _apply(expected, statements):
    ordinary_owner()
    connection = op.get_bind()
    actual = connection.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='public.confirmations'::regclass "
            "AND conname='ck_confirmations_decision_deadline'"
        )
    )
    if actual not in (expected if isinstance(expected, tuple) else (expected,)):
        raise RuntimeError(
            "Knowledge migration requires the reviewed confirmation deadline constraint"
        )
    for statement in statements:
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def upgrade():
    _apply(OLD_CHECKS, SCHEMA_SQL)


def downgrade():
    require_functions(op.get_bind(), KNOWLEDGE_FUNCTIONS)
    _apply(NEW_CHECK, DOWNGRADE_SQL)
