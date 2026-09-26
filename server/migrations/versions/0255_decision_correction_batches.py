"""Atomic historical Decision source correction batches."""

from alembic import op

revision = "0255_decision_correction_batches"
down_revision = "0254_project_intake_results"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE cehub_project.decision_intake_correction_batches (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        import_batch_id UUID NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        reason TEXT NOT NULL,
        results JSONB NOT NULL,
        created_by_user_id UUID NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT pk_decision_intake_correction_batches PRIMARY KEY (id),
        CONSTRAINT uq_decision_correction_batch_request UNIQUE (tenant_id, project_id,
request_id),
        CONSTRAINT fk_decision_intake_correction_batches_import_batch_id_d_3f38 FOREIGN
KEY(import_batch_id) REFERENCES cehub_ai.decision_intake_batches (id) ON DELETE RESTRICT,
        CONSTRAINT fk_decision_intake_correction_batches_tenant_id_projects FOREIGN
KEY(tenant_id, project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE
RESTRICT,
        CONSTRAINT fk_decision_intake_correction_batches_tenant_id_users FOREIGN
KEY(tenant_id, created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE
RESTRICT,
        CONSTRAINT ck_decision_intake_correction_batches_request CHECK (request_digest ~
'^[0-9a-f]{64}$' AND btrim(reason)<>''),
        CONSTRAINT ck_decision_intake_correction_batches_results CHECK
(jsonb_typeof(results)='array' AND jsonb_array_length(results) BETWEEN 1 AND 50)
);
CREATE INDEX ix_decision_correction_batch_history ON
cehub_project.decision_intake_correction_batches (tenant_id, project_id, import_batch_id,
id);
"""
GUARD = """
CREATE FUNCTION cehub_project.guard_decision_correction_batch() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE item jsonb; seen uuid[] := ARRAY[]::uuid[]; source_id uuid;
 original cehub_ai.decision_intake_batches%ROWTYPE;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Decision correction batches are immutable'; END IF;
 SELECT * INTO original FROM cehub_ai.decision_intake_batches
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.import_batch_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Original batch is not in this project'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(NEW.results) LOOP
  source_id := (item->>'source_row_id')::uuid;
  IF source_id IS NULL OR source_id=ANY(seen) THEN
   RAISE EXCEPTION 'One correction per source in a batch'; END IF;
  seen := array_append(seen, source_id);
  IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(original.results) v
   WHERE v->>'source_row_id'=source_id::text AND v->>'status' IN ('created','linked','reused'))
  OR NOT EXISTS (SELECT 1 FROM cehub_project.decision_intake_corrections c
   WHERE c.tenant_id=NEW.tenant_id AND c.project_id=NEW.project_id
   AND c.source_row_id=source_id AND c.id=(item->>'correction_id')::uuid
   AND c.revision=(item->>'revision')::integer AND c.action=item->>'action'
   AND c.created_by_user_id=NEW.created_by_user_id
   AND c.previous_decision_id IS NOT DISTINCT FROM (item->>'previous_decision_id')::uuid
   AND c.previous_issue_id IS NOT DISTINCT FROM (item->>'previous_issue_id')::uuid
   AND c.target_decision_id IS NOT DISTINCT FROM (item->>'target_decision_id')::uuid
   AND c.target_issue_id IS NOT DISTINCT FROM (item->>'target_issue_id')::uuid
   AND c.reason=item->>'reason' AND c.impact_note=item->>'impact_note'
   AND c.before_snapshot=item->'before_snapshot' AND c.after_snapshot=item->'after_snapshot') THEN
   RAISE EXCEPTION 'Batch must bind actual scoped source corrections';
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_project.guard_decision_correction_batch() FROM PUBLIC;
CREATE TRIGGER guard_decision_correction_batch BEFORE INSERT OR UPDATE OR DELETE
ON cehub_project.decision_intake_correction_batches FOR EACH ROW
EXECUTE FUNCTION cehub_project.guard_decision_correction_batch();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_project.decision_intake_correction_batches) THEN
      RAISE EXCEPTION 'Decision correction batch history must be retained';
    END IF;
    END $$""")
    op.execute("DROP TABLE cehub_project.decision_intake_correction_batches")
    op.execute("DROP FUNCTION cehub_project.guard_decision_correction_batch()")
