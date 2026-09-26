"""Immutable in-progress project assessments and actual initialization tasks."""

from alembic import op

revision = "0247_project_intake"
down_revision = "0246_email_intake"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_project.project_intake_proposals (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	project_id UUID NOT NULL,
	created_by_user_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	revision INTEGER NOT NULL,
	request_id UUID NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	purpose TEXT NOT NULL,
	draft JSONB NOT NULL,
	sources JSONB NOT NULL,
	project_snapshot JSONB NOT NULL,
	gaps JSONB NOT NULL,
	CONSTRAINT pk_project_intake_proposals PRIMARY KEY (id),
	CONSTRAINT uq_project_intake_proposals_scope UNIQUE (tenant_id, project_id, id),
    CONSTRAINT fk_project_intake_proposals_tenant_id_projects FOREIGN KEY(tenant_id, project_id)
REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_project_intake_proposals_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_project_intake_revision UNIQUE (tenant_id, project_id, revision),
	CONSTRAINT uq_project_intake_request UNIQUE (tenant_id, project_id, request_id),
    CONSTRAINT ck_project_intake_proposals_identity CHECK (revision>0 AND btrim(purpose)<>'' AND
request_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_project_intake_proposals_shape CHECK (jsonb_typeof(draft)='object' AND
jsonb_typeof(sources)='array' AND jsonb_array_length(sources)<=30 AND
jsonb_typeof(project_snapshot)='object' AND jsonb_typeof(gaps)='object')
)

;

CREATE TABLE cehub_project.project_intake_work (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	project_id UUID NOT NULL,
	created_by_user_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	proposal_id UUID NOT NULL,
	work_key UUID NOT NULL,
	task_id UUID NOT NULL,
	input_digest VARCHAR(64) NOT NULL,
	work_snapshot JSONB NOT NULL,
	source_snapshot JSONB NOT NULL,
	task_snapshot JSONB NOT NULL,
	link_kind VARCHAR(16) NOT NULL,
	CONSTRAINT pk_project_intake_work PRIMARY KEY (id),
	CONSTRAINT uq_project_intake_work_scope UNIQUE (tenant_id, project_id, id),
    CONSTRAINT fk_project_intake_work_tenant_id_projects FOREIGN KEY(tenant_id, project_id)
REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_project_intake_work_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_project_intake_work_tenant_id_project_intake_proposals FOREIGN KEY(tenant_id,
project_id, proposal_id) REFERENCES cehub_project.project_intake_proposals (tenant_id,
project_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_project_intake_work_key UNIQUE (tenant_id, project_id, work_key),
    CONSTRAINT fk_project_intake_work_tenant_id_tasks FOREIGN KEY(tenant_id, project_id,
task_id) REFERENCES cehub_project.tasks (tenant_id, project_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_project_intake_work_identity CHECK (input_digest ~ '^[0-9a-f]{64}$' AND
link_kind IN ('created','linked')),
    CONSTRAINT ck_project_intake_work_shape CHECK (jsonb_typeof(work_snapshot)='object' AND
jsonb_typeof(source_snapshot)='array' AND jsonb_typeof(task_snapshot)='object')
)

;
CREATE INDEX ix_project_intake_task ON cehub_project.project_intake_work (tenant_id, project_id,
task_id);

CREATE TABLE cehub_project.project_intake_applications (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	project_id UUID NOT NULL,
	created_by_user_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	proposal_id UUID NOT NULL,
	request_id UUID NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	reason TEXT NOT NULL,
	results JSONB NOT NULL,
	CONSTRAINT pk_project_intake_applications PRIMARY KEY (id),
	CONSTRAINT uq_project_intake_applications_scope UNIQUE (tenant_id, project_id, id),
    CONSTRAINT fk_project_intake_applications_tenant_id_projects FOREIGN KEY(tenant_id,
project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_project_intake_applications_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_project_intake_applications_tenant_id_project_intake_4e0f FOREIGN
KEY(tenant_id, project_id, proposal_id) REFERENCES cehub_project.project_intake_proposals
(tenant_id, project_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_project_intake_apply_request UNIQUE (tenant_id, project_id, request_id),
    CONSTRAINT ck_project_intake_applications_identity CHECK (request_digest ~ '^[0-9a-f]{64}$'
AND btrim(reason)<>''),
    CONSTRAINT ck_project_intake_applications_shape CHECK (jsonb_typeof(results)='array' AND
jsonb_array_length(results) BETWEEN 1 AND 50)
)

;
CREATE INDEX ix_project_intake_apply_history ON cehub_project.project_intake_applications
(tenant_id, project_id, proposal_id, created_at);
"""

GUARD = """
CREATE FUNCTION cehub_project.guard_project_intake() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE p cehub_project.project_intake_proposals%ROWTYPE;
 entry jsonb; expected_sources jsonb; latest integer;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Project intake history is immutable' USING ERRCODE='23514';
 END IF;
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR
UPDATE;
 IF TG_TABLE_NAME='project_intake_proposals' THEN
  SELECT COALESCE(max(revision),0) INTO latest FROM cehub_project.project_intake_proposals
   WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id;
  IF NEW.revision<>latest+1 OR NEW.project_snapshot->'project'->>'id'<>NEW.project_id::text THEN
   RAISE EXCEPTION 'Project intake revision or scope differs' USING ERRCODE='23514';
  END IF;
  FOR entry IN SELECT value FROM jsonb_array_elements(NEW.sources) LOOP
   IF NOT EXISTS (SELECT 1 FROM cehub_project.documents d WHERE d.tenant_id=NEW.tenant_id
     AND d.project_id=NEW.project_id AND d.id=(entry->'document'->>'id')::uuid
     AND d.sha256=entry->'document'->>'sha256' AND d.classification='internal') THEN
    RAISE EXCEPTION 'Intake source is not a current project original' USING ERRCODE='23514';
   END IF;
  END LOOP;
 ELSE
  SELECT * INTO p FROM cehub_project.project_intake_proposals WHERE tenant_id=NEW.tenant_id
   AND project_id=NEW.project_id AND id=NEW.proposal_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'Intake proposal scope differs' USING ERRCODE='23514'; END
IF;
  IF TG_TABLE_NAME='project_intake_work' THEN
   IF NEW.work_snapshot->>'key'<>NEW.work_key::text
    OR NEW.task_snapshot->>'id'<>NEW.task_id::text
    OR NOT (p.draft->'work' @> jsonb_build_array(NEW.work_snapshot)) THEN
     RAISE EXCEPTION 'Task binding differs from the fixed proposal' USING ERRCODE='23514';
   END IF;
   SELECT COALESCE(jsonb_agg(e.value ORDER BY e.ordinality),'[]'::jsonb) INTO expected_sources
    FROM jsonb_array_elements(p.sources) WITH ORDINALITY AS e(value,ordinality)
    WHERE e.value->>'key' IN (SELECT
jsonb_array_elements_text(NEW.work_snapshot->'observation_keys'));
   IF NEW.source_snapshot<>expected_sources THEN
    RAISE EXCEPTION 'Task binding sources differ' USING ERRCODE='23514';
   END IF;
  ELSE
   FOR entry IN SELECT value FROM jsonb_array_elements(NEW.results) LOOP
    IF NOT EXISTS (SELECT 1 FROM cehub_project.project_intake_work w
     WHERE w.tenant_id=NEW.tenant_id AND w.project_id=NEW.project_id
      AND w.work_key=(entry->>'work_key')::uuid AND w.task_id=(entry->>'task_id')::uuid
      AND (entry->>'status'='reused' OR (w.proposal_id=NEW.proposal_id AND
w.link_kind=entry->>'status'))) THEN
     RAISE EXCEPTION 'Intake receipt lacks an actual task binding' USING ERRCODE='23514';
    END IF;
   END LOOP;
  END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_project.guard_project_intake() FROM PUBLIC;
CREATE TRIGGER guard_project_intake_proposals BEFORE INSERT OR UPDATE OR DELETE ON
cehub_project.project_intake_proposals FOR EACH ROW EXECUTE FUNCTION
cehub_project.guard_project_intake();
CREATE TRIGGER guard_project_intake_work BEFORE INSERT OR UPDATE OR DELETE ON
cehub_project.project_intake_work FOR EACH ROW EXECUTE FUNCTION
cehub_project.guard_project_intake();
CREATE TRIGGER guard_project_intake_applications BEFORE INSERT OR UPDATE OR DELETE ON
cehub_project.project_intake_applications FOR EACH ROW EXECUTE FUNCTION
cehub_project.guard_project_intake();

"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
     IF EXISTS (SELECT 1 FROM cehub_project.project_intake_proposals) THEN
      RAISE EXCEPTION 'Project intake history must be retained'; END IF;
    END $$""")
    op.execute("DROP TABLE cehub_project.project_intake_applications")
    op.execute("DROP TABLE cehub_project.project_intake_work")
    op.execute("DROP TABLE cehub_project.project_intake_proposals")
    op.execute("DROP FUNCTION cehub_project.guard_project_intake()")
