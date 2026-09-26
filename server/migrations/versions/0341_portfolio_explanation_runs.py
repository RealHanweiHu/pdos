"""Read-only portfolio explanation requests, isolated from event-driven briefs."""

from importlib import import_module

from alembic import op

revision = "0341_portfolio_explanation_runs"
down_revision = "0340_portfolio_applications"
branch_labels = None
depends_on = None
previous = import_module("migrations.versions.0330_cost_reduction_runs")
OLD = previous.NEW
NEW = OLD.replace(
    "('change-work-package-request-v1','cost-reduction-request-v1'))) AND",
    "('change-work-package-request-v1','cost-reduction-request-v1')) OR "
    "(agent_key='executive_intelligence' AND "
    "context_version='portfolio-explanation-request-v1')) AND",
)


def upgrade() -> None:
    previous.replace_constraint(NEW)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs
    WHERE context_version='portfolio-explanation-request-v1') THEN
    RAISE EXCEPTION 'Retain portfolio explanation runs and model receipts'; END IF; END $$;""")
    previous.replace_constraint(OLD)
