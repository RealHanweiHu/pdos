"""Independent source-bound structured cost analysis runs (default SHADOW)."""

from alembic import op

revision = "0330_cost_reduction_runs"
down_revision = "0329_cost_definition_feedback"
branch_labels = None
depends_on = None

OLD = """
(((agent_key = 'ai_chat' OR (agent_key='supplier_intelligence' AND
context_version='supplier-recovery-request-v1') OR (agent_key = 'quality_intelligence' AND
context_version IN ('report-mapping-request-v1', 'quality-work-package-request-v1')) OR
(agent_key='knowledge_lite' AND context_version IN
('meeting-reading-request-v1','meeting-minutes-request-v1','meeting-actions-request-v1','meeting-decisions-request-v1','meeting-business-request-v1','process-template-request-v1','intake-organization-request-v1','meeting-planning-request-v1'))
OR (agent_key='engineering_intelligence' AND context_version='change-work-package-request-v1')) AND
subscription_id IS NULL AND first_event_row_id IS NULL AND last_event_row_id IS NULL AND event_count
= 0 AND event_row_ids = '[]'::jsonb AND request_id IS NOT NULL AND btrim(request_id) <> '' AND
requested_by_user_id IS NOT NULL AND (status IN ('running', 'succeeded', 'degraded', 'failed') OR
(agent_key IN ('ai_chat','quality_intelligence') AND status = 'queued'))) OR (agent_key <> 'ai_chat'
AND subscription_id IS NOT NULL AND ((request_id IS NULL AND requested_by_user_id IS NULL) OR
((agent_key='project_intelligence' AND context_version='risk-suggestion-request-v1' OR
agent_key='quality_intelligence' AND context_version='test-plan-request-v1') AND request_id IS NOT
NULL AND btrim(request_id)<>'' AND requested_by_user_id IS NOT NULL)) AND first_event_row_id IS NOT
NULL AND last_event_row_id IS NOT NULL AND CASE WHEN jsonb_typeof(event_row_ids) = 'array' THEN
event_count > 0 AND first_event_row_id > 0 AND last_event_row_id >= first_event_row_id AND
jsonb_array_length(event_row_ids) = event_count AND (event_row_ids->>0)::bigint = first_event_row_id
AND (event_row_ids->>(event_count - 1))::bigint = last_event_row_id ELSE false END)) IS TRUE
"""

NEW = """
(((agent_key = 'ai_chat' OR (agent_key='supplier_intelligence' AND
context_version='supplier-recovery-request-v1') OR (agent_key = 'quality_intelligence' AND
context_version IN ('report-mapping-request-v1', 'quality-work-package-request-v1')) OR
(agent_key='knowledge_lite' AND context_version IN
('meeting-reading-request-v1','meeting-minutes-request-v1','meeting-actions-request-v1','meeting-decisions-request-v1','meeting-business-request-v1','process-template-request-v1','intake-organization-request-v1','meeting-planning-request-v1'))
OR (agent_key='engineering_intelligence' AND context_version IN
('change-work-package-request-v1','cost-reduction-request-v1'))) AND subscription_id IS NULL AND
first_event_row_id IS NULL AND last_event_row_id IS NULL AND event_count = 0 AND event_row_ids =
'[]'::jsonb AND request_id IS NOT NULL AND btrim(request_id) <> '' AND requested_by_user_id IS NOT
NULL AND (status IN ('running', 'succeeded', 'degraded', 'failed') OR (agent_key IN
('ai_chat','quality_intelligence') AND status = 'queued'))) OR (agent_key <> 'ai_chat' AND
subscription_id IS NOT NULL AND ((request_id IS NULL AND requested_by_user_id IS NULL) OR
((agent_key='project_intelligence' AND context_version='risk-suggestion-request-v1' OR
agent_key='quality_intelligence' AND context_version='test-plan-request-v1') AND request_id IS NOT
NULL AND btrim(request_id)<>'' AND requested_by_user_id IS NOT NULL)) AND first_event_row_id IS NOT
NULL AND last_event_row_id IS NOT NULL AND CASE WHEN jsonb_typeof(event_row_ids) = 'array' THEN
event_count > 0 AND first_event_row_id > 0 AND last_event_row_id >= first_event_row_id AND
jsonb_array_length(event_row_ids) = event_count AND (event_row_ids->>0)::bigint = first_event_row_id
AND (event_row_ids->>(event_count - 1))::bigint = last_event_row_id ELSE false END)) IS TRUE
"""


def replace_constraint(value: str) -> None:
    op.execute(
        "ALTER TABLE cehub_ai.agent_runs DROP CONSTRAINT ck_agent_runs_event_bounds_consistent"
    )
    op.execute(
        "ALTER TABLE cehub_ai.agent_runs ADD CONSTRAINT "
        "ck_agent_runs_event_bounds_consistent CHECK (" + value + ")"
    )


def upgrade() -> None:
    replace_constraint(NEW)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs
    WHERE context_version='cost-reduction-request-v1') THEN
    RAISE EXCEPTION 'Retain actual cost analysis runs and fixed model receipts'; END IF; END $$;""")
    replace_constraint(OLD)
