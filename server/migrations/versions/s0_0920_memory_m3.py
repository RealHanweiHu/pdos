"""占位号 s0_0920（接真实 head s0_0892，分支 claude/memory-m3）：集成时按真实 head 重排，
revision、down_revision、快照文件 schema_s0_0920.py 的文件名与降级守卫文字一起改（不可协商项 3）。

记忆 M3 沉淀与改进：纠正四路分流、改版标待复核与复核转交、程序性修订候选与审核、
系统规则开关、维护台账（memory design §13 M3、§14.9；P88；target architecture §6.9）。
"""

from alembic import op

from migrations.schema_s0_0920 import DOWNGRADE_SQL, SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0920"
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
