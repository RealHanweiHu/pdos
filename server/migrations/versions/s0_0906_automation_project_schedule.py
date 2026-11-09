"""Schedule rules may bind one project for the status-update cadence (P34-6, P65, D75).

Placeholder s0_0906 after s0_0905 (assigned range s0_0905–s0_0909); renumbered to
the actual head at integration (revision, down_revision and snapshot file together).
"""

from alembic import op

from migrations.schema_s0_0906 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0906"
down_revision = "s0_0905"
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
