"""Budgeted, read-only management brief runs using frozen selected-project sources."""

from importlib import import_module

from alembic import op

revision = "0345_executive_brief_runs"
down_revision = "0344_milestone_designations"
branch_labels = None
depends_on = None
previous = import_module("migrations.versions.0341_portfolio_explanation_runs")
OLD = previous.NEW
NEW = OLD.replace(
    "context_version='portfolio-explanation-request-v1'",
    "context_version IN ('portfolio-explanation-request-v1','executive-brief-request-v1')",
)


def upgrade() -> None:
    previous.previous.replace_constraint(NEW)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs
    WHERE context_version='executive-brief-request-v1') THEN
    RAISE EXCEPTION 'Retain executive brief runs and model receipts'; END IF; END $$;""")
    previous.previous.replace_constraint(OLD)
