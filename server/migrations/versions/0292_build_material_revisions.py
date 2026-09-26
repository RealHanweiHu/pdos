"""ECN-linked immutable Build demand revisions and quantity deltas."""

from alembic import op

revision = "0292_build_material_revisions"
down_revision = "0291_build_material_freeze"
branch_labels = None
depends_on = None

DDL = """
ALTER TABLE cehub_product.build_material_revisions ADD COLUMN previous_revision_id uuid, ADD
COLUMN ecn_id uuid, ADD COLUMN change_context jsonb, ADD COLUMN delta jsonb;
ALTER TABLE cehub_product.build_material_revisions ADD CONSTRAINT
fk_build_material_revisions_tenant_id_build_material_revisions FOREIGN KEY(tenant_id, project_id,
previous_revision_id) REFERENCES cehub_product.build_material_revisions (tenant_id, project_id,
id) ON DELETE RESTRICT;
ALTER TABLE cehub_product.build_material_revisions ADD CONSTRAINT
fk_build_material_revisions_tenant_id_engineering_chang_ca41 FOREIGN KEY(tenant_id, project_id,
ecn_id) REFERENCES cehub_product.engineering_change_notices (tenant_id, project_id, id) ON DELETE
RESTRICT;
ALTER TABLE cehub_product.build_material_revisions ADD CONSTRAINT
ck_build_material_revisions_revision_lineage_valid CHECK ((version=1 AND previous_revision_id IS
NULL AND ecn_id IS NULL AND change_context IS NULL AND delta IS NULL) OR (version>1 AND
previous_revision_id IS NOT NULL AND ecn_id IS NOT NULL AND change_context IS NOT NULL AND delta
IS NOT NULL AND jsonb_typeof(change_context)='object' AND jsonb_typeof(delta)='array'));
ALTER TABLE cehub_product.build_material_revisions ADD CONSTRAINT uq_build_material_revision_ecn
UNIQUE (tenant_id, build_id, ecn_id);
"""

GUARD = """

CREATE OR REPLACE FUNCTION cehub_product.guard_build_material_revision() RETURNS trigger
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
   AND NEW.snapshot->'build'->>'id'=b.id::text
   AND NEW.snapshot->'build'->>'phase'=b.phase
   AND NEW.snapshot->'build'->>'stage_id'=b.stage_id::text
   AND (NEW.snapshot->'build'->>'planned_quantity')::integer=b.planned_quantity
   AND NEW.snapshot->'bom'->'header'->>'id'=m.id::text
   AND (NEW.snapshot->'bom'->'header'->>'version')::integer=m.version
   AND NEW.snapshot->'need_by_node'->>'id'=n.id::text
 ) THEN RAISE EXCEPTION 'Build material freeze must bind actual project sources'; END IF;

 IF NEW.version>1 THEN
  IF NOT EXISTS (SELECT 1 FROM cehub_product.build_material_revisions p
   WHERE p.tenant_id=NEW.tenant_id AND p.project_id=NEW.project_id AND p.build_id=NEW.build_id
   AND p.id=NEW.previous_revision_id AND p.version=NEW.version-1
   AND NOT EXISTS (SELECT 1 FROM cehub_product.build_material_revisions later
    WHERE later.tenant_id=p.tenant_id AND later.build_id=p.build_id AND later.version>p.version))
  THEN RAISE EXCEPTION 'Material revision must follow the latest fixed version'; END IF;
  IF NOT EXISTS (SELECT 1 FROM cehub_product.engineering_change_notices n
   JOIN cehub_product.engineering_change_requests r
    ON r.tenant_id=n.tenant_id AND r.project_id=n.project_id AND r.id=n.ecr_id
   JOIN cehub_project.decisions d
    ON d.tenant_id=n.tenant_id AND d.project_id=n.project_id AND d.id=n.effectivity_decision_id
   JOIN cehub_core.users u ON u.tenant_id=n.tenant_id AND u.id=NEW.created_by_user_id
   WHERE n.tenant_id=NEW.tenant_id AND n.project_id=NEW.project_id AND n.id=NEW.ecn_id
   AND n.status='erp_handoff' AND r.status='approved'
   AND d.decision_kind='ecn_effectivity' AND d.outcome='approved'
   AND u.is_active AND u.role IN ('owner','admin','project_manager')
   AND NEW.change_context->'ecn'->>'id'=n.id::text
   AND NEW.change_context->'decision'->>'id'=d.id::text
   AND EXISTS (SELECT 1 FROM jsonb_array_elements(
    r.impact_analysis->'impact_scope'->'basis'->'version'->'snapshot'->'items') item
    WHERE item->>'kind'='build' AND item->>'id'=NEW.build_id::text
     AND item->>'conclusion'='affected')
   AND EXISTS (SELECT 1 FROM jsonb_array_elements(
    r.impact_analysis->'impact_scope'->'basis'->'version'->'snapshot'->'items') item
    WHERE item->>'kind'='bom' AND item->>'id'=NEW.bom_id::text
     AND item->>'conclusion'='affected'))
  THEN RAISE EXCEPTION 'Material revision requires approved ECN and explicit affected scope'; END
IF;
 END IF;
 RETURN NEW;
END $$;
"""

OLD_GUARD = """

CREATE OR REPLACE FUNCTION cehub_product.guard_build_material_revision() RETURNS trigger
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
"""

ROLLBACK = """
ALTER TABLE cehub_product.build_material_revisions DROP CONSTRAINT
fk_build_material_revisions_tenant_id_build_material_revisions;
ALTER TABLE cehub_product.build_material_revisions DROP CONSTRAINT
fk_build_material_revisions_tenant_id_engineering_chang_ca41;
ALTER TABLE cehub_product.build_material_revisions DROP CONSTRAINT
ck_build_material_revisions_revision_lineage_valid;
ALTER TABLE cehub_product.build_material_revisions DROP CONSTRAINT uq_build_material_revision_ecn;
ALTER TABLE cehub_product.build_material_revisions DROP COLUMN previous_revision_id, DROP COLUMN
ecn_id, DROP COLUMN change_context, DROP COLUMN delta;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_product.build_material_revisions WHERE version>1) THEN
      RAISE EXCEPTION 'Retain ECN-linked material revision history';
    END IF;
    END $$;""")
    op.execute(OLD_GUARD)
    op.execute(ROLLBACK)
