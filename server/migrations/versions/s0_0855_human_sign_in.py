"""Human sign-in with passwords, one-time invitations and revocable sessions (D214/D86/D192)."""

from alembic import op

from migrations.schema_s0_0855 import DOWN_SQL, UP_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0855"
down_revision = "s0_0854"
branch_labels = depends_on = None


def execute(statements):
    for statement in statements:
        op.get_bind().exec_driver_sql(statement, execution_options={"no_parameters": True})


def upgrade():
    ordinary_owner()
    execute(UP_SQL)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    execute(DOWN_SQL)
    op.execute("SET LOCAL ROLE NONE")
