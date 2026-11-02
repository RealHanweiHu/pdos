"""Category keys, material versions, private promotion proofs and creation confirmation."""

from alembic import op
from sqlalchemy import text

from migrations.schema_s0_0730 import DOWNGRADE_SQL, SCHEMA_SQL, TABLES

revision = "s0_0730"
down_revision = "s0_0729"
branch_labels = None
depends_on = None


def ordinary_owner():
    connection = op.get_bind()
    role = connection.execute(
        text(
            "SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolcanlogin FROM pg_roles "
            "WHERE rolname='pdos_next_owner'"
        )
    ).one_or_none()
    if role is None or any(role):
        raise RuntimeError("Pre-provisioned ordinary pdos_next_owner is required")
    if connection.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname IN "
            "('pdos_next_app','pdos_next_auth','pdos_next_dispatch','pdos_agent') "
            "AND pg_has_role(rolname,'pdos_next_owner','MEMBER'))"
        )
    ):
        raise RuntimeError("Runtime roles must not inherit the schema owner")
    op.execute("SET LOCAL ROLE pdos_next_owner")


def upgrade():
    ordinary_owner()
    for statement in SCHEMA_SQL:
        op.execute(statement)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    connection = op.get_bind()
    # Hold every affected data surface until the transaction completes. A writer
    # cannot create new material between the preservation check and DDL removal.
    affected = (
        *TABLES,
        "categories",
        "category_knowledge_entries",
        "category_knowledge_current",
        "proposal_prepared_candidates",
        "proposals",
        "definition_specs",
        "action_receipts",
    )
    names = ", ".join(f'"{name}"' for name in sorted(affected))
    op.execute(f"LOCK TABLE {names} IN ACCESS EXCLUSIVE MODE")
    checks = [f'SELECT EXISTS(SELECT 1 FROM "{name}" LIMIT 1)' for name in TABLES]
    checks += [
        "SELECT EXISTS(SELECT 1 FROM categories WHERE created_by_run_id IS NOT NULL "
        "OR key IS DISTINCT FROM 'category-'||replace(id::text,'-',''))",
        "SELECT EXISTS(SELECT 1 FROM category_knowledge_entries "
        "WHERE prepared_candidate_id IS NOT NULL)",
        "SELECT EXISTS(SELECT 1 FROM proposal_prepared_candidates "
        "WHERE operation IN ('category.knowledge.add','category.knowledge.withdraw',"
        "'category.knowledge.promote','category.parameter.publish'))",
        "SELECT EXISTS(SELECT 1 FROM action_receipts "
        "WHERE operation IN ('category.knowledge.add','category.knowledge.withdraw',"
        "'category.knowledge.promote','category.parameter.publish'))",
    ]
    for query in checks:
        if connection.scalar(text(query)):
            raise RuntimeError(
                "M3 materials downgrade refuses new business data; preserve material history"
            )
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
    op.execute("SET LOCAL ROLE NONE")
