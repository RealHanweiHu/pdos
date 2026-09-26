"""Human-reviewed supply recovery applications and actual task receipts."""

from alembic import op

revision = "0311_supplier_recovery_application"
down_revision = "0310_supplier_recovery_runs"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_supplier.supplier_recovery_applications (
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
CONSTRAINT pk_supplier_recovery_applications PRIMARY KEY (id),
CONSTRAINT uq_supplier_recovery_scope UNIQUE (tenant_id, project_id, id),
CONSTRAINT uq_supplier_recovery_finding UNIQUE (finding_id),
CONSTRAINT uq_supplier_recovery_input UNIQUE (tenant_id, project_id, source_digest),
CONSTRAINT fk_supplier_recovery_applications_tenant_id_findings FOREIGN KEY(tenant_id,
project_id, finding_id) REFERENCES cehub_ai.findings (tenant_id, project_id, id) ON DELETE
RESTRICT,
CONSTRAINT fk_supplier_recovery_applications_tenant_id_agent_runs FOREIGN KEY(tenant_id, run_id)
REFERENCES cehub_ai.agent_runs (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_supplier_recovery_applications_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_supplier_recovery_applications_shape CHECK (source_digest ~ '^[a-f0-9]{64}$' AND
jsonb_typeof(review)='object' AND jsonb_typeof(source_snapshot)='object')
)

;

CREATE TABLE cehub_supplier.supplier_recovery_items (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
application_id UUID NOT NULL,
proposal_key VARCHAR(80) NOT NULL,
task_id UUID NOT NULL,
CONSTRAINT pk_supplier_recovery_items PRIMARY KEY (id),
CONSTRAINT uq_supplier_recovery_item_key UNIQUE (application_id, proposal_key),
CONSTRAINT uq_supplier_recovery_task UNIQUE (task_id),
CONSTRAINT fk_supplier_recovery_items_tenant_id_supplier_recovery__1d0f FOREIGN KEY(tenant_id,
project_id, application_id) REFERENCES cehub_supplier.supplier_recovery_applications (tenant_id,
project_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_supplier_recovery_items_tenant_id_tasks FOREIGN KEY(tenant_id, project_id,
task_id) REFERENCES cehub_project.tasks (tenant_id, project_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_supplier_recovery_items_shape CHECK (btrim(proposal_key)<>'')
)

;
"""
GUARDS = """
CREATE FUNCTION cehub_supplier.guard_recovery_application() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE f cehub_ai.findings%ROWTYPE;
DECLARE original jsonb;
BEGIN
SELECT * INTO f FROM cehub_ai.findings WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=NEW.finding_id;
SELECT run_context->'supply_source' INTO original FROM cehub_ai.agent_runs
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.run_id;
IF f.id IS NULL OR f.finding_type<>'supplier_recovery' OR f.status<>'accepted'
OR f.run_id<>NEW.run_id
OR f.accepted_payload->>'source_digest' IS DISTINCT FROM NEW.source_digest
OR f.accepted_payload->'review' IS DISTINCT FROM NEW.review
OR NEW.source_snapshot IS DISTINCT FROM original
OR NEW.source_snapshot->>'digest' IS DISTINCT FROM NEW.source_digest
THEN RAISE EXCEPTION 'Supply recovery requires exact accepted finding and fixed source'
USING ERRCODE='23514'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER guard_recovery_application BEFORE INSERT ON
cehub_supplier.supplier_recovery_applications FOR EACH ROW
EXECUTE FUNCTION cehub_supplier.guard_recovery_application();

CREATE FUNCTION cehub_supplier.guard_recovery_item() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE a cehub_supplier.supplier_recovery_applications%ROWTYPE;
DECLARE chosen jsonb;
BEGIN
SELECT * INTO a FROM cehub_supplier.supplier_recovery_applications
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.application_id;
SELECT x INTO chosen FROM jsonb_array_elements(a.review->'choices') x
WHERE x->>'key'=NEW.proposal_key AND x->>'disposition'='adopt';
IF chosen IS NULL OR NOT EXISTS(SELECT 1 FROM cehub_ai.findings f,
jsonb_array_elements(f.accepted_payload->'assessment'->'options') o
WHERE f.id=a.finding_id AND f.tenant_id=NEW.tenant_id AND f.project_id=NEW.project_id
AND f.status='accepted' AND o->>'key'=NEW.proposal_key) THEN
RAISE EXCEPTION 'Task must match adopted recovery option' USING ERRCODE='23514'; END IF;
IF NOT EXISTS(SELECT 1 FROM cehub_project.tasks t
WHERE t.tenant_id=NEW.tenant_id AND t.project_id=NEW.project_id AND t.id=NEW.task_id
AND t.status='todo' AND t.assignee_user_id::text=chosen->>'owner_user_id'
AND t.due_date::text=chosen->>'due_date'
AND t.stage_id::text IS NOT DISTINCT FROM chosen->>'stage_id'
AND t.title=left('供应恢复：'||(chosen->>'description'),512)
AND t.expected_output='验证要求：'||(chosen->>'verification')||chr(10)||
'完成判据：'||(chosen->>'completion_criteria')||chr(10)||'缺项处理：'||(chosen->>'missing_resolution'))
THEN RAISE EXCEPTION 'Recovery requires actual assigned task with accepted criteria'
USING ERRCODE='23514'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER guard_recovery_item BEFORE INSERT ON cehub_supplier.supplier_recovery_items
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.guard_recovery_item();

CREATE FUNCTION cehub_ai.guard_recovery_finding_apply() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE a cehub_supplier.supplier_recovery_applications%ROWTYPE;
DECLARE expected_count integer;
BEGIN
IF NEW.finding_type<>'supplier_recovery' THEN RETURN NEW; END IF;
IF NEW.accepted_payload IS NOT NULL AND (
NEW.accepted_payload-'review'-'details_confirmed' IS DISTINCT FROM
NEW.proposed_payload-'review'-'details_confirmed'
OR NEW.accepted_payload->'details_confirmed' IS DISTINCT FROM 'true'::jsonb
OR jsonb_typeof(NEW.accepted_payload->'review') IS DISTINCT FROM 'object'
OR jsonb_typeof(NEW.accepted_payload->'review'->'choices') IS DISTINCT FROM 'array') THEN
RAISE EXCEPTION 'Recovery needs original proposal and explicit human review'
USING ERRCODE='23514'; END IF;
IF TG_OP='UPDATE' AND OLD.accepted_payload IS NOT NULL
AND NEW.accepted_payload IS NOT NULL
AND NEW.accepted_payload IS DISTINCT FROM OLD.accepted_payload THEN
RAISE EXCEPTION 'Accepted recovery payload is immutable' USING ERRCODE='23514'; END IF;
IF NEW.status='applied' THEN
SELECT * INTO a FROM cehub_supplier.supplier_recovery_applications
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
AND finding_id=NEW.id AND id=NEW.applied_entity_id;
SELECT count(*) INTO expected_count FROM
jsonb_array_elements(NEW.accepted_payload->'review'->'choices') x
WHERE x->>'disposition'='adopt';
IF NEW.applied_entity_type IS DISTINCT FROM 'supplier_recovery' OR a.id IS NULL
OR a.created_by_user_id<>NEW.applied_by_user_id OR a.created_at<>NEW.applied_at
OR a.review IS DISTINCT FROM NEW.accepted_payload->'review'
OR expected_count<1 OR expected_count<>(SELECT count(*) FROM
cehub_supplier.supplier_recovery_items WHERE application_id=a.id) THEN
RAISE EXCEPTION 'Recovery application must include every adopted actual task'
USING ERRCODE='23514'; END IF;
END IF;
RETURN NEW;
END $$;
CREATE TRIGGER guard_recovery_finding_apply BEFORE INSERT OR UPDATE ON cehub_ai.findings
FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_recovery_finding_apply();

CREATE FUNCTION cehub_supplier.require_recovery_receipt() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
IF NOT EXISTS(SELECT 1 FROM cehub_ai.findings WHERE id=NEW.finding_id
AND tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND status='applied'
AND applied_entity_type='supplier_recovery' AND applied_entity_id=NEW.id) THEN
RAISE EXCEPTION 'Recovery application must commit with finding receipt'
USING ERRCODE='23514'; END IF;
RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER require_recovery_receipt AFTER INSERT ON
cehub_supplier.supplier_recovery_applications DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.require_recovery_receipt();
REVOKE ALL ON FUNCTION cehub_supplier.guard_recovery_application() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_supplier.guard_recovery_item() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.guard_recovery_finding_apply() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_supplier.require_recovery_receipt() FROM PUBLIC;

"""
OLD = """
(status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL AND
applied_entity_type IS NULL AND applied_entity_id IS NULL) OR (status = 'applied' AND
applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL AND applied_entity_type IN ('risk',
'memory', 'issue', 'task', 'test_run', 'sample_build_configuration', 'knowledge_candidate',
'schedule_change_proposal', 'material_exception', 'test_plan', 'meeting_minutes', 'decision',
'ecr', 'change_impact_scope', 'quality_work_package', 'process_template_revision',
'project_intake_proposal', 'meeting') AND applied_entity_id IS NOT NULL AND reviewed_at <
applied_at)
"""
NEW = """
(status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL AND
applied_entity_type IS NULL AND applied_entity_id IS NULL) OR (status = 'applied' AND
applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL AND applied_entity_type IN ('risk',
'memory', 'issue', 'task', 'test_run', 'sample_build_configuration', 'knowledge_candidate',
'schedule_change_proposal', 'material_exception', 'test_plan', 'meeting_minutes', 'decision',
'ecr', 'change_impact_scope', 'quality_work_package', 'supplier_recovery',
'process_template_revision', 'project_intake_proposal', 'meeting') AND applied_entity_id IS NOT
NULL AND reviewed_at < applied_at)
"""


def upgrade() -> None:
    op.execute(DDL)
    op.drop_constraint(
        op.f("ck_findings_apply_lifecycle_consistent"), "findings", schema="cehub_ai"
    )
    op.create_check_constraint(
        op.f("ck_findings_apply_lifecycle_consistent"), "findings", NEW, schema="cehub_ai"
    )
    op.execute(GUARDS)
    for table in ("supplier_recovery_applications", "supplier_recovery_items"):
        op.execute(
            f"CREATE TRIGGER protect_{table} BEFORE UPDATE OR DELETE ON cehub_supplier.{table} "
            "FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history()"
        )
        op.execute(f"REVOKE ALL ON cehub_supplier.{table} FROM PUBLIC")


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN
IF EXISTS(SELECT 1 FROM cehub_supplier.supplier_recovery_applications) OR
EXISTS(SELECT 1 FROM cehub_ai.findings WHERE applied_entity_type='supplier_recovery'
OR (finding_type='supplier_recovery' AND accepted_payload IS NOT NULL)) THEN
RAISE EXCEPTION 'Supplier recovery review and task history requires retention'; END IF;
END $$;
DROP TRIGGER guard_recovery_finding_apply ON cehub_ai.findings;
DROP FUNCTION cehub_ai.guard_recovery_finding_apply();
DROP TABLE cehub_supplier.supplier_recovery_items;
DROP TABLE cehub_supplier.supplier_recovery_applications;
DROP FUNCTION cehub_supplier.require_recovery_receipt();
DROP FUNCTION cehub_supplier.guard_recovery_item();
DROP FUNCTION cehub_supplier.guard_recovery_application();
""")
    op.drop_constraint(
        op.f("ck_findings_apply_lifecycle_consistent"), "findings", schema="cehub_ai"
    )
    op.create_check_constraint(
        op.f("ck_findings_apply_lifecycle_consistent"), "findings", OLD, schema="cehub_ai"
    )
