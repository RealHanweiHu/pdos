"""Align supply recovery arithmetic and disambiguate scenario lineage aliases."""

from alembic import op
from sqlalchemy import text

revision = "0410_feedback_guard_compat"
down_revision = "0409_product_master_references"
branch_labels = None
depends_on = None

OLD_COVERAGE = (
    " (NEW.snapshot#>>'{basis,material,allocated_on_hand}')::numeric <\n"
    " (NEW.snapshot#>>'{basis,material,required}')::numeric"
)
NEW_COVERAGE = (
    " (coalesce((NEW.snapshot#>>'{basis,material,qualified_issued}')::numeric,0) < 0 OR\n"
    " (NEW.snapshot#>>'{basis,material,allocated_on_hand}')::numeric +\n"
    " coalesce((NEW.snapshot#>>'{basis,material,qualified_issued}')::numeric,0) <\n"
    " (NEW.snapshot#>>'{basis,material,required}')::numeric)"
)


def definition(name: str) -> str:
    return str(
        op.get_bind()
        .execute(text("SELECT pg_get_functiondef(CAST(:name AS regprocedure))"), {"name": name})
        .scalar_one()
    )


def rewrite(*, forward: bool) -> None:
    supply = definition("cehub_supplier.material_exception_review_guard()")
    source, target = (OLD_COVERAGE, NEW_COVERAGE) if forward else (NEW_COVERAGE, OLD_COVERAGE)
    if supply.count(source) != 1:
        raise RuntimeError("Expected supply recovery arithmetic guard is unavailable")
    op.execute(supply.replace(source, target))

    scenario = definition("cehub_project.guard_scenario_recertification()")
    alias, replacement = ("old", "previous_node") if forward else ("previous_node", "old")
    for table in ("schedule_nodes", "schedule_time_nodes"):
        if scenario.count(f"cehub_project.{table} {alias}") != 1:
            raise RuntimeError("Expected scenario lineage guard is unavailable")
        scenario = scenario.replace(
            f"cehub_project.{table} {alias}", f"cehub_project.{table} {replacement}"
        )
    op.execute(scenario.replace(f"{alias}.", f"{replacement}."))


def upgrade() -> None:
    rewrite(forward=True)


def downgrade() -> None:
    rewrite(forward=False)
