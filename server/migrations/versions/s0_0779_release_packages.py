"""Fixed release preparation packages and separate named decision ledgers."""

from alembic import op

from migrations.schema_s0_0779 import (
    DOWNGRADE_SQL,
    PREVIOUS_FUNCTIONS,
    RELEASE_FUNCTIONS,
    SCHEMA_SQL,
)
from migrations.versions.s0_0778_native_pilot import ordinary_owner, require_functions

revision = "s0_0779"
down_revision = "s0_0778"
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
    require_functions(connection, RELEASE_FUNCTIONS)
    for statement in DOWNGRADE_SQL:
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")
