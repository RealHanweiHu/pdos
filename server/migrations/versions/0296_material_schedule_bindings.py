"""Versioned explicit material impacts on forecast nodes."""

from alembic import op

revision = "0296_material_schedule_bindings"
down_revision = "0295_material_exceptions"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE cehub_supplier.material_schedule_bindings (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
exception_id UUID NOT NULL,
version INTEGER NOT NULL,
review_id UUID NOT NULL,
mode VARCHAR(16) NOT NULL,
target_point VARCHAR(16) NOT NULL,
node_ids JSONB NOT NULL,
ready_at TIMESTAMP WITH TIME ZONE,
source_digest VARCHAR(64) NOT NULL,
snapshot JSONB NOT NULL,
reason TEXT NOT NULL,
created_by_user_id UUID NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
CONSTRAINT pk_material_schedule_bindings PRIMARY KEY (id),
CONSTRAINT uq_material_schedule_version UNIQUE (tenant_id, exception_id, version),
CONSTRAINT uq_material_schedule_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT fk_material_schedule_bindings_tenant_id_material_exceptions FOREIGN KEY(tenant_id,
project_id, exception_id) REFERENCES cehub_supplier.material_exceptions (tenant_id, project_id,
id) ON DELETE RESTRICT,
CONSTRAINT fk_material_schedule_bindings_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_material_schedule_bindings_binding_policy CHECK (version>0 AND mode IN
('waiting','estimate','released') AND target_point IN ('start','remaining') AND
btrim(reason)<>''),
CONSTRAINT ck_material_schedule_bindings_binding_objects CHECK (jsonb_typeof(node_ids)='array' AND
jsonb_typeof(snapshot)='object' AND jsonb_array_length(node_ids)<=100),
CONSTRAINT ck_material_schedule_bindings_binding_time CHECK ((mode='estimate' AND ready_at IS NOT
NULL) OR (mode<>'estimate' AND ready_at IS NULL)),
CONSTRAINT ck_material_schedule_bindings_binding_nodes CHECK ((mode='released' AND
jsonb_array_length(node_ids)=0) OR (mode<>'released' AND jsonb_array_length(node_ids)>0)),
CONSTRAINT ck_material_schedule_bindings_digests_valid CHECK (source_digest ~ '^[0-9a-f]{64}$' AND
request_digest ~ '^[0-9a-f]{64}$'),
CONSTRAINT fk_material_schedule_bindings_review_id_material_except_ea96 FOREIGN KEY(review_id)
REFERENCES cehub_supplier.material_exception_reviews (id) ON DELETE RESTRICT
);
"""

GUARDS = """
CREATE FUNCTION cehub_supplier.material_schedule_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE current_version integer; review cehub_supplier.material_exception_reviews%ROWTYPE;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id
 AND id=NEW.project_id FOR UPDATE;
 SELECT coalesce(max(version),0) INTO current_version FROM cehub_supplier.material_schedule_bindings
 WHERE tenant_id=NEW.tenant_id AND exception_id=NEW.exception_id;
 IF NEW.version<>current_version+1 OR (NEW.mode='released' AND current_version=0) THEN
 RAISE EXCEPTION 'Material schedule revision must follow its original binding'; END IF;
 SELECT * INTO STRICT review FROM cehub_supplier.material_exception_reviews WHERE id=NEW.review_id;
 IF review.tenant_id<>NEW.tenant_id OR review.project_id<>NEW.project_id
 OR review.exception_id<>NEW.exception_id OR EXISTS (
 SELECT 1 FROM cehub_supplier.material_exception_reviews newer
 WHERE newer.tenant_id=NEW.tenant_id AND newer.exception_id=NEW.exception_id
 AND newer.version>review.version) OR
 NEW.snapshot#>>'{review,id}' IS DISTINCT FROM NEW.review_id::text OR
 NEW.snapshot->>'source_digest' IS DISTINCT FROM NEW.source_digest OR
 NEW.snapshot#>>'{source,revision_id}' IS DISTINCT FROM review.revision_id::text THEN
 RAISE EXCEPTION 'Material schedule requires its current scoped review and source'; END IF;
 IF NEW.mode='estimate' AND NEW.ready_at<=clock_timestamp() THEN
 RAISE EXCEPTION 'Expected material availability must be in the future'; END IF;
 IF (SELECT count(DISTINCT value) FROM jsonb_array_elements_text(NEW.node_ids))
 <>jsonb_array_length(NEW.node_ids) THEN
 RAISE EXCEPTION 'Affected schedule nodes cannot repeat'; END IF;
 IF EXISTS (SELECT 1 FROM jsonb_array_elements_text(NEW.node_ids) AS selected(node_id)
 WHERE NOT EXISTS (SELECT 1 FROM cehub_project.schedule_nodes n
 JOIN cehub_project.schedule_time_nodes tn ON tn.tenant_id=n.tenant_id AND tn.node_id=n.id
 JOIN cehub_project.schedule_time_records tr ON tr.tenant_id=tn.tenant_id AND tr.id=tn.record_id
 WHERE n.tenant_id=NEW.tenant_id AND n.project_id=NEW.project_id AND n.id=selected.node_id::uuid
 AND tr.time_kind='baseline' AND tr.id::text=NEW.snapshot->>'baseline_id'
 AND NOT EXISTS (SELECT 1 FROM cehub_project.schedule_time_records newer
 WHERE newer.tenant_id=tr.tenant_id AND newer.project_id=tr.project_id
 AND newer.time_kind='baseline' AND newer.version>tr.version))) THEN
 RAISE EXCEPTION 'Material impact requires actual nodes in the current formal baseline'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER material_schedule_guard BEFORE INSERT ON cehub_supplier.material_schedule_bindings
 FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_schedule_guard();
CREATE TRIGGER material_schedule_immutable BEFORE UPDATE OR DELETE
 ON cehub_supplier.material_schedule_bindings
 FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_supplier.material_schedule_bindings) THEN
    RAISE EXCEPTION 'Material forecast history requires retention; downgrade refused'; END IF;
    END $$;
    DROP TABLE cehub_supplier.material_schedule_bindings;
    DROP FUNCTION cehub_supplier.material_schedule_guard();
    """)
