"""Give each schedule projection its own typed trigger function."""

from alembic import op

revision = "0158_schedule_projection_guards"
down_revision = "0157_id_design_checkpoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A shared trigger accesses different NEW row layouts. Keep the two
    # projections separate so cached expressions never reuse the other layout.
    op.execute("""
CREATE FUNCTION cehub_project.guard_schedule_time_node_projection()
RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS (
  SELECT 1 FROM cehub_project.schedule_time_records r
  CROSS JOIN LATERAL jsonb_array_elements(r.contract->'node_times') n
  WHERE r.tenant_id=NEW.tenant_id AND r.project_id=NEW.project_id AND r.id=NEW.record_id
   AND n->>'node_id'=NEW.node_id::text
   AND (n->'window'->>'start')::timestamptz IS NOT DISTINCT FROM NEW."start"
   AND (n->'window'->>'end')::timestamptz IS NOT DISTINCT FROM NEW."end"
 ) THEN
  RAISE EXCEPTION 'Node time must exactly project the immutable approved record'
   USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_project.guard_schedule_time_node_projection() FROM PUBLIC;
DROP TRIGGER guard_plan_application_projection ON cehub_project.schedule_time_nodes;
CREATE TRIGGER guard_plan_application_projection BEFORE INSERT ON cehub_project.schedule_time_nodes
 FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_schedule_time_node_projection();
""")


def downgrade() -> None:
    op.execute("""
DROP TRIGGER guard_plan_application_projection ON cehub_project.schedule_time_nodes;
CREATE TRIGGER guard_plan_application_projection BEFORE INSERT ON cehub_project.schedule_time_nodes
 FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_plan_application_projection();
DROP FUNCTION cehub_project.guard_schedule_time_node_projection();
""")
