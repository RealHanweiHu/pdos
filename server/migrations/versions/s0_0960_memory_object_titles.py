"""占位号，集成时按真实 head 重排。D482 余项 ① object titles; D300 every active vector space."""

from alembic import op

from migrations.schema_s0_0960 import DOWN_SQL, UP_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0960"
down_revision = "s0_0888"
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
