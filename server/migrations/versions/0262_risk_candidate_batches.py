"""Immutable same-project rule risk confirmation receipts."""

from alembic import op

revision = "0262_risk_candidate_batches"
down_revision = "0261_finding_review_undo"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_project.risk_candidate_batches (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	project_id UUID NOT NULL,
	actor_user_id UUID NOT NULL,
	request_id UUID NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	request JSONB NOT NULL,
	results JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT pk_risk_candidate_batches PRIMARY KEY (id),
CONSTRAINT fk_risk_candidate_batches_tenant_id_projects FOREIGN KEY(tenant_id, project_id)
REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_risk_candidate_batches_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_risk_candidate_batch_request UNIQUE (tenant_id, actor_user_id, request_id),
	CONSTRAINT ck_risk_candidate_batches_request CHECK (request_digest ~ '^[0-9a-f]{64}$'),
CONSTRAINT ck_risk_candidate_batches_results CHECK (jsonb_typeof(request)='object' AND
jsonb_typeof(results)='array' AND jsonb_array_length(results) BETWEEN 1 AND 200)
)

;
CREATE INDEX ix_risk_candidate_batch_history ON cehub_project.risk_candidate_batches (tenant_id,
actor_user_id, created_at, id);
"""

GUARD = """
CREATE FUNCTION cehub_project.guard_risk_candidate_batch() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE item jsonb;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Risk confirmation receipts are immutable'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(NEW.results) LOOP
  IF NOT EXISTS (SELECT 1 FROM cehub_project.risks r
   WHERE r.tenant_id=NEW.tenant_id AND r.project_id=NEW.project_id
   AND r.id=(item->>'risk_id')::uuid AND r.draft_state='confirmed'
   AND r.origin_key=item->>'origin_key'
   AND r.updated_at=(item->>'updated_at')::timestamptz) THEN
   RAISE EXCEPTION 'Receipt must reference actual rule risk confirmation';
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_project.guard_risk_candidate_batch() FROM PUBLIC;
CREATE TRIGGER guard_risk_candidate_batch BEFORE INSERT OR UPDATE OR DELETE
ON cehub_project.risk_candidate_batches FOR EACH ROW
EXECUTE FUNCTION cehub_project.guard_risk_candidate_batch();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_project.risk_candidate_batches) THEN
      RAISE EXCEPTION 'Risk confirmation receipts must be retained';
    END IF;
    END $$;
    DROP TABLE cehub_project.risk_candidate_batches;
    DROP FUNCTION cehub_project.guard_risk_candidate_batch();
    """)
