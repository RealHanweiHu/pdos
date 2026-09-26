"""Immutable resource-constrained scenario dates and original input versions."""

from alembic import op

revision = "0334_resource_schedules"
down_revision = "0333_resource_priorities"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE cehub_project.project_resource_schedules (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	scenario_id UUID NOT NULL, 
	inputs JSONB NOT NULL, 
	result JSONB NOT NULL, 
	result_digest VARCHAR(64) NOT NULL, 
	scenario_basis_digest VARCHAR(64) NOT NULL, 
	source_digest VARCHAR(64) NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_project_resource_schedules PRIMARY KEY (id), 
	CONSTRAINT uq_project_resource_schedule_id UNIQUE (tenant_id, id), 
	CONSTRAINT uq_project_resource_schedule_scope UNIQUE (tenant_id, project_id, id), 
        CONSTRAINT uq_project_resource_schedule_request UNIQUE (tenant_id, created_by_user_id, 
request_id), 
        CONSTRAINT fk_project_resource_schedules_tenant_id_project_schedul_c567 FOREIGN 
KEY(tenant_id, project_id, scenario_id) REFERENCES cehub_project.project_schedule_scenarios 
(tenant_id, project_id, id) ON DELETE RESTRICT, 
        CONSTRAINT fk_project_resource_schedules_tenant_id_users FOREIGN KEY(tenant_id, 
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
        CONSTRAINT ck_project_resource_schedules_project_resource_schedule_values CHECK 
(jsonb_typeof(inputs)='object' AND jsonb_typeof(result)='object')
)
;
CREATE TABLE cehub_project.project_resource_schedule_versions (
	tenant_id UUID NOT NULL, 
	schedule_id UUID NOT NULL, 
	capacity_version_id UUID NOT NULL, 
	policy_id UUID, 
        CONSTRAINT pk_project_resource_schedule_versions PRIMARY KEY (tenant_id, schedule_id, 
capacity_version_id), 
        CONSTRAINT fk_project_resource_schedule_versions_tenant_id_resourc_fe47 FOREIGN 
KEY(tenant_id, policy_id) REFERENCES cehub_project.resource_priority_versions (tenant_id, id) ON
 DELETE RESTRICT, 
        CONSTRAINT fk_project_resource_schedule_versions_tenant_id_project_4236 FOREIGN 
KEY(tenant_id, schedule_id) REFERENCES cehub_project.project_resource_schedules (tenant_id, id) 
ON DELETE RESTRICT, 
        CONSTRAINT fk_project_resource_schedule_versions_tenant_id_resourc_fad6 FOREIGN 
KEY(tenant_id, capacity_version_id) REFERENCES cehub_project.resource_capacity_versions 
(tenant_id, id) ON DELETE RESTRICT
);
"""

GUARDS = """
CREATE FUNCTION cehub_project.guard_resource_schedule() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_project.project_schedule_scenarios s
 WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.scenario_id
 AND s.basis_digest=NEW.scenario_basis_digest)
 OR NEW.result->>'applied' IS DISTINCT FROM 'false'
 OR NEW.result->>'ready_for_application' IS DISTINCT FROM 'false'
 OR NEW.result->'resource_solver'->>'algorithm_version' IS DISTINCT FROM 
'resource.serial_generation.v1'
 OR NEW.result->'resource_solver'->>'reservations_changed' IS DISTINCT FROM 'false'
 OR NEW.result->'resource_solver'->>'baseline_changed' IS DISTINCT FROM 'false'
 OR NEW.result->>'solution_status' NOT IN ('candidate_found','unresolved')
 OR NEW.inputs->>'request_id' IS DISTINCT FROM NEW.request_id::text
 OR NEW.result_digest !~ '^[a-f0-9]{64}$' OR NEW.source_digest !~ '^[a-f0-9]{64}$'
 THEN RAISE EXCEPTION 'resource schedule fixed proposal contract required'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_project.guard_resource_schedule_versions() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE saved jsonb; capacity cehub_project.resource_capacity_versions%ROWTYPE;
BEGIN
 SELECT result INTO saved FROM cehub_project.project_resource_schedules
 WHERE tenant_id=NEW.tenant_id AND id=NEW.schedule_id;
 SELECT * INTO capacity FROM cehub_project.resource_capacity_versions
 WHERE tenant_id=NEW.tenant_id AND id=NEW.capacity_version_id;
 IF capacity.id IS NULL OR NOT EXISTS(SELECT 1 FROM 
jsonb_array_elements(saved->'resource_solver'->'profiles') p
 WHERE p->>'id'=NEW.capacity_version_id::text AND p->>'resource_id'=capacity.resource_id::text)
 OR (NEW.policy_id IS NOT NULL AND NOT EXISTS(
 SELECT 1 FROM cehub_project.resource_priority_versions v
 WHERE v.tenant_id=NEW.tenant_id AND v.id=NEW.policy_id AND v.resource_id=capacity.resource_id
 AND EXISTS(SELECT 1 FROM jsonb_array_elements(saved->'resource_solver'->'policies') p
 WHERE p->>'policy_id'=v.id::text AND p->>'resource_id'=v.resource_id::text)))
 THEN RAISE EXCEPTION 'resource schedule source version mismatch'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_project.require_resource_schedule_versions() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.result->'resource_solver'->'profiles') p
 WHERE NOT EXISTS(SELECT 1 FROM cehub_project.project_resource_schedule_versions v
 WHERE v.tenant_id=NEW.tenant_id AND v.schedule_id=NEW.id AND 
v.capacity_version_id::text=p->>'id'))
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.result->'resource_solver'->'policies') p
 WHERE NOT EXISTS(SELECT 1 FROM cehub_project.project_resource_schedule_versions v
 WHERE v.tenant_id=NEW.tenant_id AND v.schedule_id=NEW.id AND v.policy_id::text=p->>'policy_id'))
 THEN RAISE EXCEPTION 'resource schedule requires original version bindings'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_resource_schedule BEFORE INSERT ON cehub_project.project_resource_schedules
FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_resource_schedule();
CREATE TRIGGER guard_resource_schedule_versions BEFORE INSERT ON 
cehub_project.project_resource_schedule_versions
FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_resource_schedule_versions();
CREATE CONSTRAINT TRIGGER require_resource_schedule_versions AFTER INSERT ON 
cehub_project.project_resource_schedules
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION 
cehub_project.require_resource_schedule_versions();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)
    for table in ("project_resource_schedules", "project_resource_schedule_versions"):
        op.execute(f"REVOKE ALL ON cehub_project.{table} FROM PUBLIC")
        op.execute(
            f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON cehub_project.{table} "
            "FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history()"
        )
    op.execute(
        "CREATE INDEX ix_resource_schedule_history ON cehub_project.project_resource_schedules"
        "(tenant_id,project_id,scenario_id,created_at DESC,id DESC)"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_project.project_resource_schedules) "
        "THEN RAISE EXCEPTION 'resource schedule history cannot be discarded'; END IF; END $$"
    )
    op.execute("DROP TABLE cehub_project.project_resource_schedule_versions")
    op.execute("DROP TABLE cehub_project.project_resource_schedules")
    for name in (
        "require_resource_schedule_versions",
        "guard_resource_schedule_versions",
        "guard_resource_schedule",
    ):
        op.execute(f"DROP FUNCTION cehub_project.{name}()")
