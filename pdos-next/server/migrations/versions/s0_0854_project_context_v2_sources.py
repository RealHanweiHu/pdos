"""Keep project v2 facts bound to actual frozen source footprints."""

from alembic import op

from migrations.schema_s0_0854 import DOWN_SQL, NATIVE_FUNCTIONS, PREVIOUS_FUNCTIONS, UP_SQL
from migrations.versions.s0_0778_native_pilot import require_functions
from migrations.versions.s0_0843_dingtalk import administrative_migrator

revision = "s0_0854"
down_revision = "s0_0853"
branch_labels = depends_on = None


def execute(statements):
    for statement in statements:
        op.get_bind().exec_driver_sql(statement, execution_options={"no_parameters": True})


def upgrade():
    administrative_migrator()
    require_functions(op.get_bind(), PREVIOUS_FUNCTIONS)
    execute(UP_SQL)
    require_functions(op.get_bind(), NATIVE_FUNCTIONS)


def downgrade():
    administrative_migrator()
    require_functions(op.get_bind(), NATIVE_FUNCTIONS)
    execute(DOWN_SQL)
    require_functions(op.get_bind(), PREVIOUS_FUNCTIONS)
