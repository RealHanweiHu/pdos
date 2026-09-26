"""Admit explicitly requested, zero-event Knowledge Lite meeting reading runs."""

import sqlalchemy as sa
from alembic import op

revision = "0170_meeting_reading_runs"
down_revision = "0169_meeting_transcript_sources"
branch_labels = None
depends_on = None

OLD = """(((agent_key = 'ai_chat' OR (agent_key = 'quality_intelligence'
 AND context_version = 'report-mapping-request-v1')) AND subscription_id IS NULL
 AND first_event_row_id IS NULL AND last_event_row_id IS NULL
 AND event_count = 0 AND event_row_ids = '[]'::jsonb
 AND request_id IS NOT NULL AND btrim(request_id) <> ''
 AND requested_by_user_id IS NOT NULL
 AND (status IN ('running', 'succeeded', 'degraded', 'failed')
 OR (agent_key IN ('ai_chat','quality_intelligence') AND status = 'queued'))) OR
 (agent_key <> 'ai_chat' AND subscription_id IS NOT NULL
 AND ((request_id IS NULL AND requested_by_user_id IS NULL) OR
 ((agent_key='project_intelligence' AND context_version='risk-suggestion-request-v1'
 OR agent_key='quality_intelligence' AND context_version='test-plan-request-v1')
 AND request_id IS NOT NULL AND btrim(request_id)<>''
 AND requested_by_user_id IS NOT NULL))
 AND first_event_row_id IS NOT NULL AND last_event_row_id IS NOT NULL
 AND CASE WHEN jsonb_typeof(event_row_ids) = 'array' THEN
 event_count > 0 AND first_event_row_id > 0
 AND last_event_row_id >= first_event_row_id
 AND jsonb_array_length(event_row_ids) = event_count
 AND (event_row_ids->>0)::bigint = first_event_row_id
 AND (event_row_ids->>(event_count - 1))::bigint = last_event_row_id
 ELSE false END)) IS TRUE"""
NEW = OLD.replace(
    "AND context_version = 'report-mapping-request-v1'))",
    "AND context_version = 'report-mapping-request-v1') OR (agent_key='knowledge_lite' "
    "AND context_version='meeting-reading-request-v1'))",
)


def replace_guard(body: str) -> None:
    op.drop_constraint(
        op.f("ck_agent_runs_event_bounds_consistent"), "agent_runs", schema="cehub_ai"
    )
    op.create_check_constraint(
        op.f("ck_agent_runs_event_bounds_consistent"), "agent_runs", body, schema="cehub_ai"
    )


def upgrade() -> None:
    replace_guard(NEW)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_ai.agent_runs "
                "WHERE context_version='meeting-reading-request-v1')"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard meeting reading run history")
    replace_guard(OLD)
