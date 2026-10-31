"""Keep authorized native field location while retaining lifecycle scope fences."""

from alembic import op

from migrations.schema_s0_0828 import PREVIOUS_FUNCTION, REPAIRED_FUNCTION
from migrations.versions.s0_0778_native_pilot import ordinary_owner, require_functions

revision = "s0_0828"
down_revision = "s0_0827"
branch_labels = depends_on = None


def upgrade():
    ordinary_owner()
    require_functions(op.get_bind(), {"lifecycle_reference_gate()": PREVIOUS_FUNCTION})
    op.get_bind().exec_driver_sql(REPAIRED_FUNCTION, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    require_functions(op.get_bind(), {"lifecycle_reference_gate()": REPAIRED_FUNCTION})
    op.get_bind().exec_driver_sql(PREVIOUS_FUNCTION, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")
