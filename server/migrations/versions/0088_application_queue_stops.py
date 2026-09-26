"""Keep queued Chat cancellation/failure honest: execution never started."""

from collections.abc import Sequence
from importlib import import_module

from alembic import op

revision: str = "0088_application_queue_stops"
down_revision: str | Sequence[str] | None = "0087_application_chat_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREVIOUS = import_module("migrations.versions.0079_event_authorization")
LIFECYCLE = PREVIOUS.LIFECYCLE.replace(
    "OR error_code IN ('BUDGET_LINEAGE_EXPIRED','AGENT_AUTHORIZATION_CHANGED')",
    "OR error_code IN ('BUDGET_LINEAGE_EXPIRED','AGENT_AUTHORIZATION_CHANGED') "
    "OR (agent_key='ai_chat' AND run_context->>'application_queue_version'='1')",
)


def upgrade() -> None:
    op.execute(LIFECYCLE)


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs WHERE agent_key='ai_chat'
        AND status='failed' AND started_at IS NULL
        AND run_context->>'application_queue_version'='1') THEN
        RAISE EXCEPTION 'cannot remove unstarted application failure history';
      END IF;
    END $body$;""")
    op.execute(PREVIOUS.LIFECYCLE)
