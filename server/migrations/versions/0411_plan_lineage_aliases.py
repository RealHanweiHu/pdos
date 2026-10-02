"""Preserve plan/recertification lineage guards without trigger OLD alias collisions."""

from alembic import op
from sqlalchemy import text

revision = "0411_plan_lineage_aliases"
down_revision = "0410_feedback_guard_compat"
branch_labels = None
depends_on = None

GUARDS = (
    ("cehub_project.guard_schedule_time_record()", "cehub_project.schedule_time_records"),
    ("cehub_project.guard_baseline_change_application()", "cehub_project.schedule_time_records"),
    ("cehub_project.guard_recertification_provenance()", "cehub_quality.certifications"),
)


def rewrite(*, forward: bool) -> None:
    source, target = ("old", "prior_record") if forward else ("prior_record", "old")
    for name, table in GUARDS:
        definition = str(
            op.get_bind()
            .execute(text("SELECT pg_get_functiondef(CAST(:name AS regprocedure))"), {"name": name})
            .scalar_one()
        )
        alias = f"{table} {source}"
        if definition.count(alias) != 1 or f"{source}.tenant_id" not in definition:
            raise RuntimeError(f"Expected lineage guard is unavailable: {name}")
        # Trigger records are uppercase OLD/NEW in the original definitions.
        # Only the lowercase SQL alias changes; lineage and approval checks remain.
        op.execute(
            definition.replace(alias, f"{table} {target}").replace(f"{source}.", f"{target}.")
        )


def upgrade() -> None:
    rewrite(forward=True)


def downgrade() -> None:
    rewrite(forward=False)
