"""Read actual visible project fact receipts with source RLS intact."""

from alembic import op
from sqlalchemy import text

from migrations.schema_s0_0792 import DOWNGRADE_SQL, SCHEMA_SQL, SOURCE_TABLES
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0792"
down_revision = "s0_0791"
branch_labels = None
depends_on = None


def _apply(statements):
    ordinary_owner()
    connection = op.get_bind()
    for name in SOURCE_TABLES:
        guard = connection.execute(
            text(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                "WHERE oid=to_regclass(:name)"
            ),
            {"name": "public." + name},
        ).one()
        if not all(guard):
            raise RuntimeError("Project activity sources require enabled and forced RLS")
    for statement in statements:
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})
    op.execute("SET LOCAL ROLE NONE")


def upgrade():
    _apply(SCHEMA_SQL)


def downgrade():
    _apply(DOWNGRADE_SQL)
