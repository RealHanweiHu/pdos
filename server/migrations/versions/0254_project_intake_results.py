"""Immutable initialization work execution results and evidence."""

from alembic import op

revision = "0254_project_intake_results"
down_revision = "0253_intake_ai_imports"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE cehub_project.project_intake_work_results (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        binding_id UUID NOT NULL,
        created_by_user_id UUID NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        revision INTEGER NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        outcome VARCHAR(32) NOT NULL,
        summary TEXT NOT NULL,
        criteria_response TEXT NOT NULL,
        remaining TEXT NOT NULL,
        context_snapshot JSONB NOT NULL,
        evidence_snapshot JSONB NOT NULL,
        CONSTRAINT pk_project_intake_work_results PRIMARY KEY (id),
        CONSTRAINT uq_intake_work_result_revision UNIQUE (tenant_id, binding_id, revision),
        CONSTRAINT uq_intake_work_result_request UNIQUE (tenant_id, binding_id, request_id),
        CONSTRAINT fk_project_intake_work_results_tenant_id_project_intake_work FOREIGN
KEY(tenant_id, project_id, binding_id) REFERENCES cehub_project.project_intake_work
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_project_intake_work_results_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_project_intake_work_results_identity CHECK (revision>0 AND
request_digest ~ '^[0-9a-f]{64}$' AND btrim(summary)<>'' AND btrim(criteria_response)<>''
AND btrim(remaining)<>''),
        CONSTRAINT ck_project_intake_work_results_outcome CHECK (outcome IN
('progress','addressed','no_change_needed','follow_up')),
        CONSTRAINT ck_project_intake_work_results_shape CHECK
(jsonb_typeof(context_snapshot)='object' AND jsonb_typeof(evidence_snapshot)='array' AND
jsonb_array_length(evidence_snapshot)<=10 AND (outcome IN ('progress','follow_up') OR
jsonb_array_length(evidence_snapshot)>0))
);
"""
GUARD = """
CREATE FUNCTION cehub_project.guard_intake_work_result() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE b cehub_project.project_intake_work%ROWTYPE;
 t cehub_project.tasks%ROWTYPE; latest integer;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'Initialization result history is immutable';
 END IF;
 SELECT * INTO b FROM cehub_project.project_intake_work
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.binding_id
 FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Initialization binding is missing'; END IF;
 SELECT * INTO t FROM cehub_project.tasks
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=b.task_id
 FOR UPDATE;
 SELECT coalesce(max(revision),0) INTO latest FROM cehub_project.project_intake_work_results
 WHERE tenant_id=NEW.tenant_id AND binding_id=NEW.binding_id;
 IF NEW.revision <> latest+1
 OR (NEW.context_snapshot->>'binding_id') IS DISTINCT FROM b.id::text
 OR (NEW.context_snapshot->'task'->>'id') IS DISTINCT FROM t.id::text
 OR (NEW.context_snapshot->'task'->>'status') IS DISTINCT FROM t.status::text THEN
  RAISE EXCEPTION 'Initialization result basis or revision changed';
 END IF;
 IF NEW.outcome IN ('addressed','no_change_needed') THEN
  IF nullif(btrim(t.expected_output),'') IS NULL
  OR (NEW.context_snapshot->>'source_available') IS DISTINCT FROM 'true'
  OR EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.context_snapshot->'original_sources') s
   WHERE (s->>'current') IS DISTINCT FROM 'true')
  OR (NEW.outcome='addressed' AND t.status::text <> 'done')
  OR (NEW.outcome='no_change_needed' AND t.status::text NOT IN ('done','skipped')) THEN
   RAISE EXCEPTION 'Completion requires actual task handling and current sources';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER intake_work_result_guard BEFORE INSERT OR UPDATE OR DELETE
ON cehub_project.project_intake_work_results FOR EACH ROW
EXECUTE FUNCTION cehub_project.guard_intake_work_result();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_project.project_intake_work_results) THEN
      RAISE EXCEPTION 'Initialization result history must be retained';
    END IF;
    END $$""")
    op.execute("DROP TABLE cehub_project.project_intake_work_results")
    op.execute("DROP FUNCTION cehub_project.guard_intake_work_result()")
