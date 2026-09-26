"""Allow authenticated report-mapping runs without business-event fabrication."""

from collections.abc import Sequence
from importlib import import_module

from alembic import op

revision: str = "0069_import_mapping_runs"
down_revision: str | Sequence[str] | None = "0068_chat_request_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# This is an immutable previous migration, not the current application's schema.
PREVIOUS = import_module("migrations.versions.0068_chat_request_runs")
EVENTS = PREVIOUS.EVENTS.replace(
    "agent_key = 'ai_chat' AND subscription_id IS NULL",
    "(agent_key = 'ai_chat' OR (agent_key = 'quality_intelligence' "
    "AND context_version = 'report-mapping-request-v1')) AND subscription_id IS NULL",
)


def upgrade() -> None:
    PREVIOUS.replace_check("ck_agent_runs_event_bounds_consistent", EVENTS)


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
        IF EXISTS (SELECT 1 FROM cehub_ai.agent_runs
                   WHERE agent_key = 'quality_intelligence' AND request_id IS NOT NULL) THEN
            RAISE EXCEPTION 'cannot discard persistent report mapping request history';
        END IF;
    END $body$;""")
    PREVIOUS.replace_check("ck_agent_runs_event_bounds_consistent", PREVIOUS.EVENTS)
