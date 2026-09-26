"""Keep private Issue-list mappings, source identities and original row previews."""

import sqlalchemy as sa
from alembic import op

revision = "0233_issue_intake_previews"
down_revision = "0232_template_generation_v6"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_ai.issue_intake_previews (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	conversation_id UUID NOT NULL, 
	message_id UUID NOT NULL, 
	attachment_id UUID NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	source_snapshot JSONB NOT NULL, 
	parser_version VARCHAR(64) NOT NULL, 
	permission_basis TEXT NOT NULL, 
	purpose TEXT NOT NULL, 
	mapping JSONB NOT NULL, 
	rows JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_issue_intake_previews PRIMARY KEY (id), 
	CONSTRAINT uq_issue_intake_preview_tenant UNIQUE (tenant_id, id),
    CONSTRAINT uq_issue_intake_preview_project UNIQUE (tenant_id, project_id, id), 
	CONSTRAINT uq_issue_intake_preview_request UNIQUE (tenant_id, conversation_id, request_id), 
        CONSTRAINT fk_issue_intake_previews_tenant_id_conversation_messages FOREIGN
        KEY(tenant_id, project_id, conversation_id, message_id) REFERENCES
        cehub_ai.conversation_messages (tenant_id, project_id, conversation_id, id) ON DELETE
        RESTRICT,
        CONSTRAINT fk_issue_intake_previews_tenant_id_conversation_message_cfe9 FOREIGN
        KEY(tenant_id, message_id, attachment_id) REFERENCES
        cehub_ai.conversation_message_attachments (tenant_id, message_id, attachment_id) ON
        DELETE RESTRICT,
        CONSTRAINT fk_issue_intake_previews_tenant_id_users FOREIGN KEY(tenant_id,
        created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_issue_intake_previews_digest_valid CHECK (request_digest ~ '^[0-9a-f]{64}$'), 
        CONSTRAINT ck_issue_intake_previews_preview_shape CHECK
        (jsonb_typeof(source_snapshot)='object' AND jsonb_typeof(mapping)='object' AND
        jsonb_typeof(rows)='array' AND jsonb_array_length(rows) BETWEEN 1 AND 200),
        CONSTRAINT ck_issue_intake_previews_purpose_and_parser CHECK
        (btrim(permission_basis)<>'' AND btrim(purpose)<>'' AND
        parser_version='issue-list-extracted-v1')
)

;
CREATE INDEX ix_issue_intake_message ON cehub_ai.issue_intake_previews (tenant_id,
        conversation_id, message_id, created_at);
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute("""
      CREATE FUNCTION cehub_ai.guard_issue_intake_preview() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog AS $$
      BEGIN RAISE EXCEPTION 'Issue intake preview is immutable'; END $$;
      REVOKE ALL ON FUNCTION cehub_ai.guard_issue_intake_preview() FROM PUBLIC;
      CREATE TRIGGER guard_issue_intake_preview BEFORE UPDATE OR DELETE
        ON cehub_ai.issue_intake_previews FOR EACH ROW
        EXECUTE FUNCTION cehub_ai.guard_issue_intake_preview();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_ai.issue_intake_previews)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard historical Issue intake evidence")
    op.drop_table("issue_intake_previews", schema="cehub_ai")
    op.execute("DROP FUNCTION cehub_ai.guard_issue_intake_preview()")
