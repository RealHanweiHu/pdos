"""Aggregate health counters for the monitoring probe (D213).

Placeholder number s0_0879 for this parallel branch; integration renumbers it to the
real head at that time (AGENTS.md migration rule).
"""

from alembic import op

from migrations.schema_s0_0879 import DOWN_SQL, UP_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0879"
down_revision = "s0_0861"
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
