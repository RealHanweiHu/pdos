"""Cross-project resource reallocation consent and atomic reservation receipts."""

from alembic import op

revision = "0336_resource_reallocations"
down_revision = "0335_resource_preparations"
branch_labels = None
depends_on = None

TABLES = (
    "resource_reallocations",
    "resource_reallocation_projects",
    "resource_reallocation_items",
    "resource_reallocation_decisions",
    "resource_reallocation_applications",
)
DDL = """
CREATE TABLE cehub_project.resource_reallocations (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	title TEXT NOT NULL, 
	inputs JSONB NOT NULL, 
	snapshot JSONB NOT NULL, 
	payload_digest VARCHAR(64) NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_resource_reallocations PRIMARY KEY (id), 
	CONSTRAINT uq_resource_reallocation_id UNIQUE (tenant_id, id), 
	CONSTRAINT uq_resource_reallocation_request UNIQUE (tenant_id, created_by_user_id, request_id), 
        CONSTRAINT fk_resource_reallocations_tenant_id_users FOREIGN KEY(tenant_id, 
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
        CONSTRAINT ck_resource_reallocations_shape CHECK (jsonb_typeof(inputs)='object' AND 
jsonb_typeof(snapshot)='object' AND payload_digest ~ '^[a-f0-9]{64}$')
)
;
CREATE TABLE cehub_project.resource_reallocation_projects (
	tenant_id UUID NOT NULL, 
	allocation_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	owner_user_id UUID NOT NULL, 
	body JSONB NOT NULL, 
	CONSTRAINT pk_resource_reallocation_projects PRIMARY KEY
(tenant_id, allocation_id, project_id), 
        CONSTRAINT fk_resource_reallocation_projects_tenant_id_resource_re_f18a FOREIGN 
KEY(tenant_id, allocation_id) REFERENCES cehub_project.resource_reallocations (tenant_id, id) ON
 DELETE RESTRICT, 
        CONSTRAINT fk_resource_reallocation_projects_tenant_id_projects FOREIGN KEY(tenant_id, 
project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT, 
        CONSTRAINT fk_resource_reallocation_projects_tenant_id_users FOREIGN KEY(tenant_id, 
owner_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_resource_reallocation_projects_shape CHECK (jsonb_typeof(body)='object')
)
;
CREATE TABLE cehub_project.resource_reallocation_items (
	tenant_id UUID NOT NULL, 
	allocation_id UUID NOT NULL, 
	reservation_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	capacity_version_id UUID NOT NULL, 
	policy_id UUID NOT NULL, 
        CONSTRAINT pk_resource_reallocation_items PRIMARY KEY (tenant_id, allocation_id, 
reservation_id), 
        CONSTRAINT fk_resource_reallocation_items_tenant_id_resource_reall_562e FOREIGN 
KEY(tenant_id, allocation_id, project_id) REFERENCES 
cehub_project.resource_reallocation_projects (tenant_id, allocation_id, project_id) ON DELETE 
RESTRICT, 
        CONSTRAINT fk_resource_reallocation_items_tenant_id_resource_reservations FOREIGN 
KEY(tenant_id, reservation_id) REFERENCES cehub_project.resource_reservations (tenant_id, id) ON
 DELETE RESTRICT, 
        CONSTRAINT fk_resource_reallocation_items_tenant_id_resource_capac_08f0 FOREIGN 
KEY(tenant_id, capacity_version_id) REFERENCES cehub_project.resource_capacity_versions 
(tenant_id, id) ON DELETE RESTRICT, 
        CONSTRAINT fk_resource_reallocation_items_tenant_id_resource_prior_dbda FOREIGN 
KEY(tenant_id, policy_id) REFERENCES cehub_project.resource_priority_versions (tenant_id, id) ON
 DELETE RESTRICT
)
;
CREATE TABLE cehub_project.resource_reallocation_decisions (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	allocation_id UUID NOT NULL, 
	project_id UUID, 
	action VARCHAR(16) NOT NULL, 
	reason TEXT NOT NULL, 
	payload_digest VARCHAR(64) NOT NULL, 
	actor_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_resource_reallocation_decisions PRIMARY KEY (id), 
        CONSTRAINT fk_resource_reallocation_decisions_tenant_id_resource_r_019f FOREIGN 
KEY(tenant_id, allocation_id) REFERENCES cehub_project.resource_reallocations (tenant_id, id) ON
 DELETE RESTRICT, 
        CONSTRAINT fk_resource_reallocation_decisions_tenant_id_resource_r_c2ce FOREIGN 
KEY(tenant_id, allocation_id, project_id) REFERENCES 
cehub_project.resource_reallocation_projects (tenant_id, allocation_id, project_id) ON DELETE 
RESTRICT, 
        CONSTRAINT fk_resource_reallocation_decisions_tenant_id_users FOREIGN KEY(tenant_id, 
actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT uq_reallocation_decision_request UNIQUE (tenant_id, actor_user_id, request_id), 
        CONSTRAINT ck_resource_reallocation_decisions_shape CHECK ((action='withdraw' AND 
project_id IS NULL) OR (action IN ('approve','reject') AND project_id IS NOT NULL))
)
;
CREATE TABLE cehub_project.resource_reallocation_applications (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	allocation_id UUID NOT NULL, 
	payload_digest VARCHAR(64) NOT NULL, 
	receipt JSONB NOT NULL, 
	actor_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_resource_reallocation_applications PRIMARY KEY (id), 
        CONSTRAINT fk_resource_reallocation_applications_tenant_id_resourc_e70e FOREIGN 
KEY(tenant_id, allocation_id) REFERENCES cehub_project.resource_reallocations (tenant_id, id) ON
 DELETE RESTRICT, 
        CONSTRAINT fk_resource_reallocation_applications_tenant_id_users FOREIGN KEY(tenant_id, 
actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT uq_reallocation_application UNIQUE (tenant_id, allocation_id), 
	CONSTRAINT uq_reallocation_application_request UNIQUE (tenant_id, actor_user_id, request_id), 
	CONSTRAINT ck_resource_reallocation_applications_shape CHECK (jsonb_typeof(receipt)='object')
);
CREATE UNIQUE INDEX uq_reallocation_project_decision ON 
cehub_project.resource_reallocation_decisions (tenant_id, allocation_id, project_id) WHERE 
project_id IS NOT NULL;
CREATE UNIQUE INDEX uq_reallocation_withdrawal ON cehub_project.resource_reallocation_decisions 
(tenant_id, allocation_id) WHERE action='withdraw';

"""
GUARDS = """
CREATE FUNCTION cehub_project.guard_reallocation_project() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_project.projects p JOIN cehub_core.users u
 ON u.tenant_id=p.tenant_id AND u.id=p.owner_user_id
 WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.project_id AND p.owner_user_id=NEW.owner_user_id
 AND p.status IN ('approved','active') AND u.is_active
 AND u.role IN ('owner','admin','project_manager'))
 OR NEW.body->'project'->>'id' IS DISTINCT FROM NEW.project_id::text
 OR NEW.body->'project'->>'owner_user_id' IS DISTINCT FROM NEW.owner_user_id::text
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.body->'items') i
 WHERE i->>'project_id' IS DISTINCT FROM NEW.project_id::text)
 THEN RAISE EXCEPTION 'reallocation project and named owner required'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_project.guard_reallocation_item() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_project.resource_reservations r
 WHERE r.tenant_id=NEW.tenant_id AND r.project_id=NEW.project_id AND r.id=NEW.reservation_id
 AND r.state IN ('proposed','reserved'))
 OR NOT EXISTS(SELECT 1 FROM cehub_project.resource_capacity_versions c
 JOIN cehub_project.resource_priority_versions p ON p.tenant_id=c.tenant_id
 AND p.resource_id=c.resource_id WHERE c.tenant_id=NEW.tenant_id
 AND c.id=NEW.capacity_version_id AND p.id=NEW.policy_id)
 OR NOT EXISTS(SELECT 1 FROM cehub_project.resource_reallocations a,
 LATERAL jsonb_array_elements(a.snapshot->'items') i
 WHERE a.tenant_id=NEW.tenant_id AND a.id=NEW.allocation_id
 AND i->>'reservation_id'=NEW.reservation_id::text AND i->>'project_id'=NEW.project_id::text
 AND i->'target'->>'capacity_version_id'=NEW.capacity_version_id::text
 AND i->>'policy_id'=NEW.policy_id::text)
 THEN RAISE EXCEPTION 'reallocation original reservation and target policy required'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_project.require_reallocation_parts() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.snapshot->>'version' IS DISTINCT FROM 'resource.reallocation.v1'
 OR NEW.inputs->>'request_id' IS DISTINCT FROM NEW.request_id::text
 OR jsonb_array_length(NEW.inputs->'items') NOT BETWEEN 2 AND 20
 OR (SELECT count(*) FROM cehub_project.resource_reallocation_projects
 WHERE tenant_id=NEW.tenant_id AND allocation_id=NEW.id)<2
 OR (SELECT count(*) FROM cehub_project.resource_reallocation_items
 WHERE tenant_id=NEW.tenant_id AND allocation_id=NEW.id)
 IS DISTINCT FROM jsonb_array_length(NEW.inputs->'items')
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.inputs->'items') i
 WHERE NOT EXISTS(SELECT 1 FROM cehub_project.resource_reallocation_items v
 WHERE v.tenant_id=NEW.tenant_id AND v.allocation_id=NEW.id
 AND v.reservation_id::text=i->>'reservation_id'))
 OR NOT EXISTS(SELECT 1 FROM cehub_core.users u WHERE u.tenant_id=NEW.tenant_id
 AND u.id=NEW.created_by_user_id AND u.is_active AND u.role IN ('owner','admin'))
 THEN RAISE EXCEPTION 'reallocation requires full project and original reservation bindings'; 
END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_project.guard_reallocation_decision() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE saved cehub_project.resource_reallocations%ROWTYPE;
BEGIN
 SELECT * INTO saved FROM cehub_project.resource_reallocations
 WHERE tenant_id=NEW.tenant_id AND id=NEW.allocation_id;
 IF saved.payload_digest IS DISTINCT FROM NEW.payload_digest
 OR EXISTS(SELECT 1 FROM cehub_project.resource_reallocation_applications
 WHERE tenant_id=NEW.tenant_id AND allocation_id=NEW.allocation_id)
 OR EXISTS(SELECT 1 FROM cehub_project.resource_reallocation_decisions
 WHERE tenant_id=NEW.tenant_id AND allocation_id=NEW.allocation_id AND action IN 
('reject','withdraw'))
 THEN RAISE EXCEPTION 'reallocation version changed or ended'; END IF;
 IF NEW.action='withdraw' THEN
  IF NEW.actor_user_id<>saved.created_by_user_id THEN
   RAISE EXCEPTION 'only proposer may withdraw'; END IF;
 ELSE
  IF NOT EXISTS(SELECT 1 FROM cehub_project.resource_reallocation_projects part
  JOIN cehub_project.projects p ON p.tenant_id=part.tenant_id AND p.id=part.project_id
  JOIN cehub_core.users u ON u.tenant_id=p.tenant_id AND u.id=p.owner_user_id
  WHERE part.tenant_id=NEW.tenant_id AND part.allocation_id=NEW.allocation_id
  AND part.project_id=NEW.project_id AND part.owner_user_id=NEW.actor_user_id
  AND p.owner_user_id=NEW.actor_user_id AND u.is_active
  AND u.role IN ('owner','admin','project_manager')) THEN
   RAISE EXCEPTION 'current named project owner required'; END IF;
 END IF;
 IF NEW.action='approve' AND saved.snapshot->>'capacity_clear' IS DISTINCT FROM 'true'
 THEN RAISE EXCEPTION 'unresolved capacity cannot be approved'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_project.guard_reallocation_application() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE saved cehub_project.resource_reallocations%ROWTYPE; item jsonb; applied jsonb;
BEGIN
 SELECT * INTO saved FROM cehub_project.resource_reallocations
 WHERE tenant_id=NEW.tenant_id AND id=NEW.allocation_id;
 IF saved.payload_digest IS DISTINCT FROM NEW.payload_digest
 OR saved.snapshot->>'capacity_clear' IS DISTINCT FROM 'true'
 OR NEW.receipt->>'baseline_changed' IS DISTINCT FROM 'false'
 OR NEW.receipt->>'commitments_changed' IS DISTINCT FROM 'false'
 OR NOT EXISTS(SELECT 1 FROM cehub_core.users WHERE tenant_id=NEW.tenant_id
 AND id=NEW.actor_user_id AND is_active AND role IN ('owner','admin'))
 OR EXISTS(SELECT 1 FROM cehub_project.resource_reallocation_decisions
 WHERE tenant_id=NEW.tenant_id AND allocation_id=NEW.allocation_id AND action<>'approve')
 OR EXISTS(SELECT 1 FROM cehub_project.resource_reallocation_projects p
 JOIN cehub_project.projects cp ON cp.tenant_id=p.tenant_id AND cp.id=p.project_id
 WHERE p.tenant_id=NEW.tenant_id AND p.allocation_id=NEW.allocation_id AND (
 cp.owner_user_id IS DISTINCT FROM p.owner_user_id OR NOT EXISTS(
 SELECT 1 FROM cehub_project.resource_reallocation_decisions d
 WHERE d.tenant_id=p.tenant_id AND d.allocation_id=p.allocation_id
 AND d.project_id=p.project_id AND d.actor_user_id=p.owner_user_id AND d.action='approve'
 AND d.payload_digest=NEW.payload_digest)))
 OR jsonb_array_length(NEW.receipt->'items') IS DISTINCT FROM 
jsonb_array_length(saved.snapshot->'items')
 THEN RAISE EXCEPTION 'all named project consents required for fixed reallocation'; END IF;
 FOR item IN SELECT * FROM jsonb_array_elements(saved.snapshot->'items') LOOP
  SELECT v INTO applied FROM jsonb_array_elements(NEW.receipt->'items') v
  WHERE v->>'previous_reservation_id'=item->>'reservation_id';
  IF applied IS NULL OR NOT EXISTS(SELECT 1 FROM cehub_project.resource_reservations r
  WHERE r.tenant_id=NEW.tenant_id AND r.id::text=applied->>'reservation_id'
  AND r.project_id::text=item->>'project_id' AND r.state='reserved'
  AND r.node_id::text=item->'original'->>'node_id'
  AND r.capacity_version_id::text=item->'target'->>'capacity_version_id'
  AND r.parallel_units=(item->'target'->>'parallel_units')::numeric
  AND r.window_start=(item->'target'->>'window_start')::timestamptz
  AND r.window_end=(item->'target'->>'window_end')::timestamptz
  AND r.occupancy_policy=item->'target'->>'occupancy_policy'
  AND r.contract->>'priority_policy_version'='resource.priority.v1:'||(item->>'policy_id'))
  THEN RAISE EXCEPTION 'reallocation receipt must bind exact real reserved target'; END IF;
  IF item->'original'->>'state'='reserved' AND NOT EXISTS(
  SELECT 1 FROM cehub_project.resource_reservation_replacements v
  WHERE v.tenant_id=NEW.tenant_id AND v.id::text=applied->>'replacement_id'
  AND v.previous_reservation_id::text=item->>'reservation_id'
  AND v.replacement_reservation_id::text=applied->>'reservation_id')
  THEN RAISE EXCEPTION 'reallocation requires original replacement receipt'; END IF;
  IF item->'original'->>'state'='proposed'
  AND applied->>'reservation_id' IS DISTINCT FROM item->>'reservation_id'
  THEN RAISE EXCEPTION 'pending beneficiary must retain original reservation'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_reallocation_project BEFORE INSERT ON 
cehub_project.resource_reallocation_projects
FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_reallocation_project();
CREATE TRIGGER guard_reallocation_item BEFORE INSERT ON cehub_project.resource_reallocation_items
FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_reallocation_item();
CREATE TRIGGER guard_reallocation_decision BEFORE INSERT ON 
cehub_project.resource_reallocation_decisions
FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_reallocation_decision();
CREATE TRIGGER guard_reallocation_application BEFORE INSERT ON 
cehub_project.resource_reallocation_applications
FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_reallocation_application();
CREATE CONSTRAINT TRIGGER require_reallocation_parts AFTER INSERT
ON cehub_project.resource_reallocations DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION cehub_project.require_reallocation_parts();

"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)
    for table in TABLES:
        op.execute(f"REVOKE ALL ON cehub_project.{table} FROM PUBLIC")
        op.execute(
            f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE "
            f"ON cehub_project.{table} FOR EACH ROW "
            "EXECUTE FUNCTION cehub_ai.protect_checkpoint_history()"
        )
    op.execute(
        "CREATE INDEX ix_reallocation_history ON cehub_project.resource_reallocations"
        "(tenant_id,created_at DESC,id DESC)"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_project.resource_reallocations) "
        "THEN RAISE EXCEPTION 'resource reallocation history cannot be discarded'; END IF; END $$"
    )
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE cehub_project.{table}")
    for name in (
        "guard_reallocation_project",
        "guard_reallocation_item",
        "require_reallocation_parts",
        "guard_reallocation_decision",
        "guard_reallocation_application",
    ):
        op.execute(f"DROP FUNCTION cehub_project.{name}()")
