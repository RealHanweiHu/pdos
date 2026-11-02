"""Preserve waiting history and fix JSONB calendar-source containment operands."""

from alembic import op

from migrations.schema_s0_0797 import CALENDAR_FUNCTIONS, PREVIOUS_FUNCTIONS
from migrations.versions.s0_0778_native_pilot import ordinary_owner, require_functions

revision = "s0_0797"
down_revision = "s0_0796"
branch_labels = None
depends_on = None


def _apply(expected, functions):
    ordinary_owner()
    connection = op.get_bind()
    require_functions(connection, expected)
    for statement in functions.values():
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def upgrade():
    _apply(PREVIOUS_FUNCTIONS, CALENDAR_FUNCTIONS)


def downgrade():
    _apply(CALENDAR_FUNCTIONS, PREVIOUS_FUNCTIONS)
