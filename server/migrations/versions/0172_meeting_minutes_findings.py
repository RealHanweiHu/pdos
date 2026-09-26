"""Typed meeting minutes Findings and atomic links to official minutes."""

import sqlalchemy as sa
from alembic import op

revision = "0172_meeting_minutes_findings"
down_revision = "0171_meeting_minutes_versions"
branch_labels = None
depends_on = None

CHANGES = [
    (
        "agent_runs",
        "event_bounds_consistent",
        """(((agent_key = 'ai_chat' OR (agent_key = 'quality_intelligence' AND context_version =
'report-mapping-request-v1') OR (agent_key='knowledge_lite' AND
context_version='meeting-reading-request-v1')) AND subscription_id IS NULL AND
first_event_row_id IS NULL AND last_event_row_id IS NULL AND event_count = 0 AND
event_row_ids = '[]'::jsonb AND request_id IS NOT NULL AND btrim(request_id) <> '' AND
requested_by_user_id IS NOT NULL AND (status IN ('running', 'succeeded', 'degraded',
'failed') OR (agent_key IN ('ai_chat','quality_intelligence') AND status = 'queued'))) OR
(agent_key <> 'ai_chat' AND subscription_id IS NOT NULL AND ((request_id IS NULL AND
requested_by_user_id IS NULL) OR ((agent_key='project_intelligence' AND
context_version='risk-suggestion-request-v1' OR agent_key='quality_intelligence' AND
context_version='test-plan-request-v1') AND request_id IS NOT NULL AND btrim(request_id)<>''
AND requested_by_user_id IS NOT NULL)) AND first_event_row_id IS NOT NULL AND
last_event_row_id IS NOT NULL AND CASE WHEN jsonb_typeof(event_row_ids) = 'array' THEN
event_count > 0 AND first_event_row_id > 0 AND last_event_row_id >= first_event_row_id AND
jsonb_array_length(event_row_ids) = event_count AND (event_row_ids->>0)::bigint =
first_event_row_id AND (event_row_ids->>(event_count - 1))::bigint = last_event_row_id ELSE
false END)) IS TRUE""",
        """(((agent_key = 'ai_chat' OR (agent_key = 'quality_intelligence' AND context_version =
'report-mapping-request-v1') OR (agent_key='knowledge_lite' AND context_version IN
('meeting-reading-request-v1','meeting-minutes-request-v1'))) AND subscription_id IS NULL
AND first_event_row_id IS NULL AND last_event_row_id IS NULL AND event_count = 0 AND
event_row_ids = '[]'::jsonb AND request_id IS NOT NULL AND btrim(request_id) <> '' AND
requested_by_user_id IS NOT NULL AND (status IN ('running', 'succeeded', 'degraded',
'failed') OR (agent_key IN ('ai_chat','quality_intelligence') AND status = 'queued'))) OR
(agent_key <> 'ai_chat' AND subscription_id IS NOT NULL AND ((request_id IS NULL AND
requested_by_user_id IS NULL) OR ((agent_key='project_intelligence' AND
context_version='risk-suggestion-request-v1' OR agent_key='quality_intelligence' AND
context_version='test-plan-request-v1') AND request_id IS NOT NULL AND btrim(request_id)<>''
AND requested_by_user_id IS NOT NULL)) AND first_event_row_id IS NOT NULL AND
last_event_row_id IS NOT NULL AND CASE WHEN jsonb_typeof(event_row_ids) = 'array' THEN
event_count > 0 AND first_event_row_id > 0 AND last_event_row_id >= first_event_row_id AND
jsonb_array_length(event_row_ids) = event_count AND (event_row_ids->>0)::bigint =
first_event_row_id AND (event_row_ids->>(event_count - 1))::bigint = last_event_row_id ELSE
false END)) IS TRUE""",
    ),
    (
        "findings",
        "type_allowed",
        """(agent_key = 'project_intelligence' AND finding_type IN
('risk_suggestion', 'blocker_alert',
'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND finding_type =
'knowledge_draft') OR (agent_key = 'engineering_intelligence' AND finding_type IN
('bom_impact_suggestion', 'change_impact_suggestion')) OR (agent_key =
'quality_intelligence' AND finding_type IN ('quality_cluster_alert', 'capa_suggestion',
'test_plan_change')) OR (agent_key = 'supplier_intelligence' AND finding_type =
'supplier_delay_risk') OR (agent_key = 'executive_intelligence' AND finding_type =
'executive_portfolio_brief')""",
        """(agent_key = 'project_intelligence' AND finding_type IN
('risk_suggestion', 'blocker_alert',
'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND finding_type IN
('knowledge_draft', 'meeting_minutes')) OR (agent_key = 'engineering_intelligence' AND
finding_type IN ('bom_impact_suggestion', 'change_impact_suggestion')) OR (agent_key =
'quality_intelligence' AND finding_type IN ('quality_cluster_alert', 'capa_suggestion',
'test_plan_change')) OR (agent_key = 'supplier_intelligence' AND finding_type =
'supplier_delay_risk') OR (agent_key = 'executive_intelligence' AND finding_type =
'executive_portfolio_brief')""",
    ),
    (
        "finding_quality_controls",
        "type_allowed",
        """(agent_key = 'project_intelligence' AND finding_type IN
('risk_suggestion', 'blocker_alert',
'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND finding_type =
'knowledge_draft') OR (agent_key = 'engineering_intelligence' AND finding_type IN
('bom_impact_suggestion', 'change_impact_suggestion')) OR (agent_key =
'quality_intelligence' AND finding_type IN ('quality_cluster_alert', 'capa_suggestion',
'test_plan_change')) OR (agent_key = 'supplier_intelligence' AND finding_type =
'supplier_delay_risk') OR (agent_key = 'executive_intelligence' AND finding_type =
'executive_portfolio_brief')""",
        """(agent_key = 'project_intelligence' AND finding_type IN
('risk_suggestion', 'blocker_alert',
'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND finding_type IN
('knowledge_draft', 'meeting_minutes')) OR (agent_key = 'engineering_intelligence' AND
finding_type IN ('bom_impact_suggestion', 'change_impact_suggestion')) OR (agent_key =
'quality_intelligence' AND finding_type IN ('quality_cluster_alert', 'capa_suggestion',
'test_plan_change')) OR (agent_key = 'supplier_intelligence' AND finding_type =
'supplier_delay_risk') OR (agent_key = 'executive_intelligence' AND finding_type =
'executive_portfolio_brief')""",
    ),
    (
        "findings",
        "evidence_event_ids_array",
        """jsonb_typeof(evidence_event_ids) = 'array'
AND jsonb_array_length(evidence_event_ids) > 0""",
        """jsonb_typeof(evidence_event_ids) = 'array'
AND (jsonb_array_length(evidence_event_ids) > 0
OR (finding_type='meeting_minutes' AND evidence_event_ids='[]'::jsonb))""",
    ),
    (
        "findings",
        "apply_lifecycle_consistent",
        """(status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL AND
applied_entity_type IS NULL AND applied_entity_id IS NULL) OR (status = 'applied' AND
applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL AND applied_entity_type IN
('risk', 'memory', 'issue', 'task', 'test_run', 'sample_build_configuration',
'knowledge_candidate', 'schedule_change_proposal', 'material_exception', 'test_plan') AND
applied_entity_id IS NOT NULL AND reviewed_at < applied_at)""",
        """(status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL AND
applied_entity_type IS NULL AND applied_entity_id IS NULL) OR (status = 'applied' AND
applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL AND applied_entity_type IN
('risk', 'memory', 'issue', 'task', 'test_run', 'sample_build_configuration',
'knowledge_candidate', 'schedule_change_proposal', 'material_exception', 'test_plan',
'meeting_minutes') AND applied_entity_id IS NOT NULL AND reviewed_at < applied_at)""",
    ),
]


def constraints(up: bool) -> None:
    for table, name, old, new in CHANGES:
        op.drop_constraint(op.f(f"ck_{table}_{name}"), table, schema="cehub_ai", type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_{name}"), table, new if up else old, schema="cehub_ai"
        )


def upgrade() -> None:
    constraints(True)
    op.add_column(
        "meeting_minutes_versions",
        sa.Column("source_finding_id", sa.Uuid()),
        schema="cehub_project",
    )
    op.create_foreign_key(
        "fk_minutes_finding",
        "meeting_minutes_versions",
        "findings",
        ["tenant_id", "project_id", "source_finding_id"],
        ["tenant_id", "project_id", "id"],
        source_schema="cehub_project",
        referent_schema="cehub_ai",
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_minutes_source_finding",
        "meeting_minutes_versions",
        ["tenant_id", "source_finding_id"],
        schema="cehub_project",
    )
    op.execute(GUARDS)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_ai.findings "
                "WHERE finding_type='meeting_minutes') "
                "OR EXISTS(SELECT 1 FROM cehub_ai.finding_quality_controls "
                "WHERE finding_type='meeting_minutes') "
                "OR EXISTS(SELECT 1 FROM cehub_ai.agent_runs "
                "WHERE context_version='meeting-minutes-request-v1') "
                "OR EXISTS(SELECT 1 FROM cehub_project.meeting_minutes_versions "
                "WHERE source_finding_id IS NOT NULL)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to remove meeting minutes candidate history")
    op.execute(
        "DROP TRIGGER guard_minutes_finding_origin ON cehub_project.meeting_minutes_versions; "
        "DROP FUNCTION cehub_project.guard_minutes_finding_origin(); "
        "DROP TRIGGER guard_minutes_finding_source ON cehub_ai.findings; "
        "DROP FUNCTION cehub_ai.guard_minutes_finding_source();"
    )
    op.drop_constraint(
        "uq_minutes_source_finding",
        "meeting_minutes_versions",
        schema="cehub_project",
        type_="unique",
    )
    op.drop_constraint(
        "fk_minutes_finding", "meeting_minutes_versions", schema="cehub_project", type_="foreignkey"
    )
    op.drop_column("meeting_minutes_versions", "source_finding_id", schema="cehub_project")
    constraints(False)


GUARDS = r"""
CREATE FUNCTION cehub_ai.guard_minutes_finding_source() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='UPDATE' AND OLD.finding_type='meeting_minutes' AND
   (NEW.finding_type<>OLD.finding_type OR NEW.proposed_payload IS DISTINCT FROM OLD.proposed_payload
    OR NEW.run_id<>OLD.run_id OR NEW.model_invocation_id<>OLD.model_invocation_id) THEN
  RAISE EXCEPTION 'Minutes proposal origin is immutable' USING ERRCODE='23514';
 END IF;
 IF NEW.finding_type<>'meeting_minutes' THEN RETURN NEW; END IF;
 IF NEW.evidence_event_ids<>'[]'::jsonb OR NOT EXISTS(
  SELECT 1 FROM cehub_ai.agent_runs r JOIN cehub_ai.model_invocations i
   ON i.tenant_id=r.tenant_id AND i.project_id=r.project_id AND i.run_id=r.id
  WHERE r.tenant_id=NEW.tenant_id AND r.project_id=NEW.project_id AND r.id=NEW.run_id
   AND r.agent_key='knowledge_lite' AND r.context_version='meeting-minutes-request-v1'
   AND r.run_context->>'reading_propose_minutes'='true'
   AND i.id=NEW.model_invocation_id AND i.agent_key=r.agent_key AND i.status='succeeded'
   AND NEW.proposed_payload->>'meeting_id'=r.run_context->'reading_source'->>'meeting_id'
   AND NEW.proposed_payload->>'transcript_id'=r.run_context->'reading_source'->>'transcript_id'
   AND NEW.proposed_payload->>'source_digest'=r.run_context->'reading_source'->>'transcript_digest'
   AND NEW.proposed_payload->'base_snapshot'=r.run_context->'reading_source'->'minutes_base'
   AND NEW.proposed_payload->>'base_version'=
    r.run_context->'reading_source'->'minutes_base'->>'version'
 ) THEN
  RAISE EXCEPTION 'Minutes candidate must bind its actual model run and transcript'
   USING ERRCODE='23514';
 END IF;
 IF NEW.accepted_payload IS NOT NULL AND EXISTS(SELECT 1 FROM
   unnest(ARRAY['meeting_id','transcript_id','source_digest','base_version','base_snapshot']) k
   WHERE NEW.accepted_payload->k IS DISTINCT FROM NEW.proposed_payload->k) THEN
  RAISE EXCEPTION 'Review cannot replace the minutes proposal base' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_minutes_finding_source() FROM PUBLIC;
CREATE TRIGGER guard_minutes_finding_source BEFORE INSERT OR UPDATE ON cehub_ai.findings
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_minutes_finding_source();

CREATE FUNCTION cehub_project.guard_minutes_finding_origin() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE f cehub_ai.findings%ROWTYPE; c jsonb;
BEGIN
 IF NEW.source_finding_id IS NULL THEN RETURN NEW; END IF;
 SELECT * INTO f FROM cehub_ai.findings
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.source_finding_id;
 IF NOT FOUND OR f.finding_type<>'meeting_minutes' OR f.status<>'accepted'
  OR (f.accepted_payload->>'meeting_id')::uuid IS DISTINCT FROM NEW.meeting_id
  OR (f.accepted_payload->>'base_version')::integer+1 IS DISTINCT FROM NEW.version_no
  OR f.accepted_payload->>'body' IS DISTINCT FROM NEW.body
  OR f.accepted_payload->>'unresolved_points' IS DISTINCT FROM NEW.unresolved_points
  OR jsonb_array_length(f.accepted_payload->'citations')<>jsonb_array_length(NEW.citations) THEN
  RAISE EXCEPTION 'Official minutes must match an independently accepted candidate'
   USING ERRCODE='23514';
 END IF;
 FOR c IN SELECT value FROM jsonb_array_elements(NEW.citations) LOOP
  IF c->>'transcript_id' IS DISTINCT FROM f.accepted_payload->>'transcript_id'
    OR c->>'source_digest' IS DISTINCT FROM f.accepted_payload->>'source_digest'
    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(f.accepted_payload->'citations') q
     WHERE q->>'segment_id'=c->>'segment_id' AND q->>'exact_quote'=c->>'exact_quote') THEN
   RAISE EXCEPTION 'Minutes applied citations differ from accepted quotes' USING ERRCODE='23514';
  END IF;
 END LOOP;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(f.accepted_payload->'citations') q
  WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.citations) n
   WHERE n->>'segment_id'=q->>'segment_id' AND n->>'exact_quote'=q->>'exact_quote')) THEN
  RAISE EXCEPTION 'Minutes applied citations omit accepted quotes' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_project.guard_minutes_finding_origin() FROM PUBLIC;
CREATE TRIGGER guard_minutes_finding_origin BEFORE INSERT ON cehub_project.meeting_minutes_versions
 FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_minutes_finding_origin();
"""
