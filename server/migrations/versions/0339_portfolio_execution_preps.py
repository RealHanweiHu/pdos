"""Atomic portfolio execution preparation and binding to real baseline requests."""

from alembic import op

revision = "0339_portfolio_execution_preps"
down_revision = "0338_portfolio_selections"
branch_labels = None
depends_on = None

TABLES = ("portfolio_execution_preparations", "portfolio_execution_projects")

DDL = """
CREATE TABLE cehub_project.portfolio_execution_preparations (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	selection_id UUID NOT NULL, 
	selection_digest VARCHAR(64) NOT NULL, 
	reason TEXT NOT NULL, 
	receipt JSONB NOT NULL, 
	actor_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_portfolio_execution_preparations PRIMARY KEY (id), 
	CONSTRAINT uq_portfolio_execution_preparation_id UNIQUE (tenant_id, id), 
	CONSTRAINT uq_portfolio_execution_selection UNIQUE (tenant_id, selection_id), 
	CONSTRAINT uq_portfolio_execution_request UNIQUE (tenant_id, actor_user_id, request_id), 
    CONSTRAINT fk_portfolio_execution_preparations_tenant_id_portfolio_1789 FOREIGN
KEY(tenant_id, selection_id) REFERENCES cehub_project.portfolio_selections (tenant_id, id) ON
DELETE RESTRICT,
    CONSTRAINT fk_portfolio_execution_preparations_tenant_id_users FOREIGN KEY(tenant_id,
actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_portfolio_execution_preparations_shape CHECK (jsonb_typeof(receipt)='object'
AND selection_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$')
);

CREATE TABLE cehub_project.portfolio_execution_projects (
	tenant_id UUID NOT NULL, 
	preparation_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	selection_id UUID NOT NULL, 
	schedule_id UUID NOT NULL, 
	resource_preparation_id UUID NOT NULL, 
	scenario_id UUID NOT NULL, 
	capacity_check_id UUID NOT NULL, 
	change_id UUID NOT NULL, 
	change_digest VARCHAR(64) NOT NULL, 
	receipt JSONB NOT NULL, 
	CONSTRAINT pk_portfolio_execution_projects PRIMARY KEY (tenant_id, preparation_id, project_id), 
	CONSTRAINT uq_portfolio_execution_scenario UNIQUE (tenant_id, scenario_id), 
	CONSTRAINT uq_portfolio_execution_change UNIQUE (tenant_id, change_id), 
    CONSTRAINT fk_portfolio_execution_projects_tenant_id_portfolio_exe_33e9 FOREIGN
KEY(tenant_id, preparation_id) REFERENCES cehub_project.portfolio_execution_preparations
(tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_portfolio_execution_projects_tenant_id_portfolio_sel_dd73 FOREIGN
KEY(tenant_id, selection_id, project_id) REFERENCES cehub_project.portfolio_selection_projects
(tenant_id, selection_id, project_id) ON DELETE RESTRICT,
    CONSTRAINT fk_portfolio_execution_projects_tenant_id_project_resou_d8c0 FOREIGN
KEY(tenant_id, project_id, schedule_id) REFERENCES cehub_project.project_resource_schedules
(tenant_id, project_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_portfolio_execution_projects_tenant_id_project_resou_0c84 FOREIGN
KEY(tenant_id, resource_preparation_id) REFERENCES
cehub_project.project_resource_schedule_preparations (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_portfolio_execution_projects_tenant_id_project_sched_0d2b FOREIGN
KEY(tenant_id, project_id, scenario_id) REFERENCES cehub_project.project_schedule_scenarios
(tenant_id, project_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_portfolio_execution_projects_tenant_id_project_scena_38e5 FOREIGN
KEY(tenant_id, project_id, capacity_check_id) REFERENCES
cehub_project.project_scenario_capacity_checks (tenant_id, project_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_portfolio_execution_projects_tenant_id_baseline_chan_d7a2 FOREIGN
KEY(tenant_id, project_id, change_id) REFERENCES cehub_project.baseline_change_requests
(tenant_id, project_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_portfolio_execution_projects_shape CHECK (jsonb_typeof(receipt)='object' AND
change_digest ~ '^[a-f0-9]{64}$')
);
"""

GUARDS = """
CREATE FUNCTION cehub_project.guard_portfolio_execution_preparation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE saved cehub_project.portfolio_selections%ROWTYPE;
BEGIN
 SELECT * INTO saved FROM cehub_project.portfolio_selections
 WHERE tenant_id=NEW.tenant_id AND id=NEW.selection_id FOR UPDATE;
 IF saved.id IS NULL OR NEW.selection_digest IS DISTINCT FROM saved.payload_digest
 OR NEW.receipt->>'selection_id' IS DISTINCT FROM NEW.selection_id::text
 OR NEW.receipt->>'selection_digest' IS DISTINCT FROM saved.payload_digest
 OR NEW.receipt->>'baseline_changed' IS DISTINCT FROM 'false'
 OR NEW.receipt->>'reservations_changed' IS DISTINCT FROM 'false'
 OR NEW.receipt->>'commitments_changed' IS DISTINCT FROM 'false'
 OR NEW.receipt->>'requires_baseline_approval' IS DISTINCT FROM 'true'
 OR NEW.receipt->>'requires_independent_application' IS DISTINCT FROM 'true'
 OR EXISTS(SELECT 1 FROM cehub_project.portfolio_selection_decisions
 WHERE tenant_id=NEW.tenant_id AND selection_id=NEW.selection_id AND action<>'approve')
 OR EXISTS(SELECT 1 FROM cehub_project.portfolio_selection_projects p
 WHERE p.tenant_id=NEW.tenant_id AND p.selection_id=NEW.selection_id AND NOT EXISTS(
 SELECT 1 FROM cehub_project.portfolio_selection_decisions d
 WHERE d.tenant_id=p.tenant_id AND d.selection_id=p.selection_id AND d.project_id=p.project_id
 AND d.action='approve' AND d.payload_digest=saved.payload_digest))
 THEN RAISE EXCEPTION 'all fixed portfolio project approvals required'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cehub_project.guard_portfolio_execution_project() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE package cehub_project.portfolio_execution_preparations%ROWTYPE;
 part cehub_project.portfolio_selection_projects%ROWTYPE;
 source cehub_project.project_resource_schedules%ROWTYPE;
 resource cehub_project.project_resource_schedule_preparations%ROWTYPE;
 request cehub_project.baseline_change_requests%ROWTYPE;
 receipt jsonb;
BEGIN
 SELECT * INTO package FROM cehub_project.portfolio_execution_preparations
 WHERE tenant_id=NEW.tenant_id AND id=NEW.preparation_id;
 SELECT * INTO part FROM cehub_project.portfolio_selection_projects
 WHERE tenant_id=NEW.tenant_id AND selection_id=NEW.selection_id AND project_id=NEW.project_id;
 SELECT * INTO source FROM cehub_project.project_resource_schedules
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.schedule_id;
 SELECT * INTO resource FROM cehub_project.project_resource_schedule_preparations
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.resource_preparation_id;
 SELECT * INTO request FROM cehub_project.baseline_change_requests
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.change_id;
 SELECT p INTO receipt FROM jsonb_array_elements(package.receipt->'items') p
 WHERE p->>'project_id'=NEW.project_id::text;
 IF package.id IS NULL OR part.project_id IS NULL OR source.id IS NULL
 OR resource.id IS NULL OR request.id IS NULL OR receipt IS NULL
 OR package.selection_id IS DISTINCT FROM NEW.selection_id
 OR receipt IS DISTINCT FROM NEW.receipt
 OR part.snapshot->'selected'->>'schedule_id' IS DISTINCT FROM NEW.schedule_id::text
 OR resource.schedule_id IS DISTINCT FROM source.id
 OR resource.scenario_id IS DISTINCT FROM NEW.scenario_id
 OR request.scenario_id IS DISTINCT FROM NEW.scenario_id
 OR request.capacity_check_id IS DISTINCT FROM NEW.capacity_check_id
 OR request.policy_id IS DISTINCT FROM part.policy_id
 OR request.base_baseline_id IS DISTINCT FROM part.baseline_id
 OR request.payload_digest IS DISTINCT FROM NEW.change_digest
 OR request.created_by_user_id IS DISTINCT FROM package.actor_user_id
 OR jsonb_array_length(request.snapshot->'blockers') IS DISTINCT FROM 0
 OR NEW.receipt->>'dates_changed' IS DISTINCT FROM 'false'
 OR jsonb_array_length(request.snapshot->'result'->'nodes')
 IS DISTINCT FROM jsonb_array_length(source.result->'nodes')
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(source.result->'nodes') n
 WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements(request.snapshot->'result'->'nodes') p
 WHERE p->>'node_id'=n->>'node_id'
 AND (p->>'start')::timestamptz IS NOT DISTINCT FROM (n->>'start')::timestamptz
 AND (p->>'finish')::timestamptz IS NOT DISTINCT FROM (n->>'finish')::timestamptz
 AND (p->>'remaining_work_start')::timestamptz
 IS NOT DISTINCT FROM (n->>'remaining_work_start')::timestamptz))
 THEN RAISE EXCEPTION 'real project execution must preserve selected dates and policy'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cehub_project.require_portfolio_execution_projects() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF (SELECT count(*) FROM cehub_project.portfolio_execution_projects
 WHERE tenant_id=NEW.tenant_id AND preparation_id=NEW.id)
 IS DISTINCT FROM (SELECT count(*) FROM cehub_project.portfolio_selection_projects
 WHERE tenant_id=NEW.tenant_id AND selection_id=NEW.selection_id)
 OR jsonb_array_length(NEW.receipt->'items') IS DISTINCT FROM
 (SELECT count(*)::integer FROM cehub_project.portfolio_selection_projects
 WHERE tenant_id=NEW.tenant_id AND selection_id=NEW.selection_id)
 THEN RAISE EXCEPTION 'complete portfolio execution preparation required'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cehub_project.guard_portfolio_baseline_path() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE bound cehub_project.portfolio_execution_projects%ROWTYPE; actual_scenario uuid;
BEGIN
 IF TG_TABLE_NAME='baseline_change_decisions' THEN
   SELECT scenario_id INTO actual_scenario FROM cehub_project.baseline_change_requests
   WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.change_id;
 ELSE actual_scenario:=NEW.scenario_id;
 END IF;
 SELECT * INTO bound FROM cehub_project.portfolio_execution_projects
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND scenario_id=actual_scenario;
 IF bound.project_id IS NULL THEN RETURN NEW; END IF;
 IF TG_TABLE_NAME='baseline_change_applications' THEN
   RAISE EXCEPTION 'portfolio baseline requires independent batch application';
 ELSIF TG_TABLE_NAME='baseline_change_requests' THEN
   RAISE EXCEPTION 'portfolio execution scenario already has its fixed request';
 ELSIF NEW.action='approve' THEN
   PERFORM 1 FROM cehub_project.portfolio_selections
   WHERE tenant_id=NEW.tenant_id AND id=bound.selection_id FOR UPDATE;
   IF NEW.change_id IS DISTINCT FROM bound.change_id
   OR NEW.approved_payload_digest IS DISTINCT FROM bound.change_digest
   OR EXISTS(SELECT 1 FROM cehub_project.portfolio_selection_decisions
   WHERE tenant_id=NEW.tenant_id AND selection_id=bound.selection_id AND action<>'approve')
   THEN RAISE EXCEPTION 'portfolio selection no longer supports baseline approval'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_portfolio_execution_preparation BEFORE INSERT
ON cehub_project.portfolio_execution_preparations FOR EACH ROW
EXECUTE FUNCTION cehub_project.guard_portfolio_execution_preparation();
CREATE TRIGGER guard_portfolio_execution_project BEFORE INSERT
ON cehub_project.portfolio_execution_projects FOR EACH ROW
EXECUTE FUNCTION cehub_project.guard_portfolio_execution_project();
CREATE CONSTRAINT TRIGGER require_portfolio_execution_projects AFTER INSERT
ON cehub_project.portfolio_execution_preparations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION cehub_project.require_portfolio_execution_projects();
CREATE TRIGGER guard_portfolio_baseline_path BEFORE INSERT
ON cehub_project.baseline_change_requests FOR EACH ROW
EXECUTE FUNCTION cehub_project.guard_portfolio_baseline_path();
CREATE TRIGGER guard_portfolio_baseline_path BEFORE INSERT
ON cehub_project.baseline_change_decisions FOR EACH ROW
EXECUTE FUNCTION cehub_project.guard_portfolio_baseline_path();
CREATE TRIGGER guard_portfolio_baseline_path BEFORE INSERT
ON cehub_project.baseline_change_applications FOR EACH ROW
EXECUTE FUNCTION cehub_project.guard_portfolio_baseline_path();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)
    for name in TABLES:
        op.execute(f"REVOKE ALL ON cehub_project.{name} FROM PUBLIC")
        op.execute(
            f"CREATE TRIGGER immutable_{name} BEFORE UPDATE OR DELETE "
            f"ON cehub_project.{name} FOR EACH ROW "
            "EXECUTE FUNCTION cehub_ai.protect_checkpoint_history()"
        )


def downgrade() -> None:
    for name in TABLES:
        op.execute(
            f"DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_project.{name}) "
            "THEN RAISE EXCEPTION 'portfolio execution history cannot be discarded'; END IF; END $$"
        )
    for name in (
        "baseline_change_requests",
        "baseline_change_decisions",
        "baseline_change_applications",
    ):
        op.execute(f"DROP TRIGGER guard_portfolio_baseline_path ON cehub_project.{name}")
    for name in reversed(TABLES):
        op.execute(f"DROP TABLE cehub_project.{name}")
    for name in (
        "guard_portfolio_baseline_path",
        "require_portfolio_execution_projects",
        "guard_portfolio_execution_project",
        "guard_portfolio_execution_preparation",
    ):
        op.execute(f"DROP FUNCTION cehub_project.{name}()")
