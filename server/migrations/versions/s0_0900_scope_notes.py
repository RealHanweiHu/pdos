"""Persist scope notes for M2b (P87; P121 第 3、4、6 项).

占位号: placeholder s0_0900 on head s0_0887, written in a parallel worktree on
2026-11-13 (the main session holds s0_0888). At integration this revision,
down_revision, the snapshot file name and its downgrade guard text are renumbered
together to the real head (不可协商项 3).
"""

from alembic import op

from migrations.schema_s0_0900 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0900"
down_revision = "s0_0887"
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
