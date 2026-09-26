"""Typed quality Findings apply to original Tasks and CAPA actions, never root approval."""

import sqlalchemy as sa
from alembic import op

revision = "0200_quality_work_package_application"
down_revision = "0199_fmea_revision_candidates"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_quality.quality_work_package_applications (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        ncr_id UUID NOT NULL,
        finding_id UUID NOT NULL,
        run_id UUID NOT NULL,
        source_digest VARCHAR(64) NOT NULL,
        phase VARCHAR(32) NOT NULL,
        review JSONB NOT NULL,
        source_snapshot JSONB NOT NULL,
        created_by_user_id UUID NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        CONSTRAINT pk_quality_work_package_applications PRIMARY KEY (id),
        CONSTRAINT uq_quality_package_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT uq_quality_package_finding UNIQUE (finding_id),
        CONSTRAINT uq_quality_package_input UNIQUE (tenant_id, project_id, ncr_id,
source_digest),
        CONSTRAINT fk_quality_work_package_applications_tenant_id_nonconfo_74fc FOREIGN
KEY(tenant_id, project_id, ncr_id) REFERENCES cehub_quality.nonconformance_reports (tenant_id,
project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_quality_work_package_applications_tenant_id_findings FOREIGN
KEY(tenant_id, project_id, finding_id) REFERENCES cehub_ai.findings (tenant_id, project_id, id)
ON DELETE RESTRICT,
        CONSTRAINT fk_quality_work_package_applications_tenant_id_agent_runs FOREIGN
KEY(tenant_id, run_id) REFERENCES cehub_ai.agent_runs (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_quality_work_package_applications_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_quality_work_package_applications_shape CHECK (source_digest ~
'^[a-f0-9]{64}$' AND phase IN ('investigation','actions') AND jsonb_typeof(review)='object' AND
jsonb_typeof(source_snapshot)='object')
)

;

CREATE TABLE cehub_quality.quality_work_package_items (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        application_id UUID NOT NULL,
        proposal_key VARCHAR(80) NOT NULL,
        task_id UUID,
        capa_action_id UUID,
        CONSTRAINT pk_quality_work_package_items PRIMARY KEY (id),
        CONSTRAINT uq_quality_package_item_key UNIQUE (application_id, proposal_key),
        CONSTRAINT uq_quality_package_task UNIQUE (task_id),
        CONSTRAINT uq_quality_package_capa UNIQUE (capa_action_id),
        CONSTRAINT fk_quality_work_package_items_tenant_id_quality_work_pa_b474 FOREIGN
KEY(tenant_id, project_id, application_id) REFERENCES
cehub_quality.quality_work_package_applications (tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_quality_work_package_items_tenant_id_tasks FOREIGN KEY(tenant_id,
project_id, task_id) REFERENCES cehub_project.tasks (tenant_id, project_id, id) ON DELETE
RESTRICT,
        CONSTRAINT fk_quality_work_package_items_tenant_id_capa_actions FOREIGN KEY(tenant_id,
project_id, capa_action_id) REFERENCES cehub_quality.capa_actions (tenant_id, project_id, id) ON
DELETE RESTRICT,
        CONSTRAINT ck_quality_work_package_items_shape CHECK (btrim(proposal_key)<>'' AND
((task_id IS NOT NULL AND capa_action_id IS NULL) OR (task_id IS NULL AND capa_action_id IS NOT
NULL)))
)

;
"""
GUARDS = """
CREATE FUNCTION cehub_quality.guard_quality_package() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE f cehub_ai.findings%ROWTYPE;
BEGIN
SELECT * INTO f FROM cehub_ai.findings WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=NEW.finding_id;
IF f.id IS NULL OR f.finding_type<>'capa_work_package' OR f.status<>'accepted'
OR f.run_id<>NEW.run_id OR f.accepted_payload->>'ncr_id'<>NEW.ncr_id::text
OR f.accepted_payload->>'source_digest'<>NEW.source_digest
OR f.accepted_payload->'review' IS DISTINCT FROM NEW.review
OR f.accepted_payload->'assessment'->>'phase' IS DISTINCT FROM NEW.phase
OR NEW.source_snapshot->>'digest' IS DISTINCT FROM NEW.source_digest
THEN RAISE EXCEPTION 'Quality application requires its exact accepted finding' USING
ERRCODE='23514'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER guard_quality_package BEFORE INSERT ON
cehub_quality.quality_work_package_applications
FOR EACH ROW EXECUTE FUNCTION cehub_quality.guard_quality_package();

CREATE FUNCTION cehub_quality.guard_quality_package_item() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE a cehub_quality.quality_work_package_applications%ROWTYPE;
DECLARE selected jsonb;
DECLARE proposed jsonb;
BEGIN
SELECT * INTO a FROM cehub_quality.quality_work_package_applications WHERE
tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=NEW.application_id;
SELECT x INTO selected FROM jsonb_array_elements(a.review->'choices') x
WHERE x->>'key'=NEW.proposal_key AND x->>'disposition'='adopt';
SELECT x INTO proposed FROM cehub_ai.findings f,
jsonb_array_elements(f.accepted_payload->'assessment'->'work') x
WHERE f.id=a.finding_id AND f.tenant_id=a.tenant_id AND f.status='accepted'
AND x->>'key'=NEW.proposal_key;
IF selected IS NULL OR proposed IS NULL THEN
RAISE EXCEPTION 'Quality work must match adopted proposal' USING ERRCODE='23514'; END IF;
IF proposed->>'kind'='investigation' THEN
IF NEW.capa_action_id IS NOT NULL OR NOT EXISTS(SELECT 1 FROM cehub_project.tasks t
WHERE t.tenant_id=NEW.tenant_id AND t.project_id=NEW.project_id AND t.id=NEW.task_id
AND t.status='todo' AND t.assignee_user_id::text=selected->>'owner_user_id'
AND t.due_date::text=selected->>'due_date' AND t.expected_output=selected->>'expected_evidence')
THEN RAISE EXCEPTION 'Investigation needs actual assigned task' USING ERRCODE='23514'; END IF;
ELSE
IF NEW.task_id IS NOT NULL OR NOT EXISTS(SELECT 1 FROM cehub_quality.capa_actions ca
WHERE ca.tenant_id=NEW.tenant_id AND ca.project_id=NEW.project_id AND ca.id=NEW.capa_action_id
AND ca.ncr_id=a.ncr_id AND ca.status='planned' AND ca.action_type=proposed->>'kind'
AND ca.owner_user_id::text=selected->>'owner_user_id' AND
ca.due_date::text=selected->>'due_date')
THEN RAISE EXCEPTION 'Quality work needs actual planned CAPA action' USING ERRCODE='23514'; END
IF;
END IF;
RETURN NEW;
END $$;
CREATE TRIGGER guard_quality_package_item BEFORE INSERT ON
cehub_quality.quality_work_package_items
FOR EACH ROW EXECUTE FUNCTION cehub_quality.guard_quality_package_item();

CREATE FUNCTION cehub_ai.guard_quality_finding_application() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE a cehub_quality.quality_work_package_applications%ROWTYPE;
DECLARE expected_count integer;
BEGIN
IF NEW.finding_type<>'capa_work_package' THEN RETURN NEW; END IF;
IF NEW.accepted_payload IS NOT NULL AND (
NEW.accepted_payload-'review'-'details_confirmed' IS DISTINCT FROM
NEW.proposed_payload-'review'-'details_confirmed'
OR NEW.accepted_payload->'details_confirmed' IS DISTINCT FROM 'true'::jsonb
OR jsonb_typeof(NEW.accepted_payload->'review') IS DISTINCT FROM 'object') THEN
RAISE EXCEPTION 'Quality finding requires original proposal and human choices' USING
ERRCODE='23514'; END IF;
IF TG_OP='UPDATE' AND OLD.accepted_payload IS NOT NULL AND
NEW.accepted_payload IS DISTINCT FROM OLD.accepted_payload THEN
RAISE EXCEPTION 'Accepted quality payload is immutable' USING ERRCODE='23514'; END IF;
IF NEW.status='applied' THEN
SELECT * INTO a FROM cehub_quality.quality_work_package_applications WHERE
tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND finding_id=NEW.id AND id=NEW.applied_entity_id;
SELECT count(*) INTO expected_count FROM
jsonb_array_elements(NEW.accepted_payload->'review'->'choices') x
WHERE x->>'disposition'='adopt';
IF NEW.applied_entity_type IS DISTINCT FROM 'quality_work_package' OR a.id IS NULL
OR a.created_by_user_id<>NEW.applied_by_user_id OR a.run_id<>NEW.run_id
OR a.review IS DISTINCT FROM NEW.accepted_payload->'review' OR expected_count<1
OR expected_count<>(SELECT count(*) FROM cehub_quality.quality_work_package_items WHERE
application_id=a.id)
THEN RAISE EXCEPTION 'Quality finding must reference complete actual application'
USING ERRCODE='23514'; END IF;
END IF;
RETURN NEW;
END $$;
CREATE TRIGGER guard_quality_finding_application BEFORE INSERT OR UPDATE ON cehub_ai.findings
FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_quality_finding_application();

CREATE FUNCTION cehub_quality.guard_investigation_completion() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
IF NEW.status='done' AND btrim(coalesce(NEW.completion_evidence_ref,''))=''
AND EXISTS(SELECT 1 FROM cehub_quality.quality_work_package_items w WHERE
w.tenant_id=NEW.tenant_id
AND w.project_id=NEW.project_id AND w.task_id=NEW.id)
THEN RAISE EXCEPTION 'Quality investigation completion requires actual evidence' USING
ERRCODE='23514'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER guard_investigation_completion BEFORE UPDATE ON cehub_project.tasks
FOR EACH ROW EXECUTE FUNCTION cehub_quality.guard_investigation_completion();
"""
CHANGES = [
    (
        "findings",
        "ck_findings_type_allowed",
        """
(agent_key = 'project_intelligence' AND finding_type IN ('risk_suggestion', 'blocker_alert',
'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND finding_type IN
('knowledge_draft', 'meeting_minutes', 'meeting_action', 'meeting_decision', 'meeting_issue',
'meeting_risk', 'meeting_change')) OR (agent_key = 'engineering_intelligence' AND finding_type
IN ('bom_impact_suggestion', 'change_impact_suggestion', 'change_work_package')) OR (agent_key =
'quality_intelligence' AND finding_type IN ('quality_cluster_alert', 'capa_suggestion',
'test_plan_change')) OR (agent_key = 'supplier_intelligence' AND finding_type =
'supplier_delay_risk') OR (agent_key = 'executive_intelligence' AND finding_type =
'executive_portfolio_brief')
""",
        """
(agent_key = 'project_intelligence' AND finding_type IN ('risk_suggestion', 'blocker_alert',
'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND finding_type IN
('knowledge_draft', 'meeting_minutes', 'meeting_action', 'meeting_decision', 'meeting_issue',
'meeting_risk', 'meeting_change')) OR (agent_key = 'engineering_intelligence' AND finding_type
IN ('bom_impact_suggestion', 'change_impact_suggestion', 'change_work_package')) OR (agent_key =
'quality_intelligence' AND finding_type IN ('quality_cluster_alert', 'capa_suggestion',
'test_plan_change', 'capa_work_package')) OR (agent_key = 'supplier_intelligence' AND
finding_type = 'supplier_delay_risk') OR (agent_key = 'executive_intelligence' AND finding_type
= 'executive_portfolio_brief')
""",
    ),
    (
        "findings",
        "ck_findings_evidence_event_ids_array",
        """
jsonb_typeof(evidence_event_ids) = 'array' AND (jsonb_array_length(evidence_event_ids) > 0 OR
(finding_type IN
('meeting_minutes','meeting_action','meeting_decision','meeting_issue','meeting_risk','meeting_change','change_work_package')
AND evidence_event_ids='[]'::jsonb))
""",
        """
jsonb_typeof(evidence_event_ids) = 'array' AND (jsonb_array_length(evidence_event_ids) > 0 OR
(finding_type IN
('meeting_minutes','meeting_action','meeting_decision','meeting_issue','meeting_risk','meeting_change','change_work_package','capa_work_package')
AND evidence_event_ids='[]'::jsonb))
""",
    ),
    (
        "findings",
        "ck_findings_apply_lifecycle_consistent",
        """
(status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL AND
applied_entity_type IS NULL AND applied_entity_id IS NULL) OR (status = 'applied' AND
applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL AND applied_entity_type IN ('risk',
'memory', 'issue', 'task', 'test_run', 'sample_build_configuration', 'knowledge_candidate',
'schedule_change_proposal', 'material_exception', 'test_plan', 'meeting_minutes', 'decision',
'ecr', 'change_impact_scope') AND applied_entity_id IS NOT NULL AND reviewed_at < applied_at)
""",
        """
(status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL AND
applied_entity_type IS NULL AND applied_entity_id IS NULL) OR (status = 'applied' AND
applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL AND applied_entity_type IN ('risk',
'memory', 'issue', 'task', 'test_run', 'sample_build_configuration', 'knowledge_candidate',
'schedule_change_proposal', 'material_exception', 'test_plan', 'meeting_minutes', 'decision',
'ecr', 'change_impact_scope', 'quality_work_package') AND applied_entity_id IS NOT NULL AND
reviewed_at < applied_at)
""",
    ),
    (
        "finding_quality_controls",
        "ck_finding_quality_controls_type_allowed",
        """
(agent_key = 'project_intelligence' AND finding_type IN ('risk_suggestion', 'blocker_alert',
'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND finding_type IN
('knowledge_draft', 'meeting_minutes', 'meeting_action', 'meeting_decision', 'meeting_issue',
'meeting_risk', 'meeting_change')) OR (agent_key = 'engineering_intelligence' AND finding_type
IN ('bom_impact_suggestion', 'change_impact_suggestion', 'change_work_package')) OR (agent_key =
'quality_intelligence' AND finding_type IN ('quality_cluster_alert', 'capa_suggestion',
'test_plan_change')) OR (agent_key = 'supplier_intelligence' AND finding_type =
'supplier_delay_risk') OR (agent_key = 'executive_intelligence' AND finding_type =
'executive_portfolio_brief')
""",
        """
(agent_key = 'project_intelligence' AND finding_type IN ('risk_suggestion', 'blocker_alert',
'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND finding_type IN
('knowledge_draft', 'meeting_minutes', 'meeting_action', 'meeting_decision', 'meeting_issue',
'meeting_risk', 'meeting_change')) OR (agent_key = 'engineering_intelligence' AND finding_type
IN ('bom_impact_suggestion', 'change_impact_suggestion', 'change_work_package')) OR (agent_key =
'quality_intelligence' AND finding_type IN ('quality_cluster_alert', 'capa_suggestion',
'test_plan_change', 'capa_work_package')) OR (agent_key = 'supplier_intelligence' AND
finding_type = 'supplier_delay_risk') OR (agent_key = 'executive_intelligence' AND finding_type
= 'executive_portfolio_brief')
""",
    ),
    (
        "agent_runs",
        "ck_agent_runs_event_bounds_consistent",
        """
(((agent_key = 'ai_chat' OR (agent_key = 'quality_intelligence' AND context_version =
'report-mapping-request-v1') OR (agent_key='knowledge_lite' AND context_version IN
('meeting-reading-request-v1','meeting-minutes-request-v1','meeting-actions-request-v1','meeting-decisions-request-v1','meeting-business-request-v1'))
OR (agent_key='engineering_intelligence' AND context_version='change-work-package-request-v1'))
AND subscription_id IS NULL AND first_event_row_id IS NULL AND last_event_row_id IS NULL AND
event_count = 0 AND event_row_ids = '[]'::jsonb AND request_id IS NOT NULL AND btrim(request_id)
<> '' AND requested_by_user_id IS NOT NULL AND (status IN ('running', 'succeeded', 'degraded',
'failed') OR (agent_key IN ('ai_chat','quality_intelligence') AND status = 'queued'))) OR
(agent_key <> 'ai_chat' AND subscription_id IS NOT NULL AND ((request_id IS NULL AND
requested_by_user_id IS NULL) OR ((agent_key='project_intelligence' AND
context_version='risk-suggestion-request-v1' OR agent_key='quality_intelligence' AND
context_version='test-plan-request-v1') AND request_id IS NOT NULL AND btrim(request_id)<>'' AND
requested_by_user_id IS NOT NULL)) AND first_event_row_id IS NOT NULL AND last_event_row_id IS
NOT NULL AND CASE WHEN jsonb_typeof(event_row_ids) = 'array' THEN event_count > 0 AND
first_event_row_id > 0 AND last_event_row_id >= first_event_row_id AND
jsonb_array_length(event_row_ids) = event_count AND (event_row_ids->>0)::bigint =
first_event_row_id AND (event_row_ids->>(event_count - 1))::bigint = last_event_row_id ELSE
false END)) IS TRUE
""",
        """
(((agent_key = 'ai_chat' OR (agent_key = 'quality_intelligence' AND context_version IN
('report-mapping-request-v1', 'quality-work-package-request-v1')) OR (agent_key='knowledge_lite'
AND context_version IN
('meeting-reading-request-v1','meeting-minutes-request-v1','meeting-actions-request-v1','meeting-decisions-request-v1','meeting-business-request-v1'))
OR (agent_key='engineering_intelligence' AND context_version='change-work-package-request-v1'))
AND subscription_id IS NULL AND first_event_row_id IS NULL AND last_event_row_id IS NULL AND
event_count = 0 AND event_row_ids = '[]'::jsonb AND request_id IS NOT NULL AND btrim(request_id)
<> '' AND requested_by_user_id IS NOT NULL AND (status IN ('running', 'succeeded', 'degraded',
'failed') OR (agent_key IN ('ai_chat','quality_intelligence') AND status = 'queued'))) OR
(agent_key <> 'ai_chat' AND subscription_id IS NOT NULL AND ((request_id IS NULL AND
requested_by_user_id IS NULL) OR ((agent_key='project_intelligence' AND
context_version='risk-suggestion-request-v1' OR agent_key='quality_intelligence' AND
context_version='test-plan-request-v1') AND request_id IS NOT NULL AND btrim(request_id)<>'' AND
requested_by_user_id IS NOT NULL)) AND first_event_row_id IS NOT NULL AND last_event_row_id IS
NOT NULL AND CASE WHEN jsonb_typeof(event_row_ids) = 'array' THEN event_count > 0 AND
first_event_row_id > 0 AND last_event_row_id >= first_event_row_id AND
jsonb_array_length(event_row_ids) = event_count AND (event_row_ids->>0)::bigint =
first_event_row_id AND (event_row_ids->>(event_count - 1))::bigint = last_event_row_id ELSE
false END)) IS TRUE
""",
    ),
]


def upgrade() -> None:
    op.execute(DDL)
    for table, name, _old, new in CHANGES:
        op.drop_constraint(op.f(name), table, schema="cehub_ai")
        op.create_check_constraint(op.f(name), table, new, schema="cehub_ai")
    op.execute(GUARDS)
    for table in ("quality_work_package_applications", "quality_work_package_items"):
        op.execute(
            f"CREATE TRIGGER protect_{table} BEFORE UPDATE OR DELETE ON cehub_quality.{table} "
            "FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history()"
        )
        op.execute(f"REVOKE ALL ON cehub_quality.{table} FROM PUBLIC")


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
SELECT EXISTS(SELECT 1 FROM cehub_ai.findings WHERE finding_type='capa_work_package')
    OR EXISTS(SELECT 1 FROM cehub_ai.agent_runs
    WHERE context_version='quality-work-package-request-v1')
    OR EXISTS(SELECT 1 FROM cehub_ai.finding_quality_controls
    WHERE finding_type='capa_work_package')
    OR EXISTS(SELECT 1 FROM cehub_quality.quality_work_package_applications)""")
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to discard quality work-package history")
    op.execute("DROP TRIGGER guard_investigation_completion ON cehub_project.tasks")
    op.execute("DROP FUNCTION cehub_quality.guard_investigation_completion()")
    op.execute("DROP TRIGGER guard_quality_finding_application ON cehub_ai.findings")
    op.execute("DROP FUNCTION cehub_ai.guard_quality_finding_application()")
    op.drop_table("quality_work_package_items", schema="cehub_quality")
    op.drop_table("quality_work_package_applications", schema="cehub_quality")
    op.execute("DROP FUNCTION cehub_quality.guard_quality_package_item()")
    op.execute("DROP FUNCTION cehub_quality.guard_quality_package()")
    for table, name, old, _new in reversed(CHANGES):
        op.drop_constraint(op.f(name), table, schema="cehub_ai")
        op.create_check_constraint(op.f(name), table, old, schema="cehub_ai")
