"""Independent tasks, per-recipient commitments and named project updates."""

from alembic import op

from migrations.schema_s0_0785 import DOWNGRADE_SQL, PREVIOUS_FUNCTIONS, SCHEMA_SQL, WORK_FUNCTIONS
from migrations.versions.s0_0778_native_pilot import ordinary_owner, require_functions

revision = "s0_0785"
down_revision = "s0_0784"
branch_labels = None
depends_on = None


def _apply(expected, statements):
    ordinary_owner()
    connection = op.get_bind()
    require_functions(connection, expected)
    for statement in statements:
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def upgrade():
    _apply(PREVIOUS_FUNCTIONS, SCHEMA_SQL)


def downgrade():
    _apply(WORK_FUNCTIONS, DOWNGRADE_SQL)
