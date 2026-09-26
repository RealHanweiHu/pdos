"""Atomic source-association correction batches with immutable per-row receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0239_issue_correction_batches"
down_revision = "0238_issue_compensation_results"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_project.issue_intake_correction_batches (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	reason TEXT NOT NULL, 
	results JSONB NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_issue_intake_correction_batches PRIMARY KEY (id), 
	CONSTRAINT uq_issue_correction_batch_request UNIQUE (tenant_id, project_id, request_id), 
        CONSTRAINT fk_issue_intake_correction_batches_tenant_id_projects FOREIGN KEY(tenant_id,
        project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_issue_intake_correction_batches_tenant_id_users FOREIGN KEY(tenant_id,
        created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_issue_intake_correction_batches_request CHECK (request_digest ~
        '^[0-9a-f]{64}$' AND btrim(reason)<>''),
        CONSTRAINT ck_issue_intake_correction_batches_results CHECK
        (jsonb_typeof(results)='array' AND jsonb_array_length(results) BETWEEN 1 AND 50)
)

"""


def upgrade() -> None:
    op.execute(DDL)
    op.create_index(
        "ix_issue_correction_batch_history",
        "issue_intake_correction_batches",
        ["tenant_id", "project_id", "created_at", "id"],
        schema="cehub_project",
    )
    op.create_index(
        "ix_issue_correction_batch_sources",
        "issue_intake_correction_batches",
        ["results"],
        schema="cehub_project",
        postgresql_using="gin",
    )
    op.execute("""
        CREATE FUNCTION cehub_project.guard_issue_correction_batch() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE item jsonb; seen uuid[] := ARRAY[]::uuid[]; source_id uuid;
        BEGIN
          IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Source correction batches are immutable'; END IF;
          FOR item IN SELECT value FROM jsonb_array_elements(NEW.results) LOOP
            source_id := (item->>'source_row_id')::uuid;
            IF source_id IS NULL OR source_id=ANY(seen) THEN
              RAISE EXCEPTION 'Batch source identities must be distinct'; END IF;
            seen := array_append(seen,source_id);
            IF NOT EXISTS(SELECT 1 FROM cehub_project.issue_intake_corrections c
                WHERE c.tenant_id=NEW.tenant_id AND c.project_id=NEW.project_id
                  AND c.source_row_id=source_id AND c.id=(item->>'correction_id')::uuid
                  AND c.revision=(item->>'revision')::integer AND c.action=item->>'action'
                  AND c.created_by_user_id=NEW.created_by_user_id
                  AND c.previous_issue_id IS NOT DISTINCT FROM (item->>'previous_issue_id')::uuid
                  AND c.target_issue_id IS NOT DISTINCT FROM (item->>'target_issue_id')::uuid) THEN
              RAISE EXCEPTION 'Batch must reference actual scoped source correction receipts';
            END IF;
          END LOOP;
          RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION cehub_project.guard_issue_correction_batch() FROM PUBLIC;
        CREATE TRIGGER guard_issue_correction_batch BEFORE INSERT OR UPDATE OR DELETE
          ON cehub_project.issue_intake_correction_batches FOR EACH ROW
          EXECUTE FUNCTION cehub_project.guard_issue_correction_batch();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.issue_intake_correction_batches)")
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard named source correction batch receipts")
    op.drop_table("issue_intake_correction_batches", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_issue_correction_batch()")
