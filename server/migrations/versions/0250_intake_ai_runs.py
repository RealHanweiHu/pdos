"""Source-bound private intake runs and receipted pending Findings."""

from alembic import op

revision = "0250_intake_ai_runs"
down_revision = "0249_intake_ai_sources"
branch_labels = None
depends_on = None

DDL = """
ALTER TABLE cehub_ai.agent_runs DROP CONSTRAINT ck_agent_runs_event_bounds_consistent;
ALTER TABLE cehub_ai.agent_runs ADD CONSTRAINT ck_agent_runs_event_bounds_consistent CHECK
((((agent_key = 'ai_chat' OR (agent_key = 'quality_intelligence' AND context_version IN
('report-mapping-request-v1', 'quality-work-package-request-v1')) OR (agent_key='knowledge_lite'
AND context_version IN
('meeting-reading-request-v1','meeting-minutes-request-v1','meeting-actions-request-v1','meeting-decisions-request-v1','meeting-business-request-v1','process-template-request-v1','intake-organization-request-v1'))
OR (agent_key='engineering_intelligence' AND context_version='change-work-package-request-v1'))
AND subscription_id IS NULL AND first_event_row_id IS NULL AND last_event_row_id IS NULL AND
event_count = 0 AND event_row_ids = '[]'::jsonb AND request_id IS NOT NULL AND btrim(request_id)
<> '' AND requested_by_user_id IS NOT NULL AND (status IN ('running', 'succeeded', 'degraded',
'failed') OR (agent_key IN ('ai_chat','quality_intelligence') AND status = 'queued'))) OR
(agent_key <> 'ai_chat' AND subscription_id IS NOT NULL AND ((request_id IS NULL AND
requested_by_user_id IS NULL) OR ((agent_key='project_intelligence' AND
context_version='risk-suggestion-request-v1' OR agent_key='quality_intelligence' AND
context_version='test-plan-request-v1') AND request_id IS NOT NULL AND btrim(request_id)<>'' AND
requested_by_user_id IS NOT NULL)) AND first_event_row_id IS NOT NULL AND last_event_row_id IS NOT
NULL AND CASE WHEN jsonb_typeof(event_row_ids) = 'array' THEN event_count > 0 AND
first_event_row_id > 0 AND last_event_row_id >= first_event_row_id AND
jsonb_array_length(event_row_ids) = event_count AND (event_row_ids->>0)::bigint =
first_event_row_id AND (event_row_ids->>(event_count - 1))::bigint = last_event_row_id ELSE false
END)) IS TRUE);
ALTER TABLE cehub_ai.findings DROP CONSTRAINT ck_findings_type_allowed;
ALTER TABLE cehub_ai.findings ADD CONSTRAINT ck_findings_type_allowed CHECK ((agent_key =
'project_intelligence' AND finding_type IN ('risk_suggestion', 'blocker_alert',
'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND finding_type IN
('knowledge_draft', 'meeting_minutes', 'meeting_action', 'meeting_decision', 'meeting_issue',
'meeting_risk', 'meeting_change', 'process_template_configuration','intake_organization')) OR
(agent_key = 'engineering_intelligence' AND finding_type IN ('bom_impact_suggestion',
'change_impact_suggestion', 'change_work_package')) OR (agent_key = 'quality_intelligence' AND
finding_type IN ('quality_cluster_alert', 'capa_suggestion', 'test_plan_change',
'capa_work_package')) OR (agent_key = 'supplier_intelligence' AND finding_type =
'supplier_delay_risk') OR (agent_key = 'executive_intelligence' AND finding_type =
'executive_portfolio_brief'));
ALTER TABLE cehub_ai.findings DROP CONSTRAINT ck_findings_evidence_event_ids_array;
ALTER TABLE cehub_ai.findings ADD CONSTRAINT ck_findings_evidence_event_ids_array CHECK
(jsonb_typeof(evidence_event_ids) = 'array' AND (jsonb_array_length(evidence_event_ids) > 0 OR
(finding_type IN
('meeting_minutes','meeting_action','meeting_decision','meeting_issue','meeting_risk','meeting_change','change_work_package','capa_work_package','process_template_configuration','intake_organization')
AND evidence_event_ids='[]'::jsonb)));
ALTER TABLE cehub_ai.finding_quality_controls DROP CONSTRAINT
ck_finding_quality_controls_type_allowed;
ALTER TABLE cehub_ai.finding_quality_controls ADD CONSTRAINT
ck_finding_quality_controls_type_allowed CHECK ((agent_key = 'project_intelligence' AND
finding_type IN ('risk_suggestion', 'blocker_alert', 'gate_readiness_anomaly')) OR (agent_key =
'knowledge_lite' AND finding_type IN ('knowledge_draft', 'meeting_minutes', 'meeting_action',
'meeting_decision', 'meeting_issue', 'meeting_risk', 'meeting_change',
'process_template_configuration','intake_organization')) OR (agent_key =
'engineering_intelligence' AND finding_type IN ('bom_impact_suggestion',
'change_impact_suggestion', 'change_work_package')) OR (agent_key = 'quality_intelligence' AND
finding_type IN ('quality_cluster_alert', 'capa_suggestion', 'test_plan_change',
'capa_work_package')) OR (agent_key = 'supplier_intelligence' AND finding_type =
'supplier_delay_risk') OR (agent_key = 'executive_intelligence' AND finding_type =
'executive_portfolio_brief'));
"""
OLD = """
ALTER TABLE cehub_ai.agent_runs DROP CONSTRAINT ck_agent_runs_event_bounds_consistent;
ALTER TABLE cehub_ai.agent_runs ADD CONSTRAINT ck_agent_runs_event_bounds_consistent CHECK
((((agent_key = 'ai_chat' OR (agent_key = 'quality_intelligence' AND context_version IN
('report-mapping-request-v1', 'quality-work-package-request-v1')) OR (agent_key='knowledge_lite'
AND context_version IN
('meeting-reading-request-v1','meeting-minutes-request-v1','meeting-actions-request-v1','meeting-decisions-request-v1','meeting-business-request-v1','process-template-request-v1'))
OR (agent_key='engineering_intelligence' AND context_version='change-work-package-request-v1'))
AND subscription_id IS NULL AND first_event_row_id IS NULL AND last_event_row_id IS NULL AND
event_count = 0 AND event_row_ids = '[]'::jsonb AND request_id IS NOT NULL AND btrim(request_id)
<> '' AND requested_by_user_id IS NOT NULL AND (status IN ('running', 'succeeded', 'degraded',
'failed') OR (agent_key IN ('ai_chat','quality_intelligence') AND status = 'queued'))) OR
(agent_key <> 'ai_chat' AND subscription_id IS NOT NULL AND ((request_id IS NULL AND
requested_by_user_id IS NULL) OR ((agent_key='project_intelligence' AND
context_version='risk-suggestion-request-v1' OR agent_key='quality_intelligence' AND
context_version='test-plan-request-v1') AND request_id IS NOT NULL AND btrim(request_id)<>'' AND
requested_by_user_id IS NOT NULL)) AND first_event_row_id IS NOT NULL AND last_event_row_id IS NOT
NULL AND CASE WHEN jsonb_typeof(event_row_ids) = 'array' THEN event_count > 0 AND
first_event_row_id > 0 AND last_event_row_id >= first_event_row_id AND
jsonb_array_length(event_row_ids) = event_count AND (event_row_ids->>0)::bigint =
first_event_row_id AND (event_row_ids->>(event_count - 1))::bigint = last_event_row_id ELSE false
END)) IS TRUE);
ALTER TABLE cehub_ai.findings DROP CONSTRAINT ck_findings_type_allowed;
ALTER TABLE cehub_ai.findings ADD CONSTRAINT ck_findings_type_allowed CHECK ((agent_key =
'project_intelligence' AND finding_type IN ('risk_suggestion', 'blocker_alert',
'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND finding_type IN
('knowledge_draft', 'meeting_minutes', 'meeting_action', 'meeting_decision', 'meeting_issue',
'meeting_risk', 'meeting_change', 'process_template_configuration')) OR (agent_key =
'engineering_intelligence' AND finding_type IN ('bom_impact_suggestion',
'change_impact_suggestion', 'change_work_package')) OR (agent_key = 'quality_intelligence' AND
finding_type IN ('quality_cluster_alert', 'capa_suggestion', 'test_plan_change',
'capa_work_package')) OR (agent_key = 'supplier_intelligence' AND finding_type =
'supplier_delay_risk') OR (agent_key = 'executive_intelligence' AND finding_type =
'executive_portfolio_brief'));
ALTER TABLE cehub_ai.findings DROP CONSTRAINT ck_findings_evidence_event_ids_array;
ALTER TABLE cehub_ai.findings ADD CONSTRAINT ck_findings_evidence_event_ids_array CHECK
(jsonb_typeof(evidence_event_ids) = 'array' AND (jsonb_array_length(evidence_event_ids) > 0 OR
(finding_type IN
('meeting_minutes','meeting_action','meeting_decision','meeting_issue','meeting_risk','meeting_change','change_work_package','capa_work_package','process_template_configuration')
AND evidence_event_ids='[]'::jsonb)));
ALTER TABLE cehub_ai.finding_quality_controls DROP CONSTRAINT
ck_finding_quality_controls_type_allowed;
ALTER TABLE cehub_ai.finding_quality_controls ADD CONSTRAINT
ck_finding_quality_controls_type_allowed CHECK ((agent_key = 'project_intelligence' AND
finding_type IN ('risk_suggestion', 'blocker_alert', 'gate_readiness_anomaly')) OR (agent_key =
'knowledge_lite' AND finding_type IN ('knowledge_draft', 'meeting_minutes', 'meeting_action',
'meeting_decision', 'meeting_issue', 'meeting_risk', 'meeting_change',
'process_template_configuration')) OR (agent_key = 'engineering_intelligence' AND finding_type IN
('bom_impact_suggestion', 'change_impact_suggestion', 'change_work_package')) OR (agent_key =
'quality_intelligence' AND finding_type IN ('quality_cluster_alert', 'capa_suggestion',
'test_plan_change', 'capa_work_package')) OR (agent_key = 'supplier_intelligence' AND finding_type
= 'supplier_delay_risk') OR (agent_key = 'executive_intelligence' AND finding_type =
'executive_portfolio_brief'));
"""

GUARD = """
CREATE FUNCTION cehub_ai.guard_intake_ai_run() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b cehub_ai.intake_ai_briefs;
BEGIN
 IF TG_OP='UPDATE' AND OLD.context_version='intake-organization-request-v1' AND
 (NEW.tenant_id,NEW.project_id,NEW.context_version,NEW.request_id,NEW.requested_by_user_id,
 NEW.run_context-'intake_finding_id'-'intake_reading') IS DISTINCT FROM
 (OLD.tenant_id,OLD.project_id,OLD.context_version,OLD.request_id,OLD.requested_by_user_id,
 OLD.run_context-'intake_finding_id'-'intake_reading') THEN
 RAISE EXCEPTION 'Intake run input identity is immutable'; END IF;
 IF NEW.context_version<>'intake-organization-request-v1' THEN RETURN NEW; END IF;
 SELECT * INTO b FROM cehub_ai.intake_ai_briefs WHERE tenant_id=NEW.tenant_id
  AND project_id=NEW.project_id AND id::text=NEW.run_context->>'intake_brief_id'
  AND created_by_user_id=NEW.requested_by_user_id;
 IF b.id IS NULL OR NEW.agent_key<>'knowledge_lite' OR NEW.scope_kind<>'project'
  OR NEW.run_context->>'intake_root_brief_id' IS DISTINCT FROM b.root_brief_id::text
  OR NEW.run_context->>'intake_source_digest' IS DISTINCT FROM b.source_digest
  OR NEW.run_context->'intake_source' IS DISTINCT FROM
   b.source_snapshot||jsonb_build_object('brief_id',b.id::text)
  OR NEW.run_context->>'intake_prompt_version' IS DISTINCT FROM 'intake-organization-v1'
  OR coalesce(NEW.run_context->>'intake_schema_digest','') !~ '^[0-9a-f]{64}$'
  OR coalesce(NEW.run_context->>'intake_prompt_digest','') !~ '^[0-9a-f]{64}$' THEN
 RAISE EXCEPTION 'Intake run requires exact private sources and contract'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_intake_ai_run() FROM PUBLIC;
CREATE TRIGGER guard_intake_ai_run BEFORE INSERT OR UPDATE ON cehub_ai.agent_runs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_intake_ai_run();
CREATE FUNCTION cehub_ai.guard_intake_ai_finding() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r cehub_ai.agent_runs; cp cehub_ai.application_result_checkpoints;
BEGIN
 IF TG_OP='UPDATE' AND OLD.finding_type='intake_organization' THEN
  IF NEW IS DISTINCT FROM OLD THEN
   RAISE EXCEPTION 'Intake review and application are not yet enabled'; END IF;
  RETURN NEW;
 END IF;
 IF NEW.finding_type<>'intake_organization' THEN RETURN NEW; END IF;
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id
  AND project_id=NEW.project_id AND context_version='intake-organization-request-v1';
 SELECT * INTO cp FROM cehub_ai.application_result_checkpoints WHERE tenant_id=NEW.tenant_id
  AND run_id=NEW.run_id AND invocation_id=NEW.model_invocation_id;
 IF r.id IS NULL OR NEW.agent_key<>'knowledge_lite' OR NEW.status<>'pending_review'
  OR NEW.origin_key IS DISTINCT FROM 'intake:'||(r.run_context->>'intake_brief_id')
  OR NEW.proposed_payload->>'brief_id' IS DISTINCT FROM r.run_context->>'intake_brief_id'
  OR cp.id IS NULL OR cp.body->'output' IS DISTINCT FROM NEW.proposed_payload->'assessment'
  OR NOT cehub_ai.application_result_receipt_valid(cp.tenant_id,cp.run_id,cp.model_call_id,
    cp.observation_id,cp.manifest_id,cp.invocation_id,cp.owner_lease_id) THEN
  RAISE EXCEPTION 'Intake Finding needs its actual successful model receipt'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_intake_ai_finding() FROM PUBLIC;
CREATE TRIGGER guard_intake_ai_finding BEFORE INSERT OR UPDATE ON cehub_ai.findings
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_intake_ai_finding();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs
     WHERE context_version='intake-organization-request-v1') THEN
     RAISE EXCEPTION 'Intake run history must be retained'; END IF;
    END $$""")
    op.execute("DROP TRIGGER guard_intake_ai_finding ON cehub_ai.findings")
    op.execute("DROP FUNCTION cehub_ai.guard_intake_ai_finding()")
    op.execute("DROP TRIGGER guard_intake_ai_run ON cehub_ai.agent_runs")
    op.execute("DROP FUNCTION cehub_ai.guard_intake_ai_run()")
    op.execute(OLD)
