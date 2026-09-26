"""Persist Chat requests before execution; waiting in queue owns no worker lease."""

from collections.abc import Sequence
from importlib import import_module

from alembic import op

revision: str = "0087_application_chat_queue"
down_revision: str | Sequence[str] | None = "0086_application_recovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREVIOUS = import_module("migrations.versions.0069_import_mapping_runs")
EVENTS = PREVIOUS.EVENTS.replace(
    "status IN ('running', 'succeeded', 'degraded', 'failed')",
    "(status IN ('running', 'succeeded', 'degraded', 'failed') "
    "OR (agent_key = 'ai_chat' AND status = 'queued'))",
)


def upgrade() -> None:
    PREVIOUS.PREVIOUS.replace_check("ck_agent_runs_event_bounds_consistent", EVENTS)
    op.execute("""CREATE INDEX ix_application_chat_queue
      ON cehub_ai.agent_runs(created_at,id) WHERE agent_key='ai_chat' AND status='queued'""")


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs WHERE agent_key='ai_chat'
        AND (status='queued' OR run_context ? 'application_queue_version')) THEN
        RAISE EXCEPTION 'cannot discard persistent application queue history';
      END IF;
    END $body$;""")
    op.drop_index("ix_application_chat_queue", table_name="agent_runs", schema="cehub_ai")
    PREVIOUS.PREVIOUS.replace_check("ck_agent_runs_event_bounds_consistent", PREVIOUS.EVENTS)
