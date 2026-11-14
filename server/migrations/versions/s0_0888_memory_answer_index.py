"""D482: index 小Pai's answer summary beside the owner's own words (P121 第 1 项)."""

from alembic import op

from migrations.schema_s0_0888 import DOWN_SQL, UP_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0888"
down_revision = "s0_0887"
branch_labels = depends_on = None


def _execute(statements):
    for sql in statements:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})


def upgrade():
    ordinary_owner()
    _execute(UP_SQL)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    _execute(DOWN_SQL)
    op.execute("SET LOCAL ROLE NONE")
