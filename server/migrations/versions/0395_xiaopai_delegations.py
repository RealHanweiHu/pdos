"""Project-shared conversations and durable Xiaopai follow-up state."""

# ruff: noqa: E501
from alembic import op

revision = "0395_xiaopai_delegations"
down_revision = "0394_ai_issue_event_receipts"
branch_labels = None
depends_on = None

DDL = """ALTER TABLE cehub_ai.conversations ADD COLUMN visibility varchar(16) NOT NULL DEFAULT 'private';
ALTER TABLE cehub_ai.conversations ADD CONSTRAINT ck_conversations_visibility CHECK(visibility IN ('private','project'));

CREATE TABLE cehub_ai.xiaopai_delegations (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	created_by_user_id UUID NOT NULL, 
	conversation_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	goal TEXT NOT NULL, 
	status VARCHAR(16) DEFAULT 'active' NOT NULL, 
	calendar JSONB NOT NULL, 
	digest_hour INTEGER DEFAULT 9 NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	checked_at TIMESTAMP WITH TIME ZONE, 
	result JSONB DEFAULT '{}'::jsonb NOT NULL, 
	version INTEGER DEFAULT 1 NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_xiaopai_delegations PRIMARY KEY (id), 
	CONSTRAINT uq_xiaopai_delegation_scope UNIQUE (tenant_id, project_id, id), 
	CONSTRAINT uq_xiaopai_delegation_request UNIQUE (tenant_id, created_by_user_id, request_id), 
	CONSTRAINT fk_xiaopai_delegations_tenant_id_conversations FOREIGN KEY(tenant_id, project_id, conversation_id) REFERENCES cehub_ai.conversations (tenant_id, project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_xiaopai_delegations_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_xiaopai_delegations_status CHECK (status IN ('active','paused','stopped','completed','blocked')), 
	CONSTRAINT ck_xiaopai_delegations_bounds CHECK (char_length(btrim(goal)) BETWEEN 1 AND 2000 AND version>0 AND digest_hour BETWEEN 0 AND 23)
)

;

CREATE TABLE cehub_ai.xiaopai_followups (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	delegation_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	recipient_user_id UUID NOT NULL, 
	source_digest VARCHAR(64) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	requested_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	delivered_at TIMESTAMP WITH TIME ZONE, 
	reply_due_at TIMESTAMP WITH TIME ZONE, 
	checkpoint_at TIMESTAMP WITH TIME ZONE, 
	reply TEXT, 
	reply_request_id UUID, 
	replied_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_xiaopai_followups PRIMARY KEY (id), 
	CONSTRAINT uq_xiaopai_followup_scope UNIQUE (tenant_id, project_id, id), 
	CONSTRAINT uq_xiaopai_followup_source UNIQUE (delegation_id, task_id, source_digest), 
	CONSTRAINT fk_xiaopai_followups_tenant_id_xiaopai_delegations FOREIGN KEY(tenant_id, project_id, delegation_id) REFERENCES cehub_ai.xiaopai_delegations (tenant_id, project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_xiaopai_followups_tenant_id_tasks FOREIGN KEY(tenant_id, project_id, task_id) REFERENCES cehub_project.tasks (tenant_id, project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_xiaopai_followups_tenant_id_users FOREIGN KEY(tenant_id, recipient_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_xiaopai_followups_status CHECK (status IN ('pending','waiting_reply','waiting_progress','no_reply','no_progress','resolved','cancelled','blocked')), 
	CONSTRAINT ck_xiaopai_followups_digest CHECK (source_digest ~ '^[a-f0-9]{64}$')
)

;

CREATE TABLE cehub_ai.xiaopai_receipts (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	delegation_id UUID NOT NULL, 
	kind VARCHAR(24) NOT NULL, 
	request_key VARCHAR(160) NOT NULL, 
	content JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_xiaopai_receipts PRIMARY KEY (id), 
	CONSTRAINT uq_xiaopai_receipt_request UNIQUE (delegation_id, request_key), 
	CONSTRAINT fk_xiaopai_receipts_tenant_id_xiaopai_delegations FOREIGN KEY(tenant_id, project_id, delegation_id) REFERENCES cehub_ai.xiaopai_delegations (tenant_id, project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_xiaopai_receipts_kind CHECK (kind IN ('created','state','reply','daily_digest','observation'))
)

;"""
GUARDS = """CREATE FUNCTION cehub_ai.conversation_actor_allowed(t uuid,p uuid,creator uuid,visibility text,actor uuid) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM cehub_core.users u WHERE u.tenant_id=t AND u.id=actor AND u.is_active
 AND u.role NOT IN ('supplier','customer') AND (visibility='private' AND creator=actor OR visibility='project' AND
 (u.role IN ('owner','admin') OR EXISTS(SELECT 1 FROM cehub_project.project_members m WHERE m.tenant_id=t AND m.project_id=p AND m.user_id=actor))))
$$;
REVOKE ALL ON FUNCTION cehub_ai.conversation_actor_allowed(uuid,uuid,uuid,text,uuid) FROM PUBLIC;
CREATE OR REPLACE FUNCTION cehub_ai.guard_private_conversation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Conversations use archive without erasing evidence' USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' AND (NEW.tenant_id<>OLD.tenant_id OR NEW.id<>OLD.id
  OR NEW.project_id<>OLD.project_id OR NEW.created_by_user_id<>OLD.created_by_user_id
  OR NEW.meeting_id IS DISTINCT FROM OLD.meeting_id OR NEW.title<>OLD.title OR NEW.visibility<>OLD.visibility
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
CREATE OR REPLACE FUNCTION cehub_ai.guard_conversation_message() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE c cehub_ai.conversations%ROWTYPE;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Conversation messages are immutable; corrections append new messages'
   USING ERRCODE='23514';
 END IF;
 SELECT * INTO c FROM cehub_ai.conversations WHERE id=NEW.conversation_id
  AND tenant_id=NEW.tenant_id AND project_id=NEW.project_id FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.conversation_actor_allowed(c.tenant_id,c.project_id,c.created_by_user_id,c.visibility,NEW.author_user_id) OR c.context_version<>NEW.context_version
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

CREATE OR REPLACE FUNCTION cehub_ai.guard_conversation_attachment() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE c cehub_ai.conversations%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Private source evidence uses revocation' USING ERRCODE='23514';
 END IF;
 SELECT * INTO c FROM cehub_ai.conversations WHERE tenant_id=NEW.tenant_id
  AND id=NEW.conversation_id AND project_id=NEW.project_id FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.conversation_actor_allowed(c.tenant_id,c.project_id,c.created_by_user_id,c.visibility,NEW.uploaded_by_user_id) THEN
  RAISE EXCEPTION 'Attachment must belong to its private creator' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' THEN
  IF c.archived_at IS NOT NULL OR NEW.status<>'awaiting_upload'
   OR NEW.revoked_at IS NOT NULL
   OR NEW.parser_version NOT IN ('conversation-pdf-xlsx.v1','conversation-eml.v1')
   OR NEW.extraction_metadata<>'{}'::jsonb
   OR ((NEW.parser_version='conversation-eml.v1')
       IS DISTINCT FROM (NEW.media_type='message/rfc822')) THEN
   RAISE EXCEPTION 'New attachment must await upload in an active conversation'
    USING ERRCODE='23514';
  END IF;
 ELSE
  IF (to_jsonb(NEW)-ARRAY['status','error_code','fragments',
     'extraction_metadata','updated_at','revoked_at'])
   IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['status','error_code','fragments',
     'extraction_metadata','updated_at','revoked_at'])
   OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at)
   OR (OLD.status IN ('extracted','ocr_required') AND
    (NEW.status<>OLD.status OR NEW.fragments<>OLD.fragments
     OR NEW.extraction_metadata<>OLD.extraction_metadata
     OR NEW.error_code IS DISTINCT FROM OLD.error_code))
   OR (OLD.status='awaiting_upload' AND (NEW.status NOT IN ('awaiting_upload','uploaded')
    OR NEW.extraction_metadata<>'{}'::jsonb))
   OR (OLD.status IN ('uploaded','failed') AND
    NEW.status NOT IN ('uploaded','failed','extracted','ocr_required'))
   OR ((c.archived_at IS NOT NULL OR OLD.revoked_at IS NOT NULL) AND
    (NEW.status<>OLD.status OR NEW.fragments<>OLD.fragments
     OR NEW.extraction_metadata<>OLD.extraction_metadata)) THEN
   RAISE EXCEPTION 'Attachment content, scope and completed extraction are immutable'
    USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER immutable_xiaopai_receipts BEFORE UPDATE OR DELETE ON cehub_ai.xiaopai_receipts FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.xiaopai_delegations,cehub_ai.xiaopai_followups,cehub_ai.xiaopai_receipts FROM PUBLIC;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN REVOKE ALL ON cehub_ai.xiaopai_delegations,cehub_ai.xiaopai_followups,cehub_ai.xiaopai_receipts FROM pdos_agent; END IF; END $$;
"""
OLD_GUARDS = """CREATE OR REPLACE FUNCTION cehub_ai.guard_private_conversation() RETURNS trigger
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
CREATE OR REPLACE FUNCTION cehub_ai.guard_conversation_message() RETURNS trigger
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

CREATE OR REPLACE FUNCTION cehub_ai.guard_conversation_attachment() RETURNS trigger
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
   OR NEW.revoked_at IS NOT NULL
   OR NEW.parser_version NOT IN ('conversation-pdf-xlsx.v1','conversation-eml.v1')
   OR NEW.extraction_metadata<>'{}'::jsonb
   OR ((NEW.parser_version='conversation-eml.v1')
       IS DISTINCT FROM (NEW.media_type='message/rfc822')) THEN
   RAISE EXCEPTION 'New attachment must await upload in an active conversation'
    USING ERRCODE='23514';
  END IF;
 ELSE
  IF (to_jsonb(NEW)-ARRAY['status','error_code','fragments',
     'extraction_metadata','updated_at','revoked_at'])
   IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['status','error_code','fragments',
     'extraction_metadata','updated_at','revoked_at'])
   OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at)
   OR (OLD.status IN ('extracted','ocr_required') AND
    (NEW.status<>OLD.status OR NEW.fragments<>OLD.fragments
     OR NEW.extraction_metadata<>OLD.extraction_metadata
     OR NEW.error_code IS DISTINCT FROM OLD.error_code))
   OR (OLD.status='awaiting_upload' AND (NEW.status NOT IN ('awaiting_upload','uploaded')
    OR NEW.extraction_metadata<>'{}'::jsonb))
   OR (OLD.status IN ('uploaded','failed') AND
    NEW.status NOT IN ('uploaded','failed','extracted','ocr_required'))
   OR ((c.archived_at IS NOT NULL OR OLD.revoked_at IS NOT NULL) AND
    (NEW.status<>OLD.status OR NEW.fragments<>OLD.fragments
     OR NEW.extraction_metadata<>OLD.extraction_metadata)) THEN
   RAISE EXCEPTION 'Attachment content, scope and completed extraction are immutable'
    USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.xiaopai_delegations) OR EXISTS(SELECT 1 FROM cehub_ai.conversations WHERE visibility='project') THEN RAISE EXCEPTION 'Retain Xiaopai shared history'; END IF; END $$;"
    )
    op.execute(
        "DROP TABLE cehub_ai.xiaopai_receipts,cehub_ai.xiaopai_followups,cehub_ai.xiaopai_delegations"
    )
    op.execute(OLD_GUARDS)
    op.execute("DROP FUNCTION cehub_ai.conversation_actor_allowed(uuid,uuid,uuid,text,uuid)")
    op.execute("ALTER TABLE cehub_ai.conversations DROP COLUMN visibility")
