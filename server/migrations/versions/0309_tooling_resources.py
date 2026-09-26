"""Actual tooling links to existing shared resource identities."""

from alembic import op

revision = "0309_tooling_resources"
down_revision = "0308_tooling_availability"
branch_labels = None
depends_on = None

DDL = """
ALTER TABLE cehub_supplier.tooling_rounds ADD COLUMN planning_resource_id uuid;
ALTER TABLE cehub_supplier.tooling_rounds ADD CONSTRAINT fk_tooling_round_planning_resource
FOREIGN KEY (tenant_id,planning_resource_id) REFERENCES cehub_project.planning_resources
(tenant_id,id) ON DELETE RESTRICT;
CREATE FUNCTION cehub_supplier.tooling_resource_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE resource cehub_project.planning_resources%ROWTYPE;
BEGIN
 IF NEW.planning_resource_id IS DISTINCT FROM (NEW.payload->>'planning_resource_id')::uuid THEN
 RAISE EXCEPTION 'Tooling resource must match its explicit foreign key'; END IF;
 IF NEW.planning_resource_id IS NOT NULL THEN
  SELECT * INTO STRICT resource FROM cehub_project.planning_resources
  WHERE tenant_id=NEW.tenant_id AND id=NEW.planning_resource_id;
  IF NOT ((NEW.tooling_kind='mold' AND resource.kind='mold')
   OR (NEW.tooling_kind='fixture' AND resource.kind='fixture')
   OR (NEW.tooling_kind='tooling' AND resource.kind IN ('mold','fixture','equipment','bench')))
   OR NEW.snapshot#>>'{sources,planning_resource,id}' IS DISTINCT FROM resource.id::text
   OR NEW.snapshot#>>'{sources,planning_resource,tenant_id}'
      IS DISTINCT FROM resource.tenant_id::text
   OR NEW.snapshot#>>'{sources,planning_resource,kind}' IS DISTINCT FROM resource.kind THEN
   RAISE EXCEPTION 'Tooling resource must match the actual tenant identity and equipment kind';
  END IF;
 ELSIF coalesce(NEW.snapshot#>'{sources,planning_resource}', 'null'::jsonb)<>'null'::jsonb THEN
  RAISE EXCEPTION 'Unlinked tooling cannot retain a current resource claim';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER tooling_resource_insert BEFORE INSERT OR UPDATE ON cehub_supplier.tooling_rounds
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.tooling_resource_guard();
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
    IF EXISTS(SELECT 1 FROM cehub_supplier.tooling_round_revisions
      WHERE payload->>'planning_resource_id' IS NOT NULL) THEN
      RAISE EXCEPTION 'Tooling resource relationship history requires retention';
    END IF;
    END $$;
    DROP TRIGGER tooling_resource_insert ON cehub_supplier.tooling_rounds;
    DROP FUNCTION cehub_supplier.tooling_resource_guard();
    ALTER TABLE cehub_supplier.tooling_rounds DROP COLUMN planning_resource_id;
    """)
