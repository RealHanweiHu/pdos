"""Explicit evidence-backed tooling availability and formal need-node scope."""

from alembic import op

revision = "0308_tooling_availability"
down_revision = "0307_tooling_schedule_nodes"
branch_labels = None
depends_on = None

GUARDS = """
CREATE FUNCTION cehub_supplier.tooling_availability_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE fact jsonb; target text; completed timestamptz; available timestamptz;
BEGIN
 target := NEW.payload->>'schedule_target_point';
 fact := NEW.payload->'available';
 IF target IS NOT NULL AND target NOT IN ('start','finish') THEN
 RAISE EXCEPTION 'Tooling availability target must be start or finish'; END IF;
 IF fact IS NOT NULL AND fact<>'null'::jsonb THEN
  available := (fact->>'at')::timestamptz;
  completed := (NEW.payload#>>'{completed,at}')::timestamptz;
  IF jsonb_typeof(fact)<>'object' OR available IS NULL OR completed IS NULL
  OR available<completed OR available>clock_timestamp()
  OR NEW.payload->>'status' IS DISTINCT FROM 'completed'
  OR NEW.payload->>'outcome' IS DISTINCT FROM 'accepted'
  OR coalesce(btrim(fact->>'location'),'')=''
  OR NOT EXISTS (SELECT 1 FROM cehub_project.documents d
    WHERE d.tenant_id=NEW.tenant_id AND d.project_id=NEW.project_id
    AND d.id=(fact->>'evidence_id')::uuid)
  OR NEW.snapshot#>>'{sources,available,document,id}' IS DISTINCT FROM fact->>'evidence_id'
  OR NEW.snapshot#>>'{sources,available,at}' IS DISTINCT FROM fact->>'at'
  OR NEW.snapshot#>>'{sources,available,location}' IS DISTINCT FROM fact->>'location' THEN
   RAISE EXCEPTION 'Tooling availability requires actual accepted result and project evidence';
  END IF;
 END IF;
 IF target IS NOT NULL THEN
  IF coalesce(jsonb_array_length(NEW.payload->'need_node_ids'),0)=0 THEN
   RAISE EXCEPTION 'Tooling availability requires actual need nodes'; END IF;
  IF EXISTS (
   SELECT 1 FROM jsonb_array_elements_text(NEW.payload->'need_node_ids') AS selected(node_id)
   WHERE NOT EXISTS (
    SELECT 1 FROM cehub_project.schedule_nodes n
    JOIN cehub_project.schedule_time_nodes tn ON tn.tenant_id=n.tenant_id AND tn.node_id=n.id
    JOIN cehub_project.schedule_time_records tr ON tr.tenant_id=tn.tenant_id AND tr.id=tn.record_id
    WHERE n.tenant_id=NEW.tenant_id AND n.project_id=NEW.project_id
    AND n.id=selected.node_id::uuid AND n.tooling_id IS DISTINCT FROM NEW.round_id
    AND tr.time_kind='baseline' AND tr.id::text=NEW.snapshot->>'schedule_baseline_id'
    AND NOT EXISTS (SELECT 1 FROM cehub_project.schedule_time_records newer
     WHERE newer.tenant_id=tr.tenant_id AND newer.project_id=tr.project_id
     AND newer.time_kind='baseline' AND newer.version>tr.version))) THEN
   RAISE EXCEPTION 'Tooling need nodes must match the current formal baseline and exclude itself';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER tooling_availability_insert BEFORE INSERT
ON cehub_supplier.tooling_round_revisions FOR EACH ROW
EXECUTE FUNCTION cehub_supplier.tooling_availability_guard();
"""


def upgrade() -> None:
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_supplier.tooling_round_revisions
      WHERE payload->>'schedule_target_point' IS NOT NULL OR payload->>'available' IS NOT NULL) THEN
      RAISE EXCEPTION 'Tooling availability history requires retention';
    END IF;
    END $$;
    DROP TRIGGER tooling_availability_insert ON cehub_supplier.tooling_round_revisions;
    DROP FUNCTION cehub_supplier.tooling_availability_guard();
    """)
