"""Accept bound planning-v6 runs while retaining previous run and history guards."""

from alembic import op
from sqlalchemy import text

revision = "0415_product_planning_v6_runs"
down_revision = "0414_definition_export_inheritance"
branch_labels = None
depends_on = None

FUNCTION = "cehub_ai.guard_product_work_run()"
OLD_PROMPT_GUARD = (
    "coalesce(NEW.run_context->>'product_work_prompt_version','') NOT IN "
    "('product-work-v1','product-research-v2','product-evidence-v3',"
    "'product-discovery-v4','product-planning-v5','product-rfq-v6')"
)
NEW_PROMPT_GUARD = (
    "coalesce(NEW.run_context->>'product_work_prompt_version','') NOT IN "
    "('product-work-v1','product-research-v2','product-evidence-v3',"
    "'product-discovery-v4','product-planning-v5','product-rfq-v6','product-planning-v6')\n"
    "  OR (NEW.run_context->>'product_work_prompt_version'='product-planning-v6'\n"
    "   AND coalesce(selection->>'capability','') NOT IN ('product_strategy','product_definition'))"
)
DOWNGRADE_PROTECTION = """
LOCK TABLE cehub_ai.agent_runs IN SHARE ROW EXCLUSIVE MODE;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs
  WHERE context_version='product-work-request-v1'
   AND run_context->>'product_work_prompt_version'='product-planning-v6') THEN
  RAISE EXCEPTION 'Retain planning-v6 original runs and their evidence';
 END IF;
END $$;
"""


def rewrite(*, forward: bool) -> None:
    definition = str(
        op.get_bind()
        .execute(text("SELECT pg_get_functiondef(CAST(:name AS regprocedure))"), {"name": FUNCTION})
        .scalar_one()
    )
    source, target = (
        (OLD_PROMPT_GUARD, NEW_PROMPT_GUARD) if forward else (NEW_PROMPT_GUARD, OLD_PROMPT_GUARD)
    )
    if definition.count(source) != 1 or target in definition:
        raise RuntimeError("Expected product planning prompt guard is unavailable")
    # Only the known prompt predicate changes. All scope/source/input identity
    # checks and the existing function's owner, ACL and execution settings survive.
    op.execute(definition.replace(source, target))


def upgrade() -> None:
    rewrite(forward=True)


def downgrade() -> None:
    op.execute(DOWNGRADE_PROTECTION)
    rewrite(forward=False)
