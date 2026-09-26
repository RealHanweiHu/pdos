"""Immutable grouped Finding decisions and independent applications."""

from alembic import op

revision = "0260_finding_batches"
down_revision = "0259_reminder_preferences"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_ai.finding_batches (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	project_id UUID NOT NULL,
	actor_user_id UUID NOT NULL,
	request_id UUID NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	action VARCHAR(16) NOT NULL,
	finding_type VARCHAR(64) NOT NULL,
	request JSONB NOT NULL,
	results JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT pk_finding_batches PRIMARY KEY (id),
        CONSTRAINT fk_finding_batches_tenant_id_projects FOREIGN KEY(tenant_id, project_id)
REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_finding_batches_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_finding_batch_request UNIQUE (tenant_id, actor_user_id, request_id),
        CONSTRAINT ck_finding_batches_request CHECK (action IN ('accepted','rejected','applied')
AND request_digest ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_finding_batches_results CHECK (jsonb_typeof(request)='object' AND
jsonb_typeof(results)='array' AND jsonb_array_length(results) BETWEEN 1 AND 20)
)

;
CREATE INDEX ix_finding_batch_history ON cehub_ai.finding_batches (tenant_id, actor_user_id,
created_at, id);
"""
GUARD = """

CREATE FUNCTION cehub_ai.guard_finding_batch() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE item jsonb;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Finding batch receipts are immutable'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(NEW.results) LOOP
  IF NOT EXISTS (SELECT 1 FROM cehub_ai.findings f
   WHERE f.tenant_id=NEW.tenant_id AND f.project_id=NEW.project_id
   AND f.id=(item->>'finding_id')::uuid AND f.finding_type=NEW.finding_type
   AND f.status=NEW.action AND f.updated_at=(item->>'updated_at')::timestamptz
   AND (CASE WHEN NEW.action='applied' THEN f.applied_by_user_id
         ELSE f.reviewed_by_user_id END)=NEW.actor_user_id) THEN
   RAISE EXCEPTION 'Batch must reference actual named Finding decisions';
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_finding_batch() FROM PUBLIC;
CREATE TRIGGER guard_finding_batch BEFORE INSERT OR UPDATE OR DELETE ON cehub_ai.finding_batches
FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_finding_batch();

"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_ai.finding_batches) THEN
      RAISE EXCEPTION 'Finding batch receipts must be retained';
    END IF;
    END $$;
    DROP TABLE cehub_ai.finding_batches;
    DROP FUNCTION cehub_ai.guard_finding_batch();
    """)
