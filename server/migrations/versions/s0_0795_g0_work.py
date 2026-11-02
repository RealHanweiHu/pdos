"""Continue native G0 project open items through existing controlled tasks."""

from alembic import op

from migrations.schema_s0_0795 import DOWNGRADE_SQL, G0_FUNCTIONS, PREVIOUS_FUNCTIONS, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner, require_functions

revision = "s0_0795"
down_revision = "s0_0794"
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
    if (
        op.get_bind()
        .exec_driver_sql(
            "SELECT EXISTS(SELECT 1 FROM work_task_versions WHERE g0_open_item_id IS NOT NULL)"
        )
        .scalar()
    ):
        raise RuntimeError("Native G0 task history exists; downgrade would discard its source")
    _apply(G0_FUNCTIONS, DOWNGRADE_SQL)
