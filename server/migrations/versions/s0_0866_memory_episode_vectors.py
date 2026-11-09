"""Persist optional episode vectors and their outbound receipts for M2a (P85 第 3 项).

Placeholder number written in a parallel worktree on s0_0861; renumber to the
real head at integration (不可协商项 3).
"""

from alembic import op

from migrations.schema_s0_0866 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0866"
down_revision = "s0_0865"
branch_labels = depends_on = None


def upgrade():
    ordinary_owner()
    for sql in SCHEMA_SQL:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    for sql in DOWNGRADE_SQL:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")
