"""Identify user risk requests separately from event Agent work and allow queuing."""

from collections.abc import Sequence
from importlib import import_module

from alembic import op

revision: str = "0092_risk_application_queue"
down_revision: str | Sequence[str] | None = "0091_application_cancellation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUEUE = import_module("migrations.versions.0087_application_chat_queue")
WAIT = import_module("migrations.versions.0089_application_waiting_input")
OLD_LIFECYCLE = WAIT.PREVIOUS.LIFECYCLE.replace(
    "(status='running' AND started_at IS NOT NULL",
    "(status IN ('running','waiting_input') AND started_at IS NOT NULL",
)
LIFECYCLE = OLD_LIFECYCLE.replace(
    "agent_key='ai_chat' AND run_context",
    "agent_key IN ('ai_chat','project_intelligence') AND run_context",
)
EVENTS = QUEUE.EVENTS.replace(
    "AND request_id IS NULL AND requested_by_user_id IS NULL",
    """AND ((request_id IS NULL AND requested_by_user_id IS NULL) OR
     (agent_key='project_intelligence' AND context_version='risk-suggestion-request-v1'
      AND request_id IS NOT NULL AND btrim(request_id)<>''
      AND requested_by_user_id IS NOT NULL))""",
)


def upgrade() -> None:
    QUEUE.PREVIOUS.PREVIOUS.replace_check("ck_agent_runs_event_bounds_consistent", EVENTS)
    op.execute(LIFECYCLE)
    op.execute("""CREATE INDEX ix_application_risk_queue ON cehub_ai.agent_runs(created_at,id)
     WHERE agent_key='project_intelligence' AND request_id IS NOT NULL AND status='queued';""")


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs
     WHERE agent_key='project_intelligence' AND request_id IS NOT NULL) THEN
      RAISE EXCEPTION 'cannot remove application risk request history'; END IF; END $body$;""")
    op.drop_index("ix_application_risk_queue", table_name="agent_runs", schema="cehub_ai")
    op.execute(OLD_LIFECYCLE)
    QUEUE.PREVIOUS.PREVIOUS.replace_check("ck_agent_runs_event_bounds_consistent", QUEUE.EVENTS)
