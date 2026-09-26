"""Persist test-plan requests separately from event work and allow queued stops."""

from collections.abc import Sequence
from importlib import import_module

from alembic import op

revision: str = "0093_test_plan_queue"
down_revision: str | Sequence[str] | None = "0092_risk_application_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
PREVIOUS = import_module("migrations.versions.0092_risk_application_queue")
EVENTS = PREVIOUS.EVENTS.replace(
    "(agent_key='project_intelligence' AND context_version='risk-suggestion-request-v1'",
    """((agent_key='project_intelligence' AND context_version='risk-suggestion-request-v1'
       OR agent_key='quality_intelligence' AND context_version='test-plan-request-v1')""",
)
LIFECYCLE = PREVIOUS.LIFECYCLE.replace(
    "agent_key IN ('ai_chat','project_intelligence') AND run_context",
    "agent_key IN ('ai_chat','project_intelligence','quality_intelligence') AND run_context",
)


def upgrade() -> None:
    PREVIOUS.QUEUE.PREVIOUS.PREVIOUS.replace_check("ck_agent_runs_event_bounds_consistent", EVENTS)
    op.execute(LIFECYCLE)
    op.execute("""CREATE INDEX ix_application_test_plan_queue ON cehub_ai.agent_runs(created_at,id)
     WHERE context_version='test-plan-request-v1' AND status='queued';""")


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs
     WHERE context_version='test-plan-request-v1') THEN
      RAISE EXCEPTION 'cannot remove test-plan request history'; END IF; END $body$;""")
    op.drop_index("ix_application_test_plan_queue", table_name="agent_runs", schema="cehub_ai")
    op.execute(PREVIOUS.LIFECYCLE)
    PREVIOUS.QUEUE.PREVIOUS.PREVIOUS.replace_check(
        "ck_agent_runs_event_bounds_consistent", PREVIOUS.EVENTS
    )
