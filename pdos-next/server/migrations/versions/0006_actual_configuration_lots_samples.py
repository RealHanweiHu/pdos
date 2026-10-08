"""Preserve actual observations and single-unit identity apart from the Build plan."""

from alembic import op

from migrations.schema_0006 import SCHEMA_SQL, TABLES

revision = "next_0006"
down_revision = "next_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_build_fixed_plan_scope", "builds",
        ["tenant_id", "product_id", "project_id", "id",
         "engineering_configuration_id", "manufacturing_configuration_id"],
    )
    for statement in SCHEMA_SQL:
        op.execute(statement)
    for name in TABLES:
        op.execute(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_scope ON "{name}" '
            "USING (tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid)"
        )
        op.execute(f'GRANT SELECT, INSERT ON "{name}" TO pdos_next_app')
        op.execute(
            f'CREATE TRIGGER fixed_snapshot BEFORE UPDATE OR DELETE ON "{name}" '
            "FOR EACH ROW EXECUTE FUNCTION protect_next_snapshot()"
        )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pdos_agent")


def downgrade():
    for name in reversed(TABLES):
        op.drop_table(name)
    op.drop_constraint("uq_build_fixed_plan_scope", "builds", type_="unique")
