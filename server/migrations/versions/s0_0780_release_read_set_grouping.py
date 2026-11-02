"""Group release JSON operands before read-set containment comparisons."""

from alembic import op
from sqlalchemy import text

from migrations.schema_s0_0780 import FUNCTION, PREVIOUS_DEFINITION, REPLACEMENT_DEFINITION
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0780"
down_revision = "s0_0779"
branch_labels = None
depends_on = None


def _replace(expected, replacement):
    ordinary_owner()
    connection = op.get_bind()
    actual = connection.scalar(
        text("SELECT pg_get_functiondef(to_regprocedure(:signature))"),
        {"signature": "public." + FUNCTION},
    )
    if actual != expected:
        raise RuntimeError("Release correction requires its exact reviewed predecessor")
    connection.exec_driver_sql(replacement, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def upgrade():
    _replace(PREVIOUS_DEFINITION, REPLACEMENT_DEFINITION)


def downgrade():
    _replace(REPLACEMENT_DEFINITION, PREVIOUS_DEFINITION)
