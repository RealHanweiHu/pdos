"""Immutable BOM, dual configuration, planned Build and readiness snapshots."""

from alembic import op

from migrations.schema_0005 import SCHEMA_SQL, TABLES

revision = "next_0005"
down_revision = "next_0004"
branch_labels = None
depends_on = None


def upgrade():
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
