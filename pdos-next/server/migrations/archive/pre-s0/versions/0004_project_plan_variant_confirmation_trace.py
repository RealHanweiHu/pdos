"""Fixed variants, real projects/first plans, material T1 review and call trace."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.schema_0004 import SCHEMA_SQL, TABLES

revision = "next_0004"
down_revision = "next_0003"
branch_labels = None
depends_on = None

ADDITIONS = {
    "confirmations": [("payload_digest", sa.String(64), None), ("snapshot", JSONB(), None)],
    "model_invocations": [("call_id", sa.Uuid(), None)],
    "model_budget_reservations": [
        ("revision", sa.Integer(), "1"),
        ("provider_version", sa.String(160), None),
        ("protocol", sa.String(32), None),
        ("route_digest", sa.String(64), None),
        ("request_id", sa.String(200), None),
        ("normalized_usage", JSONB(), None),
        ("settled_at", sa.DateTime(timezone=True), None),
        ("reconciliation_history", JSONB(), "'[]'::jsonb"),
    ],
}


def upgrade():
    for statement in SCHEMA_SQL:
        op.execute(statement)
    op.create_foreign_key(
        "fk_project_current_plan",
        "projects",
        "plan_revisions",
        ["tenant_id", "product_id", "id", "current_plan_id"],
        ["tenant_id", "product_id", "project_id", "id"],
    )
    for table, columns in ADDITIONS.items():
        for name, kind, initial in columns:
            op.add_column(
                table,
                sa.Column(
                    name,
                    kind,
                    nullable=initial is None,
                    server_default=sa.text(initial) if initial else None,
                ),
            )
            if initial is not None:
                op.alter_column(table, name, server_default=None)
    op.create_unique_constraint("uq_invocation_call", "model_invocations", ["tenant_id", "call_id"])
    op.execute("""
      CREATE FUNCTION protect_next_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'fixed business snapshots are immutable'; END $$
    """)
    for name in TABLES:
        op.execute(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_scope ON "{name}" '
            "USING (tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = nullif(current_setting('pdos.tenant_id', true), '')::uuid)"
        )
        ops = "SELECT, INSERT, UPDATE" if name == "projects" else "SELECT, INSERT"
        op.execute(f'GRANT {ops} ON "{name}" TO pdos_next_app')
        if name != "projects":
            op.execute(
                f'CREATE TRIGGER fixed_snapshot BEFORE UPDATE OR DELETE ON "{name}" '
                "FOR EACH ROW EXECUTE FUNCTION protect_next_snapshot()"
            )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pdos_agent")


def downgrade():
    op.drop_constraint("uq_invocation_call", "model_invocations", type_="unique")
    for table, columns in reversed(list(ADDITIONS.items())):
        for name, _, _ in reversed(columns):
            op.drop_column(table, name)
    op.drop_constraint("fk_project_current_plan", "projects", type_="foreignkey")
    for name in reversed(TABLES):
        op.drop_table(name)
    op.execute("DROP FUNCTION protect_next_snapshot()")
