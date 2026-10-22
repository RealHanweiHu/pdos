"""Category-level reference gates and inherited model audiences."""

from alembic import op

from migrations.schema_s0_0002 import SQL

revision = "s0_0002"
down_revision = "s0_0001"
branch_labels = None
depends_on = None


def upgrade():
    for statement in SQL:
        op.execute(statement)


def downgrade():
    for statement in reversed(SQL):
        if statement.startswith("CREATE POLICY model_audience"):
            table = statement.split('"')[1]
            op.execute(f'DROP POLICY model_audience ON "{table}"')
    op.execute("DROP TRIGGER a_protect_category ON grants")
    op.execute("DROP TRIGGER category_owner_immutable ON categories")
    op.execute("DROP FUNCTION protect_category_owner()")
    op.execute(
        "CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON grants "
        "FOR EACH ROW EXECUTE FUNCTION lifecycle_reference_gate()"
    )
    from migrations.schema_s0_0001 import SCHEMA_SQL

    original = next(
        sql
        for sql in SCHEMA_SQL
        if sql.startswith("CREATE OR REPLACE FUNCTION public.lifecycle_reference_gate()")
    )
    op.execute(original)
