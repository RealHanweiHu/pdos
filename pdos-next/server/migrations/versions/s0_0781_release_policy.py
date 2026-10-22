"""Controlled release policies for fixed packages and separate decisions."""

from alembic import op

from migrations.schema_s0_0781 import (
    DOWNGRADE_SQL,
    POLICY_FUNCTIONS,
    PREVIOUS_FUNCTIONS,
    SCHEMA_SQL,
)
from migrations.versions.s0_0778_native_pilot import ordinary_owner, require_functions

revision = "s0_0781"
down_revision = "s0_0780"
branch_labels = None
depends_on = None


def upgrade():
    ordinary_owner()
    connection = op.get_bind()
    require_functions(connection, PREVIOUS_FUNCTIONS)
    for statement in SCHEMA_SQL:
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    connection = op.get_bind()
    require_functions(connection, POLICY_FUNCTIONS)
    for statement in DOWNGRADE_SQL:
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")
