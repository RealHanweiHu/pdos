"""Stable failures, quality/CAPA drafts and fixed change impact graphs."""
# ruff: noqa: E501

from alembic import op
from sqlalchemy import text

from migrations.schema_0023 import (
    ATOMIC,
    FUNCTIONS,
    IMMUTABLE,
    PARENT_COLUMNS,
    PARENT_TABLES,
    POINTERS,
    SCHEMA_SQL,
    TABLES,
)

revision = "next_0023"
down_revision = "next_0022"
branch_labels = None
depends_on = None


def upgrade():
    for table in PARENT_TABLES:
        op.create_unique_constraint(f"uq_{table}_quality_scope", table, list(PARENT_COLUMNS))
    for statement in SCHEMA_SQL:
        op.execute(statement)
    for statement in FUNCTIONS.values():
        op.execute(statement)
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f"CREATE POLICY tenant_scope ON \"{table}\" USING (tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid) WITH CHECK (tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid)"
        )
        permissions = "SELECT,INSERT,UPDATE" if table in POINTERS else "SELECT,INSERT"
        op.execute(f'GRANT {permissions} ON "{table}" TO pdos_next_app')
        op.execute(
            f'CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON "{table}" FOR EACH ROW EXECUTE FUNCTION lifecycle_reference_gate()'
        )
        if table in IMMUTABLE:
            op.execute(
                f'CREATE TRIGGER retained_record BEFORE UPDATE OR DELETE ON "{table}" FOR EACH ROW EXECUTE FUNCTION protect_next_snapshot()'
            )
        if table in POINTERS:
            op.execute(
                f'CREATE TRIGGER exact_current BEFORE INSERT OR UPDATE OR DELETE ON "{table}" FOR EACH ROW EXECUTE FUNCTION {POINTERS[table]}()'
            )
        if table in ATOMIC:
            op.execute(
                f'CREATE CONSTRAINT TRIGGER quality_change_required AFTER INSERT ON "{table}" DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_quality_change_atom()'
            )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pdos_agent")


def downgrade():
    if any(op.get_bind().scalar(text(f'SELECT count(*) FROM "{table}"')) for table in TABLES):
        raise RuntimeError("Retained quality/change history prevents destructive downgrade")
    for table in reversed(TABLES):
        op.drop_table(table)
    for name in reversed(FUNCTIONS):
        signature = (
            "(uuid,uuid,uuid,integer,text,text,uuid,text)"
            if name == "assert_quality_change_receipt"
            else "()"
        )
        op.execute(f"DROP FUNCTION {name}{signature}")
    for table in PARENT_TABLES:
        op.drop_constraint(f"uq_{table}_quality_scope", table, type_="unique")
