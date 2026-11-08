"""Owner flags for the LangGraph checkpoint retention purge (D58)."""

from alembic import op

from migrations.schema_s0_0857 import DOWN_SQL, UP_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0857"
down_revision = "s0_0856"
branch_labels = depends_on = None


def _apply(statements):
    ordinary_owner()
    connection = op.get_bind()
    for statement in statements:
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def upgrade():
    _apply(UP_SQL)


def downgrade():
    _apply(DOWN_SQL)
