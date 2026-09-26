"""Freeze Build Prototype BOM sources and expanded demand without ERP writes."""

from alembic import op

revision = "0291_build_material_freeze"
down_revision = "0290_meeting_forecast_sources"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE cehub_product.build_material_revisions (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
build_id UUID NOT NULL,
version INTEGER NOT NULL,
bom_id UUID NOT NULL,
need_by_node_id UUID NOT NULL,
created_by_user_id UUID NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
source_digest VARCHAR(64) NOT NULL,
content_digest VARCHAR(64) NOT NULL,
snapshot JSONB NOT NULL,
lines JSONB NOT NULL,
reason TEXT NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
CONSTRAINT pk_build_material_revisions PRIMARY KEY (id),
CONSTRAINT uq_build_material_revision_project UNIQUE (tenant_id, project_id, id),
CONSTRAINT uq_build_material_revision_version UNIQUE (tenant_id, build_id, version),
CONSTRAINT uq_build_material_revision_request UNIQUE (tenant_id, created_by_user_id,
request_id),
CONSTRAINT fk_build_material_revisions_tenant_id_build_batches FOREIGN KEY(tenant_id,
project_id, build_id) REFERENCES cehub_product.build_batches (tenant_id, project_id, id) ON
DELETE RESTRICT,
CONSTRAINT fk_build_material_revisions_tenant_id_development_boms FOREIGN KEY(tenant_id,
project_id, bom_id) REFERENCES cehub_product.development_boms (tenant_id, project_id, id) ON
DELETE RESTRICT,
CONSTRAINT fk_build_material_revisions_tenant_id_schedule_nodes FOREIGN KEY(tenant_id,
project_id, need_by_node_id) REFERENCES cehub_project.schedule_nodes (tenant_id, project_id, id)
ON DELETE RESTRICT,
CONSTRAINT fk_build_material_revisions_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_build_material_revisions_version_reason_valid CHECK (version > 0 AND btrim(reason)
<> ''),
CONSTRAINT ck_build_material_revisions_snapshot_lines_valid CHECK
(jsonb_typeof(snapshot)='object' AND jsonb_typeof(lines)='array' AND
jsonb_array_length(lines)>0),
CONSTRAINT ck_build_material_revisions_prototype_bom_only CHECK
(COALESCE(snapshot->'bom'->'header'->>'bom_type', '')='prototype'),
CONSTRAINT ck_build_material_revisions_digests_valid CHECK (request_digest ~ '^[0-9a-f]{64}$'
AND source_digest ~ '^[0-9a-f]{64}$' AND content_digest ~ '^[0-9a-f]{64}$')
);
"""
GUARD = """
CREATE FUNCTION cehub_product.guard_build_material_revision() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Build material sources and quantities are immutable';
 END IF;
 IF NOT EXISTS (
  SELECT 1 FROM cehub_product.build_batches b
  JOIN cehub_product.development_boms m
   ON m.tenant_id=b.tenant_id AND m.project_id=b.project_id AND m.id=NEW.bom_id
  JOIN cehub_project.schedule_nodes n
   ON n.tenant_id=b.tenant_id AND n.project_id=b.project_id AND n.id=NEW.need_by_node_id
  WHERE b.tenant_id=NEW.tenant_id AND b.project_id=NEW.project_id AND b.id=NEW.build_id
   AND b.status='planned' AND m.bom_type='prototype'
   AND n.node_kind='build' AND n.build_id=b.id
   AND NEW.version=1
   AND NEW.snapshot->'build'->>'id'=b.id::text
   AND NEW.snapshot->'build'->>'phase'=b.phase
   AND NEW.snapshot->'build'->>'stage_id'=b.stage_id::text
   AND (NEW.snapshot->'build'->>'planned_quantity')::integer=b.planned_quantity
   AND NEW.snapshot->'bom'->'header'->>'id'=m.id::text
   AND (NEW.snapshot->'bom'->'header'->>'version')::integer=m.version
   AND NEW.snapshot->'need_by_node'->>'id'=n.id::text
 ) THEN RAISE EXCEPTION 'Build material freeze must bind actual project sources'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_build_material_revision
BEFORE INSERT OR UPDATE OR DELETE ON cehub_product.build_material_revisions
FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_build_material_revision();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_product.build_material_revisions) THEN
      RAISE EXCEPTION 'Retain frozen Build BOM and demand history';
    END IF;
    END $$;
    DROP TABLE cehub_product.build_material_revisions;
    DROP FUNCTION cehub_product.guard_build_material_revision();
    """)
