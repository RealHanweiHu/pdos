"""Persist reproducible Cost BOM calculations without treating them as frozen approvals."""

from alembic import op

revision = "0323_cost_rollups"
down_revision = "0322_cost_inputs"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_cost.cost_rollups (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    bom_id UUID NOT NULL,
    title VARCHAR(256) NOT NULL,
    algorithm VARCHAR(64) NOT NULL,
    command JSONB NOT NULL,
    snapshot JSONB NOT NULL,
    result JSONB NOT NULL,
    source_digest VARCHAR(64) NOT NULL,
    calculation_digest VARCHAR(64) NOT NULL,
    created_by_user_id UUID NOT NULL,
    request_id UUID NOT NULL,
    request_digest VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_cost_rollups PRIMARY KEY (id),
    CONSTRAINT fk_cost_rollups_tenant_id_development_boms FOREIGN KEY(tenant_id, project_id,
bom_id) REFERENCES cehub_product.development_boms (tenant_id, project_id, id) ON DELETE
RESTRICT,
    CONSTRAINT fk_cost_rollups_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT uq_cost_rollup_scope UNIQUE (tenant_id, project_id, id),
    CONSTRAINT uq_cost_rollup_request UNIQUE (tenant_id, created_by_user_id, request_id),
    CONSTRAINT ck_cost_rollups_shape CHECK (btrim(title)<>'' AND btrim(algorithm)<>'' AND
jsonb_typeof(command)='object' AND jsonb_typeof(snapshot)='object' AND
jsonb_typeof(result)='object'),
    CONSTRAINT ck_cost_rollups_digests CHECK (source_digest ~ '^[0-9a-f]{64}$' AND
calculation_digest ~ '^[0-9a-f]{64}$' AND request_digest ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_cost_rollups_history ON cehub_cost.cost_rollups (tenant_id, project_id,
created_at, id);
"""

GUARD = """
CREATE FUNCTION cehub_cost.guard_cost_rollup() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE source jsonb; item jsonb; original cehub_cost.cost_inputs; picked jsonb;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id
 FOR UPDATE;
 IF (NEW.algorithm='cost-rollup.v1' AND NEW.result->>'algorithm'=NEW.algorithm
  AND NEW.snapshot->>'algorithm'=NEW.algorithm AND NEW.command->>'bom_id'=NEW.bom_id::text
  AND NEW.command->>'title'=NEW.title AND NEW.snapshot#>>'{bom,id}'=NEW.bom_id::text
  AND NEW.snapshot#>>'{bom,project_id}'=NEW.project_id::text
  AND NEW.snapshot#>>'{bom,bom_type}'='cost'
  AND (NEW.command->>'product_quantity')::numeric>0
  AND NEW.result->>'currency'=NEW.command->>'currency'
  AND jsonb_typeof(NEW.snapshot->'inputs')='array'
  AND jsonb_typeof(NEW.snapshot->'items')='array') IS NOT TRUE THEN
  RAISE EXCEPTION 'Cost calculation requires its fixed scope, policy and source BOM'; END IF;
 picked:=coalesce((SELECT jsonb_agg(p->'input_id') FROM
   jsonb_array_elements(NEW.command->'prices') p),'[]'::jsonb)
   ||coalesce(NEW.command->'target_ids','[]'::jsonb)
   ||coalesce(NEW.command->'rate_ids','[]'::jsonb);
 IF jsonb_array_length(picked)<>jsonb_array_length(NEW.snapshot->'inputs')
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(picked) id
    GROUP BY id HAVING count(*)>1) THEN
  RAISE EXCEPTION 'Cost input selections must have one fixed source each'; END IF;
 FOR source IN SELECT * FROM jsonb_array_elements(NEW.snapshot->'inputs') LOOP
  SELECT * INTO original FROM cehub_cost.cost_inputs
   WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
   AND id::text=source->>'id';
  IF original.id IS NULL OR source->'payload' IS DISTINCT FROM original.payload
   OR source->'snapshot' IS DISTINCT FROM original.snapshot
   OR source->>'record_id' IS DISTINCT FROM original.record_id::text
   OR source->>'version' IS DISTINCT FROM original.version::text
   OR NOT picked @> jsonb_build_array(source->'id') THEN
   RAISE EXCEPTION 'Cost calculation must retain actual source versions'; END IF;
 END LOOP;
 FOR item IN SELECT * FROM jsonb_array_elements(NEW.snapshot->'items') LOOP
  IF NOT EXISTS (SELECT 1 FROM cehub_product.development_bom_items b
   WHERE b.tenant_id=NEW.tenant_id AND b.project_id=NEW.project_id AND b.bom_id=NEW.bom_id
   AND b.id::text=item->>'id' AND b.quantity=(item->>'quantity')::numeric
   AND b.unit=item->>'unit' AND b.parent_item_id::text IS NOT DISTINCT FROM
     item->>'parent_item_id') THEN
   RAISE EXCEPTION 'Cost quantities must match the source BOM structure'; END IF;
 END LOOP;
 IF jsonb_array_length(NEW.snapshot->'items')<>(SELECT count(*) FROM
  cehub_product.development_bom_items WHERE tenant_id=NEW.tenant_id
  AND project_id=NEW.project_id AND bom_id=NEW.bom_id) THEN
  RAISE EXCEPTION 'Cost calculation cannot silently omit BOM items'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER cost_rollup_guard BEFORE INSERT ON cehub_cost.cost_rollups
FOR EACH ROW EXECUTE FUNCTION cehub_cost.guard_cost_rollup();
CREATE TRIGGER cost_rollup_immutable BEFORE UPDATE OR DELETE ON cehub_cost.cost_rollups
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
REVOKE ALL ON cehub_cost.cost_rollups FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_cost.guard_cost_rollup() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
     IF EXISTS (SELECT 1 FROM cehub_cost.cost_rollups) THEN
      RAISE EXCEPTION 'Retain immutable cost calculation history'; END IF;
    END $$;
    DROP TABLE cehub_cost.cost_rollups;
    DROP FUNCTION cehub_cost.guard_cost_rollup();
    """)
