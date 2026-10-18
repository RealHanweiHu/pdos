"""Named service authorization and persistent automatic trigger admission."""

from alembic import op

from migrations.schema_s0_0787 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0787"
down_revision = "s0_0786"
branch_labels = None
depends_on = None


def _apply(statements):
    ordinary_owner()
    connection = op.get_bind()
    for statement in statements:
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def upgrade():
    _apply(SCHEMA_SQL)


def downgrade():
    _apply(DOWNGRADE_SQL)
