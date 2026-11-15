"""Owner-deleted Sessions leave memory; episode usage lists the notes used (P121 第 8 项, D475).

PLACEHOLDER NUMBER: written in a parallel worktree on head s0_0887 and moved onto
s0_0888 on 2026-11-14. At integration the revision, down_revision and the snapshot
file name move together to the real head (不可协商项 3).
"""

from alembic import op

from migrations.schema_s0_0940 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0940"
down_revision = "s0_0888"
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
