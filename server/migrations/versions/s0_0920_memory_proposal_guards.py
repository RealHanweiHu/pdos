"""Suppression fingerprints and discussion voids for memory proposals (P121 第 8 项).

占位号：并行工作区在真实 head s0_0887 上写成（主会话占用 s0_0888）。集成时按真实 head
重排：revision、down_revision 与快照文件 schema_s0_0920.py 的文件名一起改（不可协商项 3）。
"""

from alembic import op

from migrations.schema_s0_0920 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0920"
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
