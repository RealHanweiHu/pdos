"""Source-bound cost findings, human review and atomic alternative applications."""

from alembic import op

revision = "0331_cost_reduction_findings"
down_revision = "0330_cost_reduction_runs"
branch_labels = None
depends_on = None

OLD = {
    "findings|ck_findings_evidence_event_ids_array": """
jsonb_typeof(evidence_event_ids) = 'array' AND (jsonb_array_length(evidence_event_ids) > 0
OR (finding_type IN
('meeting_minutes','meeting_action','meeting_decision','meeting_issue','meeting_risk','meeting_change','change_work_package','capa_work_package','supplier_recovery','process_template_configuration','intake_organization','meeting_plan')
AND evidence_event_ids='[]'::jsonb))
""",
    "findings|ck_findings_apply_lifecycle_consistent": """
(status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL AND
applied_entity_type IS NULL AND applied_entity_id IS NULL) OR (status = 'applied' AND
applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL AND applied_entity_type IN
('risk', 'memory', 'issue', 'task', 'test_run', 'sample_build_configuration',
'knowledge_candidate', 'schedule_change_proposal', 'material_exception', 'test_plan',
'meeting_minutes', 'decision', 'ecr', 'change_impact_scope', 'quality_work_package',
'supplier_recovery', 'process_template_revision', 'project_intake_proposal', 'meeting') AND
applied_entity_id IS NOT NULL AND reviewed_at < applied_at)
""",
    "findings|ck_findings_type_allowed": """
(agent_key = 'project_intelligence' AND finding_type IN ('risk_suggestion', 'blocker_alert',
'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND finding_type IN
('knowledge_draft', 'meeting_minutes', 'meeting_action', 'meeting_decision',
'meeting_issue', 'meeting_risk', 'meeting_change',
'process_template_configuration','intake_organization','meeting_plan')) OR (agent_key =
'engineering_intelligence' AND finding_type IN ('bom_impact_suggestion',
'change_impact_suggestion', 'change_work_package')) OR (agent_key = 'quality_intelligence'
AND finding_type IN ('quality_cluster_alert', 'capa_suggestion', 'test_plan_change',
'capa_work_package')) OR (agent_key = 'supplier_intelligence' AND finding_type IN
('supplier_delay_risk','supplier_recovery')) OR (agent_key = 'executive_intelligence' AND
finding_type = 'executive_portfolio_brief')
""",
    "finding_quality_controls|ck_finding_quality_controls_type_allowed": """
(agent_key = 'project_intelligence' AND finding_type IN ('risk_suggestion', 'blocker_alert',
'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND finding_type IN
('knowledge_draft', 'meeting_minutes', 'meeting_action', 'meeting_decision',
'meeting_issue', 'meeting_risk', 'meeting_change',
'process_template_configuration','intake_organization','meeting_plan')) OR (agent_key =
'engineering_intelligence' AND finding_type IN ('bom_impact_suggestion',
'change_impact_suggestion', 'change_work_package')) OR (agent_key = 'quality_intelligence'
AND finding_type IN ('quality_cluster_alert', 'capa_suggestion', 'test_plan_change',
'capa_work_package')) OR (agent_key = 'supplier_intelligence' AND finding_type IN
('supplier_delay_risk','supplier_recovery')) OR (agent_key = 'executive_intelligence' AND
finding_type = 'executive_portfolio_brief')
""",
}
NEW = {
    "findings|ck_findings_evidence_event_ids_array": """
jsonb_typeof(evidence_event_ids) = 'array' AND (jsonb_array_length(evidence_event_ids) > 0
OR (finding_type IN
('meeting_minutes','meeting_action','meeting_decision','meeting_issue','meeting_risk','meeting_change','change_work_package','capa_work_package','supplier_recovery','cost_reduction','process_template_configuration','intake_organization','meeting_plan')
AND evidence_event_ids='[]'::jsonb))
""",
    "findings|ck_findings_apply_lifecycle_consistent": """
(status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL AND
applied_entity_type IS NULL AND applied_entity_id IS NULL) OR (status = 'applied' AND
applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL AND applied_entity_type IN
('risk', 'memory', 'issue', 'task', 'test_run', 'sample_build_configuration',
'knowledge_candidate', 'schedule_change_proposal', 'material_exception', 'test_plan',
'meeting_minutes', 'decision', 'ecr', 'change_impact_scope', 'quality_work_package',
'supplier_recovery', 'cost_reduction', 'process_template_revision',
'project_intake_proposal', 'meeting') AND applied_entity_id IS NOT NULL AND reviewed_at <
applied_at)
""",
    "findings|ck_findings_type_allowed": """
(agent_key = 'project_intelligence' AND finding_type IN ('risk_suggestion', 'blocker_alert',
'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND finding_type IN
('knowledge_draft', 'meeting_minutes', 'meeting_action', 'meeting_decision',
'meeting_issue', 'meeting_risk', 'meeting_change',
'process_template_configuration','intake_organization','meeting_plan')) OR (agent_key =
'engineering_intelligence' AND finding_type IN ('bom_impact_suggestion',
'change_impact_suggestion', 'change_work_package', 'cost_reduction')) OR (agent_key =
'quality_intelligence' AND finding_type IN ('quality_cluster_alert', 'capa_suggestion',
'test_plan_change', 'capa_work_package')) OR (agent_key = 'supplier_intelligence' AND
finding_type IN ('supplier_delay_risk','supplier_recovery')) OR (agent_key =
'executive_intelligence' AND finding_type = 'executive_portfolio_brief')
""",
    "finding_quality_controls|ck_finding_quality_controls_type_allowed": """
(agent_key = 'project_intelligence' AND finding_type IN ('risk_suggestion', 'blocker_alert',
'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND finding_type IN
('knowledge_draft', 'meeting_minutes', 'meeting_action', 'meeting_decision',
'meeting_issue', 'meeting_risk', 'meeting_change',
'process_template_configuration','intake_organization','meeting_plan')) OR (agent_key =
'engineering_intelligence' AND finding_type IN ('bom_impact_suggestion',
'change_impact_suggestion', 'change_work_package', 'cost_reduction')) OR (agent_key =
'quality_intelligence' AND finding_type IN ('quality_cluster_alert', 'capa_suggestion',
'test_plan_change', 'capa_work_package')) OR (agent_key = 'supplier_intelligence' AND
finding_type IN ('supplier_delay_risk','supplier_recovery')) OR (agent_key =
'executive_intelligence' AND finding_type = 'executive_portfolio_brief')
""",
}

DDL = """

CREATE TABLE cehub_cost.cost_reduction_applications (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	finding_id UUID NOT NULL, 
	run_id UUID NOT NULL, 
	source_digest VARCHAR(64) NOT NULL, 
	review JSONB NOT NULL, 
	source_snapshot JSONB NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_cost_reduction_applications PRIMARY KEY (id), 
	CONSTRAINT uq_cost_reduction_scope UNIQUE (tenant_id, project_id, id), 
	CONSTRAINT uq_cost_reduction_finding UNIQUE (finding_id), 
	CONSTRAINT uq_cost_reduction_input UNIQUE (tenant_id, project_id, source_digest), 
        CONSTRAINT fk_cost_reduction_applications_tenant_id_findings FOREIGN KEY(tenant_id,
project_id, finding_id) REFERENCES cehub_ai.findings (tenant_id, project_id, id) ON DELETE
RESTRICT,
        CONSTRAINT fk_cost_reduction_applications_tenant_id_agent_runs FOREIGN KEY(tenant_id,
run_id) REFERENCES cehub_ai.agent_runs (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_reduction_applications_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_cost_reduction_applications_shape CHECK (source_digest ~ '^[a-f0-9]{64}$'
AND jsonb_typeof(review)='object' AND jsonb_typeof(source_snapshot)='object')
)

;

CREATE TABLE cehub_cost.cost_reduction_items (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	application_id UUID NOT NULL, 
	proposal_key VARCHAR(80) NOT NULL, 
	alternative_id UUID NOT NULL, 
	CONSTRAINT pk_cost_reduction_items PRIMARY KEY (id), 
	CONSTRAINT uq_cost_reduction_item_key UNIQUE (application_id, proposal_key), 
	CONSTRAINT uq_cost_reduction_alternative UNIQUE (alternative_id), 
	CONSTRAINT uq_cost_reduction_item_scope UNIQUE (tenant_id, project_id, id), 
        CONSTRAINT fk_cost_reduction_items_tenant_id_cost_reduction_applications FOREIGN
KEY(tenant_id, project_id, application_id) REFERENCES cehub_cost.cost_reduction_applications
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_reduction_items_tenant_id_cost_alternatives FOREIGN KEY(tenant_id,
project_id, alternative_id) REFERENCES cehub_cost.cost_alternatives (tenant_id, project_id, id)
ON DELETE RESTRICT,
	CONSTRAINT ck_cost_reduction_items_shape CHECK (btrim(proposal_key)<>'')
)

;
"""

ORIGIN = """

CREATE FUNCTION cehub_ai.guard_cost_reduction_origin() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='UPDATE' AND OLD.finding_type='cost_reduction' AND
 (NEW.finding_type<>OLD.finding_type OR NEW.proposed_payload IS DISTINCT FROM
OLD.proposed_payload
 OR NEW.run_id<>OLD.run_id OR NEW.model_invocation_id IS DISTINCT FROM OLD.model_invocation_id)
 THEN RAISE EXCEPTION 'Cost reduction candidate origin is immutable'; END IF;
 IF NEW.finding_type<>'cost_reduction' THEN RETURN NEW; END IF;
 IF NEW.evidence_event_ids<>'[]'::jsonb OR NOT EXISTS (
 SELECT 1 FROM cehub_ai.agent_runs r JOIN cehub_ai.model_invocations i
 ON i.tenant_id=r.tenant_id AND i.project_id=r.project_id AND i.run_id=r.id
 WHERE r.tenant_id=NEW.tenant_id AND r.project_id=NEW.project_id AND r.id=NEW.run_id
 AND r.agent_key='engineering_intelligence' AND r.context_version='cost-reduction-request-v1'
 AND r.run_context->>'cost_output_mode'='reviewable.v1'
 AND i.id=NEW.model_invocation_id AND i.agent_key=r.agent_key AND i.status='succeeded'
 AND i.prompt_version=r.run_context->>'cost_prompt_version'
 AND NEW.proposed_payload->>'source_digest'=r.run_context->'cost_source'->>'digest'
 AND NEW.proposed_payload->'selection'=r.run_context->'cost_source'->'selection'
 AND r.run_context->'cost_source'->>'project_id'=NEW.project_id::text
 ) THEN RAISE EXCEPTION 'Cost reduction requires actual successful model receipt and
sources';
 END IF;
 IF NEW.accepted_payload IS NOT NULL AND EXISTS(SELECT 1 FROM
 unnest(ARRAY['source_digest','selection','assessment']) k
 WHERE NEW.accepted_payload->k IS DISTINCT FROM NEW.proposed_payload->k) THEN
 RAISE EXCEPTION 'Review must retain original cost source and assessment'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_cost_reduction_origin BEFORE INSERT OR UPDATE ON cehub_ai.findings
FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_cost_reduction_origin();
REVOKE ALL ON FUNCTION cehub_ai.guard_cost_reduction_origin() FROM PUBLIC;

"""

GUARDS = """

CREATE FUNCTION cehub_cost.guard_cost_reduction_application() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE f cehub_ai.findings%ROWTYPE;
DECLARE original jsonb;
BEGIN
SELECT * INTO f FROM cehub_ai.findings WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=NEW.finding_id;
SELECT run_context->'cost_source' INTO original FROM cehub_ai.agent_runs
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.run_id;
IF f.id IS NULL OR f.finding_type<>'cost_reduction' OR f.status<>'accepted'
OR f.run_id<>NEW.run_id
OR f.accepted_payload->>'source_digest' IS DISTINCT FROM NEW.source_digest
OR f.accepted_payload->'review' IS DISTINCT FROM NEW.review
OR NEW.source_snapshot IS DISTINCT FROM original
OR NEW.source_snapshot->>'digest' IS DISTINCT FROM NEW.source_digest
THEN RAISE EXCEPTION 'Cost reduction requires exact accepted finding and fixed source'
USING ERRCODE='23514'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER guard_cost_reduction_application BEFORE INSERT ON
cehub_cost.cost_reduction_applications FOR EACH ROW
EXECUTE FUNCTION cehub_cost.guard_cost_reduction_application();

CREATE FUNCTION cehub_cost.guard_cost_reduction_item() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE a cehub_cost.cost_reduction_applications%ROWTYPE;
DECLARE chosen jsonb;
BEGIN
SELECT * INTO a FROM cehub_cost.cost_reduction_applications
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.application_id;
SELECT x INTO chosen FROM jsonb_array_elements(a.review->'choices') x
WHERE x->>'key'=NEW.proposal_key AND x->>'disposition'='adopt';
IF chosen IS NULL OR NOT EXISTS(SELECT 1 FROM cehub_ai.findings f,
jsonb_array_elements(f.accepted_payload->'assessment'->'options') o
WHERE f.id=a.finding_id AND f.tenant_id=NEW.tenant_id AND f.project_id=NEW.project_id
AND f.status='accepted' AND o->>'key'=NEW.proposal_key) THEN
RAISE EXCEPTION 'Alternative must match adopted cost option' USING ERRCODE='23514'; END IF;
IF NOT EXISTS(SELECT 1 FROM cehub_cost.cost_alternatives t
WHERE t.tenant_id=NEW.tenant_id AND t.project_id=NEW.project_id AND t.id=NEW.alternative_id
AND t.status='proposed' AND t.previous_id IS NULL AND t.revision_number=1
AND t.payload->'draft'=chosen->'draft'
AND t.snapshot->>'digest'=chosen->>'expected_digest'
AND t.created_by_user_id=a.created_by_user_id)
THEN RAISE EXCEPTION 'Cost proposal requires actual alternative with accepted content'
USING ERRCODE='23514'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER guard_cost_reduction_item BEFORE INSERT ON cehub_cost.cost_reduction_items
FOR EACH ROW EXECUTE FUNCTION cehub_cost.guard_cost_reduction_item();

CREATE FUNCTION cehub_ai.guard_cost_reduction_finding_apply() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE a cehub_cost.cost_reduction_applications%ROWTYPE;
DECLARE expected_count integer;
BEGIN
IF NEW.finding_type<>'cost_reduction' THEN RETURN NEW; END IF;
IF NEW.accepted_payload IS NOT NULL AND (
NEW.accepted_payload-'review'-'details_confirmed' IS DISTINCT FROM
NEW.proposed_payload-'review'-'details_confirmed'
OR NEW.accepted_payload->'details_confirmed' IS DISTINCT FROM 'true'::jsonb
OR jsonb_typeof(NEW.accepted_payload->'review') IS DISTINCT FROM 'object'
OR jsonb_typeof(NEW.accepted_payload->'review'->'choices') IS DISTINCT FROM 'array') THEN
RAISE EXCEPTION 'Cost reduction needs original proposal and explicit human review'
USING ERRCODE='23514'; END IF;
IF TG_OP='UPDATE' AND OLD.accepted_payload IS NOT NULL
AND NEW.accepted_payload IS NOT NULL
AND NEW.accepted_payload IS DISTINCT FROM OLD.accepted_payload THEN
RAISE EXCEPTION 'Accepted cost payload is immutable' USING ERRCODE='23514'; END IF;
IF NEW.status='applied' THEN
SELECT * INTO a FROM cehub_cost.cost_reduction_applications
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
AND finding_id=NEW.id AND id=NEW.applied_entity_id;
SELECT count(*) INTO expected_count FROM
jsonb_array_elements(NEW.accepted_payload->'review'->'choices') x
WHERE x->>'disposition'='adopt';
IF NEW.applied_entity_type IS DISTINCT FROM 'cost_reduction' OR a.id IS NULL
OR a.created_by_user_id<>NEW.applied_by_user_id OR a.created_at<>NEW.applied_at
OR a.review IS DISTINCT FROM NEW.accepted_payload->'review'
OR expected_count<1 OR expected_count<>(SELECT count(*) FROM
cehub_cost.cost_reduction_items WHERE application_id=a.id) THEN
RAISE EXCEPTION 'Cost reduction application must include every adopted actual alternative'
USING ERRCODE='23514'; END IF;
END IF;
RETURN NEW;
END $$;
CREATE TRIGGER guard_cost_reduction_finding_apply BEFORE INSERT OR UPDATE ON cehub_ai.findings
FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_cost_reduction_finding_apply();

CREATE FUNCTION cehub_cost.require_cost_reduction_receipt() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
IF NOT EXISTS(SELECT 1 FROM cehub_ai.findings WHERE id=NEW.finding_id
AND tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND status='applied'
AND applied_entity_type='cost_reduction' AND applied_entity_id=NEW.id) THEN
RAISE EXCEPTION 'Cost reduction application must commit with finding receipt'
USING ERRCODE='23514'; END IF;
RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER require_cost_reduction_receipt AFTER INSERT ON
cehub_cost.cost_reduction_applications DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION cehub_cost.require_cost_reduction_receipt();
REVOKE ALL ON FUNCTION cehub_cost.guard_cost_reduction_application() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_cost.guard_cost_reduction_item() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.guard_cost_reduction_finding_apply() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_cost.require_cost_reduction_receipt() FROM PUBLIC;


"""


def constraints(values: dict[str, str]) -> None:
    for key, expression in values.items():
        table, name = key.split("|")
        op.drop_constraint(op.f(name), table, schema="cehub_ai")
        op.create_check_constraint(op.f(name), table, expression, schema="cehub_ai")


def upgrade() -> None:
    constraints(NEW)
    op.execute(DDL)
    op.execute(ORIGIN)
    op.execute(GUARDS)
    for table in ("cost_reduction_applications", "cost_reduction_items"):
        op.execute(
            f"CREATE TRIGGER protect_{table} BEFORE UPDATE OR DELETE ON cehub_cost.{table} "
            "FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history()"
        )
        op.execute(f"REVOKE ALL ON cehub_cost.{table} FROM PUBLIC")


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN
IF EXISTS(SELECT 1 FROM cehub_cost.cost_reduction_applications) OR
EXISTS(SELECT 1 FROM cehub_ai.findings WHERE finding_type='cost_reduction') OR
EXISTS(SELECT 1 FROM cehub_ai.finding_quality_controls WHERE finding_type='cost_reduction')
THEN RAISE EXCEPTION 'Cost finding and adoption history requires retention'; END IF;
END $$;
DROP TRIGGER guard_cost_reduction_origin ON cehub_ai.findings;
DROP TRIGGER guard_cost_reduction_finding_apply ON cehub_ai.findings;
DROP FUNCTION cehub_ai.guard_cost_reduction_origin();
DROP FUNCTION cehub_ai.guard_cost_reduction_finding_apply();
DROP TABLE cehub_cost.cost_reduction_items;
DROP TABLE cehub_cost.cost_reduction_applications;
DROP FUNCTION cehub_cost.require_cost_reduction_receipt();
DROP FUNCTION cehub_cost.guard_cost_reduction_item();
DROP FUNCTION cehub_cost.guard_cost_reduction_application();
""")
    constraints(OLD)
