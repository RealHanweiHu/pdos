"""Bind internal query embeddings to the actual main model READ and Run budget."""

from alembic import op

from migrations.schema_s0_0838 import DOWNGRADE_SQL, EMPTY_HISTORY_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0838"
down_revision = "s0_0837"
branch_labels = depends_on = None


def execute(statements):
    for sql in statements:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})


def upgrade():
    ordinary_owner()
    execute(SCHEMA_SQL)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    execute(EMPTY_HISTORY_SQL)
    ordinary_owner()
    execute(DOWNGRADE_SQL)
    op.execute("SET LOCAL ROLE NONE")
