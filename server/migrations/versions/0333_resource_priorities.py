"""Versioned resource priority and deterministic pending reservation order."""

from alembic import op

revision = "0333_resource_priorities"
down_revision = "0332_cost_discussion_inputs"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_project.resource_priority_versions (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        resource_id UUID NOT NULL,
        version INTEGER NOT NULL,
        status VARCHAR(16) NOT NULL,
        valid_from TIMESTAMP WITH TIME ZONE NOT NULL,
        valid_until TIMESTAMP WITH TIME ZONE NOT NULL,
        body JSONB NOT NULL,
        created_by_user_id UUID NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        CONSTRAINT pk_resource_priority_versions PRIMARY KEY (id),
        CONSTRAINT uq_resource_priority_scope UNIQUE (tenant_id, id),
        CONSTRAINT uq_resource_priority_version UNIQUE (tenant_id, resource_id, version),
        CONSTRAINT uq_resource_priority_request UNIQUE (tenant_id, created_by_user_id,
request_id),
        CONSTRAINT fk_resource_priority_versions_tenant_id_planning_resources FOREIGN
KEY(tenant_id, resource_id) REFERENCES cehub_project.planning_resources (tenant_id, id) ON
DELETE RESTRICT,
        CONSTRAINT fk_resource_priority_versions_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_resource_priority_versions_shape CHECK (version>0 AND status IN
('active','suspended') AND valid_until>valid_from AND jsonb_typeof(body)='object' AND
request_digest ~ '^[a-f0-9]{64}$')
)

;

CREATE TABLE cehub_project.resource_priority_bindings (
        tenant_id UUID NOT NULL,
        reservation_id UUID NOT NULL,
        project_id UUID NOT NULL,
        policy_id UUID NOT NULL,
        rank INTEGER NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        CONSTRAINT pk_resource_priority_bindings PRIMARY KEY (tenant_id, reservation_id),
        CONSTRAINT fk_resource_priority_bindings_tenant_id_resource_reservations FOREIGN
KEY(tenant_id, reservation_id) REFERENCES cehub_project.resource_reservations (tenant_id, id) ON
DELETE RESTRICT,
        CONSTRAINT fk_resource_priority_bindings_tenant_id_resource_priori_bd2d FOREIGN
KEY(tenant_id, policy_id) REFERENCES cehub_project.resource_priority_versions (tenant_id, id) ON
DELETE RESTRICT,
        CONSTRAINT ck_resource_priority_bindings_shape CHECK (rank BETWEEN 1 AND 1000)
)

;
"""

GUARDS = """
CREATE FUNCTION cehub_project.resource_priority_conflict(t uuid, wanted uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
WITH target AS (
 SELECT r.*, b.policy_id, b.rank, cap.parallel_units AS capacity_units,
 cap.window_start AS capacity_start, cap.window_end AS capacity_end
 FROM cehub_project.resource_reservations r
 JOIN cehub_project.resource_priority_bindings b ON b.tenant_id=r.tenant_id
 AND b.reservation_id=r.id
 JOIN cehub_project.resource_capacity_versions cap ON cap.tenant_id=r.tenant_id
 AND cap.id=r.capacity_version_id WHERE r.tenant_id=t AND r.id=wanted
), spans AS (
 SELECT i.start,i."end" FROM cehub_project.resource_reservation_intervals i
 WHERE i.tenant_id=t AND i.reservation_id=wanted
), others AS (
 SELECT r.id,r.parallel_units,r.state,i.start,i."end"
 FROM target x JOIN cehub_project.resource_reservations r
 ON r.tenant_id=x.tenant_id AND r.resource_id=x.resource_id AND r.id<>x.id
 JOIN cehub_project.resource_reservation_intervals i
 ON i.tenant_id=r.tenant_id AND i.reservation_id=r.id
 JOIN cehub_project.projects p ON p.tenant_id=r.tenant_id AND p.id=r.project_id
 LEFT JOIN cehub_project.resource_priority_bindings b
 ON b.tenant_id=r.tenant_id AND b.reservation_id=r.id
 WHERE r.state='reserved' OR (
 r.state='proposed' AND b.policy_id=x.policy_id AND p.status IN ('approved','active')
 AND r.capacity_version_id=x.capacity_version_id AND r.window_end>statement_timestamp()
 AND r.window_start>=x.capacity_start AND r.window_end<=x.capacity_end
 AND r.parallel_units<=x.capacity_units
 AND (b.rank < x.rank OR (b.rank=x.rank AND (r.created_at,r.id)<(x.created_at,x.id))))
 UNION ALL
 SELECT NULL::uuid,l.parallel_units,'reserved',l.start,l."end"
 FROM target x JOIN cehub_project.current_legacy_resource_allocations l
 ON l.tenant_id=x.tenant_id AND l.resource_id=x.resource_id
), points AS (
 SELECT start AS at FROM spans UNION SELECT "end" FROM spans
 UNION SELECT o.start FROM others o WHERE EXISTS(
 SELECT 1 FROM spans s WHERE o.start>=s.start AND o.start<s."end")
 UNION SELECT o."end" FROM others o WHERE EXISTS(
 SELECT 1 FROM spans s WHERE o."end">s.start AND o."end"<s."end")
)
SELECT EXISTS(SELECT 1 FROM points p CROSS JOIN target x
 WHERE EXISTS(SELECT 1 FROM spans s WHERE s.start<=p.at AND s."end">p.at)
 AND EXISTS(SELECT 1 FROM others o WHERE o.state='proposed' AND o.start<=p.at AND o."end">p.at)
 AND x.parallel_units+coalesce((SELECT sum(o.parallel_units) FROM others o
 WHERE o.start<=p.at AND o."end">p.at),0)>x.capacity_units)
$$;

CREATE FUNCTION cehub_project.guard_resource_priority_version() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE previous integer;
BEGIN
 PERFORM cehub_project.lock_resource_inventory(NEW.tenant_id);
 PERFORM 1 FROM cehub_project.planning_resources WHERE tenant_id=NEW.tenant_id
 AND id=NEW.resource_id FOR UPDATE;
 SELECT coalesce(max(version),0) INTO previous FROM cehub_project.resource_priority_versions
 WHERE tenant_id=NEW.tenant_id AND resource_id=NEW.resource_id;
 IF NEW.version<>previous+1 OR NEW.body->>'resource_id' IS DISTINCT FROM NEW.resource_id::text
 OR (NEW.body->>'expected_version')::integer IS DISTINCT FROM previous
 OR NEW.body->>'status' IS DISTINCT FROM NEW.status
 OR (NEW.body->>'valid_from')::timestamptz IS DISTINCT FROM NEW.valid_from
 OR (NEW.body->>'valid_until')::timestamptz IS DISTINCT FROM NEW.valid_until
 OR jsonb_typeof(NEW.body->'ranks') IS DISTINCT FROM 'array'
 OR coalesce((NEW.body->>'default_rank')::integer,0) NOT BETWEEN 1 AND 1000
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.body->'ranks') r
 WHERE coalesce((r->>'rank')::integer,0) NOT BETWEEN 1 AND 1000 OR NOT EXISTS(
 SELECT 1 FROM cehub_project.projects p WHERE p.tenant_id=NEW.tenant_id
 AND p.id::text=r->>'project_id'))
 OR (SELECT count(*)<>count(DISTINCT r->>'project_id')
 FROM jsonb_array_elements(NEW.body->'ranks') r)
 THEN RAISE EXCEPTION 'Resource policy requires current version and actual scoped project ranks'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_resource_priority_version BEFORE INSERT ON
cehub_project.resource_priority_versions FOR EACH ROW
EXECUTE FUNCTION cehub_project.guard_resource_priority_version();

CREATE FUNCTION cehub_project.guard_resource_priority_binding() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r cehub_project.resource_reservations; p cehub_project.resource_priority_versions;
BEGIN
 SELECT * INTO r FROM cehub_project.resource_reservations WHERE tenant_id=NEW.tenant_id
 AND id=NEW.reservation_id;
 SELECT * INTO p FROM cehub_project.resource_priority_versions WHERE tenant_id=NEW.tenant_id
 AND id=NEW.policy_id;
 IF (r.project_id=NEW.project_id AND r.resource_id=p.resource_id AND r.state='proposed'
 AND r.contract->>'priority_policy_version'='resource.priority.v1:'||p.id::text
 AND NEW.rank=coalesce((SELECT (v->>'rank')::integer FROM jsonb_array_elements(p.body->'ranks') v
 WHERE v->>'project_id'=r.project_id::text),(p.body->>'default_rank')::integer)) IS NOT TRUE THEN
 RAISE EXCEPTION 'Reservation must retain exact policy and project rank' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_resource_priority_binding BEFORE INSERT ON
cehub_project.resource_priority_bindings FOR EACH ROW
EXECUTE FUNCTION cehub_project.guard_resource_priority_binding();

CREATE FUNCTION cehub_project.guard_priority_reserve() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE p cehub_project.resource_priority_versions;
BEGIN
 IF NEW.state='reserved' AND OLD.state<>'reserved' THEN
 PERFORM cehub_project.lock_resource_inventory(NEW.tenant_id);
 PERFORM 1 FROM cehub_project.planning_resources WHERE tenant_id=NEW.tenant_id
 AND id=NEW.resource_id FOR UPDATE;
 SELECT * INTO p FROM cehub_project.resource_priority_versions WHERE tenant_id=NEW.tenant_id
 AND resource_id=NEW.resource_id ORDER BY version DESC LIMIT 1;
 IF p.id IS NULL OR p.status<>'active' OR NOT
 (p.valid_from<=clock_timestamp() AND clock_timestamp()<p.valid_until)
 OR NEW.contract->>'priority_policy_version' IS DISTINCT FROM 'resource.priority.v1:'||p.id::text
 OR NOT EXISTS(SELECT 1 FROM cehub_project.resource_priority_bindings b
 WHERE b.tenant_id=NEW.tenant_id AND b.reservation_id=NEW.id AND b.policy_id=p.id)
 OR NEW.contract->'approval'->>'policy_version' IS DISTINCT FROM
 NEW.contract->>'priority_policy_version'
 OR cehub_project.resource_priority_conflict(NEW.tenant_id,NEW.id) THEN
 RAISE EXCEPTION 'Reservation priority missing, stale, expired or queued behind higher demand'
 USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_priority_reserve BEFORE UPDATE ON cehub_project.resource_reservations
FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_priority_reserve();

CREATE FUNCTION cehub_project.require_priority_binding() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_project.resource_priority_bindings b
 WHERE b.tenant_id=NEW.tenant_id AND b.reservation_id=NEW.id) THEN
 RAISE EXCEPTION 'New reservation requires explicit versioned resource policy'
 USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER require_priority_binding AFTER INSERT ON
cehub_project.resource_reservations DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION cehub_project.require_priority_binding();
REVOKE ALL ON FUNCTION cehub_project.guard_resource_priority_version() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_project.guard_resource_priority_binding() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_project.guard_priority_reserve() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_project.require_priority_binding() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)
    for name in ("resource_priority_versions", "resource_priority_bindings"):
        op.execute(
            f"CREATE TRIGGER protect_{name} BEFORE UPDATE OR DELETE ON cehub_project.{name} "
            "FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history()"
        )
        op.execute(f"REVOKE ALL ON cehub_project.{name} FROM PUBLIC")


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_project.resource_priority_versions) THEN
RAISE EXCEPTION 'Resource priority history requires retention'; END IF; END $$;
DROP TRIGGER require_priority_binding ON cehub_project.resource_reservations;
DROP TRIGGER guard_priority_reserve ON cehub_project.resource_reservations;
DROP FUNCTION cehub_project.require_priority_binding();
DROP FUNCTION cehub_project.guard_priority_reserve();
DROP FUNCTION cehub_project.resource_priority_conflict(uuid,uuid);
DROP TABLE cehub_project.resource_priority_bindings;
DROP TABLE cehub_project.resource_priority_versions;
DROP FUNCTION cehub_project.guard_resource_priority_binding();
DROP FUNCTION cehub_project.guard_resource_priority_version();
""")
