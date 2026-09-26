"""Private staged files and immutable message attachment bindings.
Revision ID: 0177_conversation_attachments
Revises: 0176_private_conversations
"""

import sqlalchemy as sa
from alembic import op

revision = "0177_conversation_attachments"
down_revision = "0176_private_conversations"
branch_labels = None
depends_on = None
DDL = [
    """
ALTER TABLE cehub_ai.conversation_messages ADD CONSTRAINT uq_conversation_message_scope UNIQUE
(tenant_id, project_id, conversation_id, id)
""",
    """

CREATE TABLE cehub_ai.conversation_attachments (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    conversation_id UUID NOT NULL,
    request_id UUID NOT NULL,
    uploaded_by_user_id UUID NOT NULL,
    filename VARCHAR(512) NOT NULL,
    media_type VARCHAR(128) NOT NULL,
    classification VARCHAR(32) NOT NULL,
    size_bytes BIGINT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    object_key VARCHAR(1024) NOT NULL,
    parser_version VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    error_code VARCHAR(64),
    fragments JSONB DEFAULT '[]'::jsonb NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_conversation_attachments PRIMARY KEY (id),
    CONSTRAINT uq_conversation_attachment_scope UNIQUE (tenant_id, project_id, conversation_id,
id),
    CONSTRAINT uq_conversation_attachment_request UNIQUE (tenant_id, conversation_id,
request_id),
    CONSTRAINT uq_conversation_attachment_content UNIQUE (tenant_id, conversation_id, sha256,
classification, parser_version),
    CONSTRAINT fk_conversation_attachments_tenant_id_conversations FOREIGN KEY(tenant_id,
project_id, conversation_id) REFERENCES cehub_ai.conversations (tenant_id, project_id, id) ON
DELETE RESTRICT,
    CONSTRAINT fk_conversation_attachments_tenant_id_users FOREIGN KEY(tenant_id,
uploaded_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_conversation_attachments_content_identity CHECK (size_bytes BETWEEN 1 AND
20971520 AND sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_conversation_attachments_classification CHECK (classification IN
('internal','confidential','restricted')),
    CONSTRAINT ck_conversation_attachments_status CHECK (status IN
('awaiting_upload','uploaded','extracted','ocr_required','failed')),
    CONSTRAINT ck_conversation_attachments_extraction CHECK (jsonb_typeof(fragments)='array' AND
((status='extracted' AND jsonb_array_length(fragments)>0) OR (status<>'extracted' AND
fragments='[]'::jsonb)))
)

""",
    """
CREATE INDEX ix_conversation_attachment_created ON cehub_ai.conversation_attachments (tenant_id,
conversation_id, created_at)
""",
    """

CREATE TABLE cehub_ai.conversation_attachment_requests (
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    conversation_id UUID NOT NULL,
    request_id UUID NOT NULL,
    attachment_id UUID NOT NULL,
    request_digest VARCHAR(64) NOT NULL,
    CONSTRAINT pk_conversation_attachment_requests PRIMARY KEY (tenant_id, conversation_id,
request_id),
    CONSTRAINT fk_conversation_attachment_requests_tenant_id_conversat_3d9a FOREIGN
KEY(tenant_id, project_id, conversation_id, attachment_id) REFERENCES
cehub_ai.conversation_attachments (tenant_id, project_id, conversation_id, id) ON DELETE
RESTRICT,
    CONSTRAINT ck_conversation_attachment_requests_digest CHECK (request_digest ~
'^[0-9a-f]{64}$')
)

""",
    """

CREATE TABLE cehub_ai.conversation_message_attachments (
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    conversation_id UUID NOT NULL,
    message_id UUID NOT NULL,
    attachment_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    CONSTRAINT pk_conversation_message_attachments PRIMARY KEY (tenant_id, message_id,
attachment_id),
    CONSTRAINT uq_conversation_message_attachment_order UNIQUE (tenant_id, message_id, ordinal),
    CONSTRAINT fk_conversation_message_attachments_tenant_id_conversat_9722 FOREIGN
KEY(tenant_id, project_id, conversation_id, message_id) REFERENCES
cehub_ai.conversation_messages (tenant_id, project_id, conversation_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_conversation_message_attachments_tenant_id_conversat_9ba2 FOREIGN
KEY(tenant_id, project_id, conversation_id, attachment_id) REFERENCES
cehub_ai.conversation_attachments (tenant_id, project_id, conversation_id, id) ON DELETE
RESTRICT,
    CONSTRAINT ck_conversation_message_attachments_ordinal CHECK (ordinal BETWEEN 1 AND 6)
)

""",
]


def upgrade() -> None:
    for statement in DDL:
        op.execute(statement)
    op.execute(GUARDS)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_ai.conversation_attachments)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to remove private attachment evidence")
    op.execute("""
    DROP TABLE cehub_ai.conversation_message_attachments;
    DROP TABLE cehub_ai.conversation_attachment_requests;
    DROP TABLE cehub_ai.conversation_attachments;
    ALTER TABLE cehub_ai.conversation_messages DROP CONSTRAINT uq_conversation_message_scope;
    DROP FUNCTION cehub_ai.guard_conversation_attachment();
    DROP FUNCTION cehub_ai.guard_message_attachment();
    DROP FUNCTION cehub_ai.guard_attachment_request();
    """)


GUARDS = r"""
CREATE FUNCTION cehub_ai.guard_conversation_attachment() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE c cehub_ai.conversations%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Private source evidence uses revocation' USING ERRCODE='23514';
 END IF;
 SELECT * INTO c FROM cehub_ai.conversations WHERE tenant_id=NEW.tenant_id
  AND id=NEW.conversation_id AND project_id=NEW.project_id FOR UPDATE;
 IF NOT FOUND OR c.created_by_user_id<>NEW.uploaded_by_user_id THEN
  RAISE EXCEPTION 'Attachment must belong to its private creator' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' THEN
  IF c.archived_at IS NOT NULL OR NEW.status<>'awaiting_upload'
   OR NEW.revoked_at IS NOT NULL OR NEW.parser_version<>'conversation-pdf-xlsx.v1' THEN
   RAISE EXCEPTION 'New attachment must await upload in an active conversation'
    USING ERRCODE='23514';
  END IF;
 ELSE
  IF (to_jsonb(NEW)-ARRAY['status','error_code','fragments','updated_at','revoked_at'])
   IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['status','error_code','fragments','updated_at','revoked_at'])
   OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at)
   OR (OLD.status IN ('extracted','ocr_required') AND
    (NEW.status<>OLD.status OR NEW.fragments<>OLD.fragments
     OR NEW.error_code IS DISTINCT FROM OLD.error_code))
   OR (OLD.status='awaiting_upload' AND NEW.status NOT IN ('awaiting_upload','uploaded'))
   OR (OLD.status IN ('uploaded','failed') AND
    NEW.status NOT IN ('uploaded','failed','extracted','ocr_required'))
   OR ((c.archived_at IS NOT NULL OR OLD.revoked_at IS NOT NULL) AND
    (NEW.status<>OLD.status OR NEW.fragments<>OLD.fragments)) THEN
   RAISE EXCEPTION 'Attachment content, scope and completed extraction are immutable'
    USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_conversation_attachment() FROM PUBLIC;
CREATE TRIGGER guard_conversation_attachment BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_ai.conversation_attachments FOR EACH ROW
 EXECUTE FUNCTION cehub_ai.guard_conversation_attachment();

CREATE FUNCTION cehub_ai.guard_message_attachment() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE
 m cehub_ai.conversation_messages%ROWTYPE;
 c cehub_ai.conversations%ROWTYPE;
 a cehub_ai.conversation_attachments%ROWTYPE;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Message source bindings are immutable' USING ERRCODE='23514';
 END IF;
 SELECT * INTO c FROM cehub_ai.conversations WHERE tenant_id=NEW.tenant_id
  AND project_id=NEW.project_id AND id=NEW.conversation_id FOR UPDATE;
 SELECT * INTO m FROM cehub_ai.conversation_messages WHERE tenant_id=NEW.tenant_id
  AND conversation_id=NEW.conversation_id AND id=NEW.message_id;
 SELECT * INTO a FROM cehub_ai.conversation_attachments WHERE tenant_id=NEW.tenant_id
  AND conversation_id=NEW.conversation_id AND id=NEW.attachment_id;
 IF m.id IS NULL OR a.id IS NULL OR c.id IS NULL OR c.archived_at IS NOT NULL
  OR c.next_sequence<>m.sequence OR a.revoked_at IS NOT NULL
  OR m.action NOT IN ('note','project_query')
  OR (m.action='project_query' AND (a.classification<>'internal' OR a.status<>'extracted')) THEN
  RAISE EXCEPTION 'Message requires currently usable sources in its original submission'
   USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_message_attachment() FROM PUBLIC;
CREATE TRIGGER guard_message_attachment BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_ai.conversation_message_attachments FOR EACH ROW
 EXECUTE FUNCTION cehub_ai.guard_message_attachment();

CREATE FUNCTION cehub_ai.guard_attachment_request() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 RAISE EXCEPTION 'Upload request receipts are immutable' USING ERRCODE='23514';
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_attachment_request() FROM PUBLIC;
CREATE TRIGGER guard_attachment_request BEFORE UPDATE OR DELETE
 ON cehub_ai.conversation_attachment_requests FOR EACH ROW
 EXECUTE FUNCTION cehub_ai.guard_attachment_request();
"""
