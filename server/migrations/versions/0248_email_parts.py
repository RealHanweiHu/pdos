"""Private independently saved email attachments with immutable MIME provenance."""

from alembic import op

revision = "0248_email_parts"
down_revision = "0247_project_intake"
branch_labels = None
depends_on = None

DDL = r"""

CREATE TABLE cehub_ai.conversation_email_parts (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        conversation_id UUID NOT NULL,
        parent_attachment_id UUID NOT NULL,
        attachment_id UUID NOT NULL,
        created_by_user_id UUID NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        parent_sha256 VARCHAR(64) NOT NULL,
        part_path VARCHAR(128) NOT NULL,
        parser_version VARCHAR(64) NOT NULL,
        part_snapshot JSONB NOT NULL,
        permission_basis TEXT NOT NULL,
        purpose TEXT NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT pk_conversation_email_parts PRIMARY KEY (id),
        CONSTRAINT uq_conversation_email_part_request UNIQUE (tenant_id, conversation_id,
request_id),
        CONSTRAINT fk_email_part_parent_attachment_id FOREIGN KEY(tenant_id, project_id,
conversation_id, parent_attachment_id) REFERENCES cehub_ai.conversation_attachments (tenant_id,
project_id, conversation_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_email_part_attachment_id FOREIGN KEY(tenant_id, project_id, conversation_id,
 attachment_id) REFERENCES cehub_ai.conversation_attachments (tenant_id, project_id,
conversation_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_conversation_email_parts_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_conversation_email_parts_identity CHECK (parent_attachment_id<>attachment_id
 AND request_digest ~ '^[0-9a-f]{64}$' AND parent_sha256 ~ '^[0-9a-f]{64}$' AND part_path ~
'^1(\.[1-9][0-9]*)*$' AND parser_version='email-attachments.v1'),
        CONSTRAINT ck_conversation_email_parts_shape CHECK (jsonb_typeof(part_snapshot)='object'
AND length(btrim(permission_basis)) BETWEEN 1 AND 2000 AND length(btrim(purpose)) BETWEEN 1 AND
2000)
)

;
CREATE INDEX ix_email_part_child ON cehub_ai.conversation_email_parts (tenant_id, conversation_id,
 attachment_id, id);
CREATE INDEX ix_email_part_parent ON cehub_ai.conversation_email_parts (tenant_id,
conversation_id, parent_attachment_id, id);
"""

GUARD = """
CREATE FUNCTION cehub_ai.guard_conversation_email_part() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE parent cehub_ai.conversation_attachments; child cehub_ai.conversation_attachments;
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'Email attachment provenance is immutable' USING ERRCODE='23514';
 END IF;
 PERFORM 1 FROM cehub_ai.conversations WHERE tenant_id=NEW.tenant_id
  AND project_id=NEW.project_id AND id=NEW.conversation_id FOR UPDATE;
 SELECT * INTO parent FROM cehub_ai.conversation_attachments WHERE tenant_id=NEW.tenant_id
  AND project_id=NEW.project_id AND conversation_id=NEW.conversation_id
  AND id=NEW.parent_attachment_id;
 SELECT * INTO child FROM cehub_ai.conversation_attachments WHERE tenant_id=NEW.tenant_id
  AND project_id=NEW.project_id AND conversation_id=NEW.conversation_id AND id=NEW.attachment_id;
 IF parent.id IS NULL OR child.id IS NULL OR parent.media_type<>'message/rfc822'
  OR parent.revoked_at IS NOT NULL OR child.revoked_at IS NOT NULL
  OR parent.status='awaiting_upload' OR parent.sha256<>NEW.parent_sha256
  OR parent.uploaded_by_user_id<>NEW.created_by_user_id
  OR child.uploaded_by_user_id<>NEW.created_by_user_id
  OR NOT ((NEW.part_snapshot->>'path'=NEW.part_path
   AND NEW.part_snapshot->>'sha256'=child.sha256
   AND (NEW.part_snapshot->>'size_bytes')::bigint=child.size_bytes
   AND NEW.part_snapshot->>'status'='available'
   AND NEW.part_snapshot->>'media_type'=child.media_type) IS TRUE)
  OR (CASE parent.classification WHEN 'internal' THEN 0 WHEN 'confidential' THEN 1 ELSE 2 END)
   > (CASE child.classification WHEN 'internal' THEN 0 WHEN 'confidential' THEN 1 ELSE 2 END)
 THEN RAISE EXCEPTION 'Email attachment source differs' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_conversation_email_part() FROM PUBLIC;
CREATE TRIGGER guard_conversation_email_part BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_ai.conversation_email_parts FOR EACH ROW
 EXECUTE FUNCTION cehub_ai.guard_conversation_email_part();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_ai.conversation_email_parts) THEN
     RAISE EXCEPTION 'Email attachment source history must be retained'; END IF;
    END $$""")
    op.execute("DROP TABLE cehub_ai.conversation_email_parts")
    op.execute("DROP FUNCTION cehub_ai.guard_conversation_email_part()")
