"""Private project conversations and immutable user messages.

Revision ID: 0176_private_conversations
Revises: 0175_meeting_business_findings
"""

import sqlalchemy as sa
from alembic import op

revision = "0176_private_conversations"
down_revision = "0175_meeting_business_findings"
branch_labels = None
depends_on = None

DDL = [
    """

CREATE TABLE cehub_ai.conversations (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        meeting_id UUID,
        created_by_user_id UUID NOT NULL,
        title VARCHAR(256) NOT NULL,
        context_version INTEGER NOT NULL,
        next_sequence INTEGER NOT NULL,
        archived_at TIMESTAMP WITH TIME ZONE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT pk_conversations PRIMARY KEY (id),
        CONSTRAINT uq_conversation_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT fk_conversations_tenant_id_projects FOREIGN KEY(tenant_id, project_id)
REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_conversations_tenant_id_meetings FOREIGN KEY(tenant_id, meeting_id)
REFERENCES cehub_project.meetings (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_conversations_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_conversations_version_sequence CHECK (context_version=1 AND
next_sequence>0)
)

""",
    """
CREATE INDEX ix_conversation_owner_project ON cehub_ai.conversations (tenant_id,
created_by_user_id, project_id, updated_at)
""",
    """

CREATE TABLE cehub_ai.conversation_messages (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        conversation_id UUID NOT NULL,
        author_user_id UUID NOT NULL,
        sequence INTEGER NOT NULL,
        context_version INTEGER NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        body TEXT NOT NULL,
        action VARCHAR(32) NOT NULL,
        transcript_id UUID,
        expected_digest VARCHAR(64),
        expected_minutes_version INTEGER,
        dispatch_input TEXT NOT NULL,
        operation_request_id VARCHAR(128) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT pk_conversation_messages PRIMARY KEY (id),
        CONSTRAINT uq_conversation_sequence UNIQUE (tenant_id, conversation_id, sequence),
        CONSTRAINT uq_conversation_message_request UNIQUE (tenant_id, conversation_id,
request_id),
        CONSTRAINT uq_conversation_operation_request UNIQUE (tenant_id, operation_request_id),
        CONSTRAINT fk_conversation_messages_tenant_id_conversations FOREIGN KEY(tenant_id,
project_id, conversation_id) REFERENCES cehub_ai.conversations (tenant_id, project_id, id) ON
DELETE RESTRICT,
        CONSTRAINT fk_conversation_messages_tenant_id_users FOREIGN KEY(tenant_id,
author_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_conversation_messages_tenant_id_meeting_transcripts FOREIGN
KEY(tenant_id, transcript_id) REFERENCES cehub_project.meeting_transcripts (tenant_id, id) ON
DELETE RESTRICT,
        CONSTRAINT ck_conversation_messages_content_bound CHECK (context_version=1 AND
sequence>0 AND length(btrim(body)) BETWEEN 1 AND 2000 AND length(dispatch_input)<=20000),
        CONSTRAINT ck_conversation_messages_action_allowed CHECK (action IN
('note','project_query','meeting_reading','minutes','actions','decisions','business')),
        CONSTRAINT ck_conversation_messages_request_digest CHECK (request_digest ~
'^[0-9a-f]{64}$'),
        CONSTRAINT ck_conversation_messages_action_source CHECK ((action IN
('note','project_query') AND transcript_id IS NULL AND expected_digest IS NULL AND
expected_minutes_version IS NULL) OR (action NOT IN ('note','project_query') AND transcript_id
IS NOT NULL AND expected_digest IS NOT NULL AND expected_digest ~ '^[0-9a-f]{64}$'
AND ((action='minutes' AND expected_minutes_version IS NOT NULL AND
expected_minutes_version>=0) OR (action<>'minutes' AND expected_minutes_version IS NULL))))
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
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_ai.conversations)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to remove private conversation history")
    op.execute("""
        DROP TABLE cehub_ai.conversation_messages;
        DROP TABLE cehub_ai.conversations;
        DROP FUNCTION cehub_ai.guard_conversation_message();
        DROP FUNCTION cehub_ai.guard_private_conversation();
    """)


GUARDS = r"""
CREATE FUNCTION cehub_ai.guard_private_conversation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Conversations use archive without erasing evidence' USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' AND (NEW.tenant_id<>OLD.tenant_id OR NEW.id<>OLD.id
  OR NEW.project_id<>OLD.project_id OR NEW.created_by_user_id<>OLD.created_by_user_id
  OR NEW.meeting_id IS DISTINCT FROM OLD.meeting_id OR NEW.title<>OLD.title
  OR NEW.context_version<>OLD.context_version OR NEW.created_at<>OLD.created_at
  OR NEW.next_sequence NOT IN (OLD.next_sequence, OLD.next_sequence+1)) THEN
  RAISE EXCEPTION 'Conversation scope and creator are fixed' USING ERRCODE='23514';
 END IF;
 IF NEW.meeting_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cehub_project.meetings m
  WHERE m.tenant_id=NEW.tenant_id AND m.project_id=NEW.project_id AND m.id=NEW.meeting_id) THEN
  RAISE EXCEPTION 'Conversation meeting must belong to its project' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_private_conversation() FROM PUBLIC;
CREATE TRIGGER guard_private_conversation BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_ai.conversations
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_private_conversation();

CREATE FUNCTION cehub_ai.guard_conversation_message() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE c cehub_ai.conversations%ROWTYPE;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Conversation messages are immutable; corrections append new messages'
   USING ERRCODE='23514';
 END IF;
 SELECT * INTO c FROM cehub_ai.conversations WHERE id=NEW.conversation_id
  AND tenant_id=NEW.tenant_id AND project_id=NEW.project_id FOR UPDATE;
 IF NOT FOUND OR c.created_by_user_id<>NEW.author_user_id OR c.context_version<>NEW.context_version
  OR c.next_sequence<>NEW.sequence OR c.archived_at IS NOT NULL THEN
  RAISE EXCEPTION 'Message must match its private owner and current sequence' USING ERRCODE='23514';
 END IF;
 IF NEW.transcript_id IS NOT NULL AND (c.meeting_id IS NULL OR NOT EXISTS(
  SELECT 1 FROM cehub_project.meeting_transcripts t WHERE t.tenant_id=NEW.tenant_id
   AND t.meeting_id=c.meeting_id AND t.id=NEW.transcript_id)) THEN
  RAISE EXCEPTION 'Message transcript must belong to this conversation meeting'
   USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_conversation_message() FROM PUBLIC;
CREATE TRIGGER guard_conversation_message BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_ai.conversation_messages
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_conversation_message();
"""
