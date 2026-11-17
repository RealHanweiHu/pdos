"""Assigned s0_0893 on s0_0892 at the 11-16 memory integration (placeholder s0_0900, branch
claude/memory-note-contract; file names, revision and down_revision moved together).

Personal memory notes on the unified item contract (P121 第 6 项后半, D512).

占位号：s0_0900 是并行工作区（分支 claude/memory-note-contract）的占位号，接在真实 head
s0_0892 之后写成。集成时按真实 head 重排：revision、down_revision、快照文件
schema_s0_0900.py 的文件名（及下面的 import）和快照里降级守卫的文字一起改（不可协商项 3）。
"""

from alembic import op

from migrations.schema_s0_0893 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0893"
down_revision = "s0_0892"
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
