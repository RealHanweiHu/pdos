"""Aggregate health counters for the monitoring probe (D213).

Written as placeholder s0_0879 on a parallel branch; renumbered to s0_0867 after
M2a's s0_0866 at the 11-09 integration (AGENTS.md migration rule).
"""

from alembic import op

from migrations.schema_s0_0867 import DOWN_SQL, UP_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0867"
down_revision = "s0_0866"
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
