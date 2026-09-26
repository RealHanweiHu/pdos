"""Resource date selection into existing scenario approval, with immutable source binding."""

from alembic import op

revision = "0335_resource_preparations"
down_revision = "0334_resource_schedules"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE cehub_project.project_resource_schedule_preparations (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	schedule_id UUID NOT NULL, 
	scenario_id UUID NOT NULL, 
	title TEXT NOT NULL, 
	reason TEXT NOT NULL, 
	receipt JSONB NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_project_resource_schedule_preparations PRIMARY KEY (id), 
	CONSTRAINT uq_resource_preparation_id UNIQUE (tenant_id, id), 
	CONSTRAINT uq_resource_preparation_source UNIQUE (tenant_id, schedule_id), 
	CONSTRAINT uq_resource_preparation_scenario UNIQUE (tenant_id, scenario_id), 
	CONSTRAINT uq_resource_preparation_request UNIQUE (tenant_id, created_by_user_id, request_id), 
        CONSTRAINT fk_project_resource_schedule_preparations_tenant_id_pro_e206 FOREIGN 
KEY(tenant_id, project_id, schedule_id) REFERENCES cehub_project.project_resource_schedules 
(tenant_id, project_id, id) ON DELETE RESTRICT, 
        CONSTRAINT fk_project_resource_schedule_preparations_tenant_id_pro_e700 FOREIGN 
KEY(tenant_id, project_id, scenario_id) REFERENCES cehub_project.project_schedule_scenarios 
(tenant_id, project_id, id) ON DELETE RESTRICT, 
        CONSTRAINT fk_project_resource_schedule_preparations_tenant_id_users FOREIGN 
KEY(tenant_id, created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE 
RESTRICT, 
        CONSTRAINT ck_project_resource_schedule_preparations_shape CHECK 
(jsonb_typeof(receipt)='object' AND request_digest ~ '^[a-f0-9]{64}$')
);
"""
GUARDS = """
CREATE FUNCTION cehub_project.guard_resource_preparation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE saved cehub_project.project_resource_schedules%ROWTYPE;
 planned cehub_project.project_schedule_scenarios%ROWTYPE;
 original cehub_project.project_schedule_scenarios%ROWTYPE;
BEGIN
 SELECT * INTO saved FROM cehub_project.project_resource_schedules
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.schedule_id;
 SELECT * INTO planned FROM cehub_project.project_schedule_scenarios
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.scenario_id;
 SELECT * INTO original FROM cehub_project.project_schedule_scenarios
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=saved.scenario_id;
 IF saved.id IS NULL OR planned.id IS NULL OR original.id IS NULL
 OR saved.result->>'solution_status' IS DISTINCT FROM 'candidate_found'
 OR planned.basis_digest IS DISTINCT FROM saved.scenario_basis_digest
 OR planned.actor_user_id IS DISTINCT FROM NEW.created_by_user_id
 OR planned.title IS DISTINCT FROM NEW.title OR planned.reason IS DISTINCT FROM NEW.reason
 OR (planned.plan - 'id' - 'version') IS DISTINCT FROM (original.plan - 'id' - 'version')
 OR planned.inputs->'dependencies' IS DISTINCT FROM original.inputs->'dependencies'
 OR NEW.receipt->>'source_result_digest' IS DISTINCT FROM saved.result_digest
 OR NEW.receipt->>'source_digest' IS NULL
 OR saved.result->'resource_solver'->>'ledger_identity_digest' IS NULL
 OR NEW.receipt->>'reservations_changed' IS DISTINCT FROM 'false'
 OR NEW.receipt->>'baseline_changed' IS DISTINCT FROM 'false'
 OR NEW.receipt->>'requires_baseline_approval' IS DISTINCT FROM 'true'
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(saved.result->'nodes') n
 WHERE n->>'actual_finish' IS NULL AND (
 (planned.inputs->'remaining_estimates'->(n->>'node_id')->>'not_before')::timestamptz
 IS DISTINCT FROM (n->>'remaining_work_start')::timestamptz))
 THEN RAISE EXCEPTION 'fixed resource date preparation required'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_project.require_resource_preparation_capacity() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_project.project_scenario_capacity_checks c
 WHERE c.tenant_id=NEW.tenant_id AND c.project_id=NEW.project_id AND c.scenario_id=NEW.scenario_id
 AND c.result->'resource_date_origin'->>'preparation_id'=NEW.id::text
 AND c.result->'resource_date_origin'->>'schedule_id'=NEW.schedule_id::text)
 THEN RAISE EXCEPTION 'resource date preparation requires capacity receipt'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_resource_preparation BEFORE INSERT
ON cehub_project.project_resource_schedule_preparations
FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_resource_preparation();
CREATE CONSTRAINT TRIGGER require_resource_preparation_capacity AFTER INSERT
ON cehub_project.project_resource_schedule_preparations DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION cehub_project.require_resource_preparation_capacity();

"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)
    op.execute("REVOKE ALL ON cehub_project.project_resource_schedule_preparations FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER immutable_resource_preparations BEFORE UPDATE OR DELETE "
        "ON cehub_project.project_resource_schedule_preparations FOR EACH ROW "
        "EXECUTE FUNCTION cehub_ai.protect_checkpoint_history()"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_project.project_resource_schedule_preparations) "
        "THEN RAISE EXCEPTION 'resource preparation history cannot be discarded'; END IF; END $$"
    )
    op.execute("DROP TABLE cehub_project.project_resource_schedule_preparations")
    op.execute("DROP FUNCTION cehub_project.require_resource_preparation_capacity()")
    op.execute("DROP FUNCTION cehub_project.guard_resource_preparation()")
