"""Working-day estimate and readable status-update cadence (D71/D190, D75, P34-6).

Assigned s0_0871 after s0_0870 at the 11-10 integration (placeholder s0_0905 in the
range s0_0905–s0_0909; revision, down_revision and snapshot file moved together).
"""

from alembic import op

from migrations.schema_s0_0871 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0871"
down_revision = "s0_0870"
branch_labels = depends_on = None


def _execute(statements):
    for sql in statements:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})


def upgrade():
    ordinary_owner()
    _execute(SCHEMA_SQL)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    _execute(DOWNGRADE_SQL)
    op.execute("SET LOCAL ROLE NONE")
