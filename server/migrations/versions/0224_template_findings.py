"""Organization Finding proposals, human review and atomic candidate provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0224_template_findings"
down_revision = "0223_tenant_template_runs"
branch_labels = None
depends_on = None
DDL = """
ALTER TABLE cehub_ai.findings ALTER COLUMN project_id DROP NOT NULL;
ALTER TABLE cehub_ai.findings ADD COLUMN scope_kind varchar(16) NOT NULL DEFAULT 'project';
ALTER TABLE cehub_ai.findings ADD CONSTRAINT fk_finding_run_scope FOREIGN
KEY(tenant_id,scope_kind,run_id,agent_key)
 REFERENCES cehub_ai.agent_runs(tenant_id,scope_kind,id,agent_key) ON DELETE RESTRICT;
ALTER TABLE cehub_core.process_template_revisions ADD COLUMN source_finding_id uuid;
ALTER TABLE cehub_core.process_template_revisions ADD CONSTRAINT fk_process_revision_finding
FOREIGN KEY(tenant_id,source_finding_id)
 REFERENCES cehub_ai.findings(tenant_id,id) ON DELETE RESTRICT;
ALTER TABLE cehub_core.process_template_revisions ADD CONSTRAINT uq_process_revision_finding
UNIQUE(tenant_id,source_finding_id);
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
ALTER TABLE cehub_ai.findings DROP CONSTRAINT ck_findings_apply_lifecycle_consistent;
ALTER TABLE cehub_ai.findings ADD CONSTRAINT ck_findings_apply_lifecycle_consistent CHECK
((status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL AND
applied_entity_type IS NULL AND applied_entity_id IS NULL) OR (status = 'applied' AND
applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL AND applied_entity_type IN ('risk',
'memory', 'issue', 'task', 'test_run', 'sample_build_configuration', 'knowledge_candidate',
'schedule_change_proposal', 'material_exception', 'test_plan', 'meeting_minutes', 'decision',
'ecr', 'change_impact_scope', 'quality_work_package', 'process_template_revision') AND
applied_entity_id IS NOT NULL AND reviewed_at < applied_at));
ALTER TABLE cehub_ai.findings ADD CONSTRAINT ck_findings_scope CHECK ((scope_kind='project' AND
project_id IS NOT NULL AND finding_type<>'process_template_configuration') OR
(scope_kind='tenant' AND project_id IS NULL AND agent_key='knowledge_lite' AND
finding_type='process_template_configuration'));
ALTER TABLE cehub_ai.finding_quality_controls DROP CONSTRAINT
ck_finding_quality_controls_type_allowed;
ALTER TABLE cehub_ai.finding_quality_controls ADD CONSTRAINT
ck_finding_quality_controls_type_allowed CHECK ((agent_key = 'project_intelligence' AND
finding_type IN ('risk_suggestion', 'blocker_alert', 'gate_readiness_anomaly')) OR (agent_key =
'knowledge_lite' AND finding_type IN ('knowledge_draft', 'meeting_minutes', 'meeting_action',
'meeting_decision', 'meeting_issue', 'meeting_risk', 'meeting_change',
'process_template_configuration')) OR (agent_key = 'engineering_intelligence' AND finding_type
IN ('bom_impact_suggestion', 'change_impact_suggestion', 'change_work_package')) OR (agent_key =
'quality_intelligence' AND finding_type IN ('quality_cluster_alert', 'capa_suggestion',
'test_plan_change', 'capa_work_package')) OR (agent_key = 'supplier_intelligence' AND
finding_type = 'supplier_delay_risk') OR (agent_key = 'executive_intelligence' AND finding_type
= 'executive_portfolio_brief'));

CREATE FUNCTION cehub_ai.guard_process_template_finding() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r cehub_ai.agent_runs; cp cehub_ai.application_result_checkpoints; actor uuid;
BEGIN
 IF TG_OP='UPDATE' AND (NEW.scope_kind,NEW.project_id) IS DISTINCT FROM
(OLD.scope_kind,OLD.project_id) THEN
  RAISE EXCEPTION 'Finding scope is immutable';
 END IF;
 IF NEW.scope_kind<>'tenant' THEN RETURN NEW; END IF;
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id
  AND scope_kind='tenant' AND agent_key='knowledge_lite' AND
context_version='process-template-request-v1';
 IF r.id IS NULL OR NEW.origin_key IS DISTINCT FROM
'process-template:'||(r.run_context->>'process_template_brief_id')
  OR NEW.proposed_payload->>'brief_id' IS DISTINCT FROM
r.run_context->>'process_template_brief_id' THEN
  RAISE EXCEPTION 'Organization Finding needs its original scoped request';
 END IF;
 IF TG_OP='INSERT' THEN
  SELECT * INTO cp FROM cehub_ai.application_result_checkpoints WHERE tenant_id=NEW.tenant_id
   AND run_id=NEW.run_id AND invocation_id=NEW.model_invocation_id;
  IF NEW.status<>'pending_review' OR cp.id IS NULL OR cp.body->'output' IS DISTINCT FROM
    NEW.proposed_payload->'assessment' OR NOT cehub_ai.application_result_receipt_valid(
cp.tenant_id,cp.run_id,cp.model_call_id,cp.observation_id,cp.manifest_id,cp.invocation_id,cp.owner_lease_id)
THEN
   RAISE EXCEPTION 'Organization Finding requires the known budgeted model result';
  END IF;
 ELSE
  IF (NEW.id,NEW.tenant_id,NEW.run_id,NEW.model_invocation_id,NEW.agent_key,NEW.finding_type,
   NEW.origin_key,NEW.title,NEW.summary,NEW.proposed_payload,NEW.evidence_event_ids,
   NEW.confidence_basis_points,NEW.preflight_version,NEW.created_at) IS DISTINCT FROM
   (OLD.id,OLD.tenant_id,OLD.run_id,OLD.model_invocation_id,OLD.agent_key,OLD.finding_type,
   OLD.origin_key,OLD.title,OLD.summary,OLD.proposed_payload,OLD.evidence_event_ids,
   OLD.confidence_basis_points,OLD.preflight_version,OLD.created_at) THEN
   RAISE EXCEPTION 'Original organization Finding is immutable';
  END IF;
  IF OLD.status='pending_review' AND NEW.status IN ('accepted','rejected') THEN
   actor:=NEW.reviewed_by_user_id;
   IF NEW.status='accepted' AND NEW.accepted_payload->>'brief_id' IS DISTINCT FROM
NEW.proposed_payload->>'brief_id' THEN
    RAISE EXCEPTION 'Accepted configuration cannot change original requirement';
   END IF;
  ELSIF OLD.status='accepted' AND NEW.status='applied' THEN
   actor:=NEW.applied_by_user_id;
   IF (NEW.accepted_payload,NEW.reviewed_at,NEW.reviewed_by_user_id,NEW.review_comment) IS
DISTINCT FROM
      (OLD.accepted_payload,OLD.reviewed_at,OLD.reviewed_by_user_id,OLD.review_comment)
    OR NOT EXISTS(SELECT 1 FROM cehub_core.process_template_revisions v WHERE
v.tenant_id=NEW.tenant_id
      AND v.id=NEW.applied_entity_id AND v.source_finding_id=NEW.id
      AND v.configuration=NEW.accepted_payload->'configuration') THEN
    RAISE EXCEPTION 'Apply requires the accepted payload and its atomically prepared candidate';
   END IF;
  ELSIF OLD.status='pending_review' AND NEW.status='archived' THEN
   RETURN NEW;
  ELSE RAISE EXCEPTION 'Organization Finding requires separate review and apply';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM cehub_core.users u JOIN cehub_core.tenants t ON t.id=u.tenant_id
   WHERE u.tenant_id=NEW.tenant_id AND u.id=actor AND u.is_active AND u.role IN ('owner','admin')
    AND t.status='active') THEN
   RAISE EXCEPTION 'Organization Finding requires a current named administrator';
  END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_process_template_finding() FROM PUBLIC;
CREATE TRIGGER guard_process_template_finding BEFORE INSERT OR UPDATE ON cehub_ai.findings
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_process_template_finding();
CREATE FUNCTION cehub_core.guard_process_template_finding_origin() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.source_finding_id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM cehub_ai.findings f WHERE f.tenant_id=NEW.tenant_id AND f.id=NEW.source_finding_id
   AND f.scope_kind='tenant' AND f.finding_type='process_template_configuration'
   AND f.status='accepted' AND f.accepted_payload->>'brief_id'=NEW.source_brief_id::text
   AND f.accepted_payload->'configuration'=NEW.configuration
 ) THEN RAISE EXCEPTION 'AI-origin configuration requires a matching accepted Finding'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_core.guard_process_template_finding_origin() FROM PUBLIC;
CREATE TRIGGER guard_process_template_finding_origin BEFORE INSERT ON
cehub_core.process_template_revisions
 FOR EACH ROW EXECUTE FUNCTION cehub_core.guard_process_template_finding_origin();
"""

OLD_CONSTRAINTS = {
    "ck_findings_type_allowed": """
(agent_key = 'project_intelligence' AND finding_type IN ('risk_suggestion', 'blocker_alert',
'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND finding_type IN
('knowledge_draft', 'meeting_minutes', 'meeting_action', 'meeting_decision', 'meeting_issue',
'meeting_risk', 'meeting_change')) OR (agent_key = 'engineering_intelligence' AND finding_type
IN ('bom_impact_suggestion', 'change_impact_suggestion', 'change_work_package')) OR (agent_key =
'quality_intelligence' AND finding_type IN ('quality_cluster_alert', 'capa_suggestion',
'test_plan_change', 'capa_work_package')) OR (agent_key = 'supplier_intelligence' AND
finding_type = 'supplier_delay_risk') OR (agent_key = 'executive_intelligence' AND finding_type
= 'executive_portfolio_brief')""",
    "ck_findings_evidence_event_ids_array": """
jsonb_typeof(evidence_event_ids) = 'array' AND (jsonb_array_length(evidence_event_ids) > 0 OR
(finding_type IN
('meeting_minutes','meeting_action','meeting_decision','meeting_issue','meeting_risk','meeting_change','change_work_package','capa_work_package')
AND evidence_event_ids='[]'::jsonb))""",
    "ck_findings_apply_lifecycle_consistent": """
(status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL AND
applied_entity_type IS NULL AND applied_entity_id IS NULL) OR (status = 'applied' AND
applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL AND applied_entity_type IN ('risk',
'memory', 'issue', 'task', 'test_run', 'sample_build_configuration', 'knowledge_candidate',
'schedule_change_proposal', 'material_exception', 'test_plan', 'meeting_minutes', 'decision',
'ecr', 'change_impact_scope', 'quality_work_package') AND applied_entity_id IS NOT NULL AND
reviewed_at < applied_at)""",
}


def upgrade() -> None:
    op.execute(sa.text(DDL))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT EXISTS(SELECT 1 FROM cehub_ai.findings WHERE scope_kind='tenant')")
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to discard organization Finding history")
    op.execute(
        "DROP TRIGGER guard_process_template_finding_origin ON "
        "cehub_core.process_template_revisions"
    )
    op.execute("DROP FUNCTION cehub_core.guard_process_template_finding_origin()")
    op.execute("DROP TRIGGER guard_process_template_finding ON cehub_ai.findings")
    op.execute("DROP FUNCTION cehub_ai.guard_process_template_finding()")
    op.drop_constraint(
        "fk_process_revision_finding",
        "process_template_revisions",
        schema="cehub_core",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_process_revision_finding",
        "process_template_revisions",
        schema="cehub_core",
        type_="unique",
    )
    op.drop_column("process_template_revisions", "source_finding_id", schema="cehub_core")
    op.drop_constraint("fk_finding_run_scope", "findings", schema="cehub_ai", type_="foreignkey")
    op.drop_constraint(op.f("ck_findings_scope"), "findings", schema="cehub_ai", type_="check")
    op.drop_column("findings", "scope_kind", schema="cehub_ai")
    op.alter_column("findings", "project_id", nullable=False, schema="cehub_ai")
    for name, value in OLD_CONSTRAINTS.items():
        op.execute(f"ALTER TABLE cehub_ai.findings DROP CONSTRAINT {name}")
        op.execute(f"ALTER TABLE cehub_ai.findings ADD CONSTRAINT {name} CHECK ({value})")
    op.execute(
        "ALTER TABLE cehub_ai.finding_quality_controls DROP CONSTRAINT "
        "ck_finding_quality_controls_type_allowed"
    )
    op.execute(
        "ALTER TABLE cehub_ai.finding_quality_controls ADD CONSTRAINT "
        "ck_finding_quality_controls_type_allowed CHECK ("
        + OLD_CONSTRAINTS["ck_findings_type_allowed"]
        + ")"
    )
