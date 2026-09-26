"""Store confirmed original Issue rows and private batch receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0234_issue_intake_confirm"
down_revision = "0233_issue_intake_previews"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE cehub_ai.issue_intake_batches (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	preview_id UUID NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	results JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_issue_intake_batches PRIMARY KEY (id), 
	CONSTRAINT uq_issue_intake_batch_request UNIQUE (tenant_id, preview_id, request_id), 
        CONSTRAINT fk_issue_intake_batches_tenant_id_issue_intake_previews FOREIGN
        KEY(tenant_id, project_id, preview_id) REFERENCES cehub_ai.issue_intake_previews
        (tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_issue_intake_batches_tenant_id_users FOREIGN KEY(tenant_id,
        created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_issue_intake_batches_digest CHECK (request_digest ~ '^[0-9a-f]{64}$'), 
        CONSTRAINT ck_issue_intake_batches_results CHECK (jsonb_typeof(results)='array' AND
        jsonb_array_length(results) BETWEEN 1 AND 200)
)

;

CREATE TABLE cehub_project.issue_intake_rows (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	preview_id UUID NOT NULL, 
	issue_id UUID NOT NULL, 
	document_id UUID NOT NULL, 
	source_sha256 VARCHAR(64) NOT NULL, 
	locator TEXT NOT NULL, 
	input_digest VARCHAR(64) NOT NULL, 
	source_snapshot JSONB NOT NULL, 
	created_snapshot JSONB NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_issue_intake_rows PRIMARY KEY (id), 
        CONSTRAINT uq_issue_intake_original_row UNIQUE (tenant_id, project_id, source_sha256,
        locator),
        CONSTRAINT fk_issue_intake_rows_tenant_id_issue_intake_previews FOREIGN KEY(tenant_id,
        project_id, preview_id) REFERENCES cehub_ai.issue_intake_previews (tenant_id,
        project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_issue_intake_rows_tenant_id_issues FOREIGN KEY(tenant_id, project_id,
        issue_id) REFERENCES cehub_project.issues (tenant_id, project_id, id) ON DELETE
        RESTRICT,
        CONSTRAINT fk_issue_intake_rows_tenant_id_documents FOREIGN KEY(tenant_id, project_id,
        document_id) REFERENCES cehub_project.documents (tenant_id, project_id, id) ON DELETE
        RESTRICT,
        CONSTRAINT fk_issue_intake_rows_tenant_id_users FOREIGN KEY(tenant_id,
        created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_issue_intake_rows_digests CHECK (source_sha256 ~ '^[0-9a-f]{64}$' AND
        input_digest ~ '^[0-9a-f]{64}$'),
        CONSTRAINT ck_issue_intake_rows_snapshots CHECK (jsonb_typeof(source_snapshot)='object'
        AND jsonb_typeof(created_snapshot)='object'),
	CONSTRAINT ck_issue_intake_rows_locator CHECK (btrim(locator)<>'')
)

;
CREATE INDEX ix_issue_intake_issue ON cehub_project.issue_intake_rows (tenant_id, project_id,
        issue_id);
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute("""
        CREATE FUNCTION cehub_ai.guard_issue_intake_confirmation() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN RAISE EXCEPTION 'Issue intake confirmation is immutable'; END $$;
        REVOKE ALL ON FUNCTION cehub_ai.guard_issue_intake_confirmation() FROM PUBLIC;
        CREATE TRIGGER guard_issue_intake_confirmation BEFORE UPDATE OR DELETE
          ON cehub_ai.issue_intake_batches FOR EACH ROW
          EXECUTE FUNCTION cehub_ai.guard_issue_intake_confirmation();
        CREATE TRIGGER guard_issue_intake_confirmation BEFORE UPDATE OR DELETE
          ON cehub_project.issue_intake_rows FOR EACH ROW
          EXECUTE FUNCTION cehub_ai.guard_issue_intake_confirmation();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
        SELECT EXISTS(SELECT 1 FROM cehub_ai.issue_intake_batches)
          OR EXISTS(SELECT 1 FROM cehub_project.issue_intake_rows)
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard confirmed Issue intake history")
    op.drop_table("issue_intake_rows", schema="cehub_project")
    op.drop_table("issue_intake_batches", schema="cehub_ai")
    op.execute("DROP FUNCTION cehub_ai.guard_issue_intake_confirmation()")
