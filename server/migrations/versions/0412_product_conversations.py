"""Typed private product conversations while preserving project conversation history."""

# ruff: noqa: E501
from alembic import op

revision = "0412_product_conversations"
down_revision = "0411_plan_lineage_aliases"
branch_labels = None
depends_on = None

DDL = r"""ALTER TABLE cehub_ai.conversations ADD COLUMN scope_kind varchar(32) NOT NULL DEFAULT 'project', ADD COLUMN market_space_id uuid, ADD COLUMN product_line_id uuid;
ALTER TABLE cehub_ai.conversations ALTER COLUMN project_id DROP NOT NULL;
ALTER TABLE cehub_ai.conversation_messages ALTER COLUMN project_id DROP NOT NULL;
ALTER TABLE cehub_ai.conversation_attachments ALTER COLUMN project_id DROP NOT NULL;
ALTER TABLE cehub_ai.conversation_attachment_requests ALTER COLUMN project_id DROP NOT NULL;
ALTER TABLE cehub_ai.conversation_message_attachments ALTER COLUMN project_id DROP NOT NULL;
ALTER TABLE cehub_ai.conversations ADD CONSTRAINT uq_conversation_typed_scope UNIQUE(tenant_id,id), ADD CONSTRAINT fk_conversations_market_space FOREIGN KEY(tenant_id,market_space_id) REFERENCES cehub_product.market_spaces(tenant_id,id) ON DELETE RESTRICT, ADD CONSTRAINT fk_conversations_product_line FOREIGN KEY(tenant_id,market_space_id,product_line_id) REFERENCES cehub_product.product_nodes(tenant_id,market_space_id,id) ON DELETE RESTRICT, ADD CONSTRAINT ck_conversations_typed_scope CHECK(((scope_kind='project' AND project_id IS NOT NULL AND market_space_id IS NULL AND product_line_id IS NULL) OR (scope_kind='personal' AND project_id IS NULL AND market_space_id IS NULL AND product_line_id IS NULL AND meeting_id IS NULL AND visibility='private') OR (scope_kind='market_space' AND project_id IS NULL AND market_space_id IS NOT NULL AND product_line_id IS NULL AND meeting_id IS NULL AND visibility='private') OR (scope_kind='product_line' AND project_id IS NULL AND market_space_id IS NOT NULL AND product_line_id IS NOT NULL AND meeting_id IS NULL AND visibility='private')) IS TRUE);
ALTER TABLE cehub_ai.conversation_messages ADD CONSTRAINT uq_conversation_message_typed_scope UNIQUE(tenant_id,conversation_id,id);
ALTER TABLE cehub_ai.conversation_attachments ADD CONSTRAINT uq_conversation_attachment_typed_scope UNIQUE(tenant_id,conversation_id,id);
ALTER TABLE cehub_ai.conversation_messages ADD CONSTRAINT fk_conversation_messages_typed_conversation FOREIGN KEY(tenant_id,conversation_id) REFERENCES cehub_ai.conversations(tenant_id,id) ON DELETE RESTRICT;
ALTER TABLE cehub_ai.conversation_attachments ADD CONSTRAINT fk_conversation_attachments_typed_conversation FOREIGN KEY(tenant_id,conversation_id) REFERENCES cehub_ai.conversations(tenant_id,id) ON DELETE RESTRICT;
ALTER TABLE cehub_ai.conversation_attachment_requests ADD CONSTRAINT fk_conversation_attachment_requests_typed_attachment FOREIGN KEY(tenant_id,conversation_id,attachment_id) REFERENCES cehub_ai.conversation_attachments(tenant_id,conversation_id,id) ON DELETE RESTRICT;
ALTER TABLE cehub_ai.conversation_message_attachments ADD CONSTRAINT fk_conversation_message_attachments_typed_message FOREIGN KEY(tenant_id,conversation_id,message_id) REFERENCES cehub_ai.conversation_messages(tenant_id,conversation_id,id) ON DELETE RESTRICT;
ALTER TABLE cehub_ai.conversation_message_attachments ADD CONSTRAINT fk_conversation_message_attachments_typed_attachment FOREIGN KEY(tenant_id,conversation_id,attachment_id) REFERENCES cehub_ai.conversation_attachments(tenant_id,conversation_id,id) ON DELETE RESTRICT;
ALTER TABLE cehub_ai.conversation_messages ADD COLUMN product_work_request jsonb, DROP CONSTRAINT ck_conversation_messages_action_allowed, DROP CONSTRAINT ck_conversation_messages_action_source, ADD CONSTRAINT ck_conversation_messages_action_allowed CHECK(action IN ('note','project_query','meeting_reading','minutes','actions','decisions','business','change_work_package','quality_work_package','meeting_planning','product_work')), ADD CONSTRAINT ck_conversation_messages_action_source CHECK((action IN ('note','project_query','product_work') AND transcript_id IS NULL AND expected_digest IS NULL AND expected_minutes_version IS NULL) OR (action NOT IN ('note','project_query','change_work_package','quality_work_package','meeting_planning','product_work') AND transcript_id IS NOT NULL AND expected_digest IS NOT NULL AND expected_digest ~ '^[0-9a-f]{64}$' AND ((action='minutes' AND expected_minutes_version IS NOT NULL AND expected_minutes_version>=0) OR (action<>'minutes' AND expected_minutes_version IS NULL))) OR (action IN ('change_work_package','quality_work_package','meeting_planning') AND transcript_id IS NULL AND expected_minutes_version IS NULL AND expected_digest IS NOT NULL AND expected_digest ~ '^[0-9a-f]{64}$')), ADD CONSTRAINT ck_conversation_messages_product_request CHECK(((action='product_work' AND project_id IS NULL AND product_work_request IS NOT NULL AND jsonb_typeof(product_work_request)='object' AND jsonb_typeof(product_work_request->'selection')='object' AND product_work_request->>'expected_digest' ~ '^[0-9a-f]{64}$' AND jsonb_typeof(product_work_request->'user_instruction')='string') OR (action<>'product_work' AND product_work_request IS NULL)) IS TRUE AND (project_id IS NOT NULL OR (action IN ('note','product_work') AND object_focus IS NULL)));
"""

AUTHORIZATION = r"""CREATE FUNCTION cehub_ai.require_product_conversation_actor(t uuid,s uuid,l uuid,actor uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM cehub_core.users u WHERE u.tenant_id=t AND u.id=actor AND u.is_active AND u.role IN ('owner','admin','project_manager','engineer','quality') AND
 (u.role IN ('owner','admin') OR EXISTS(SELECT 1 FROM cehub_product.market_space_members sm WHERE sm.tenant_id=t AND sm.market_space_id=s AND sm.user_id=actor)) AND
 (l IS NULL OR u.role IN ('owner','admin') OR EXISTS(SELECT 1 FROM cehub_product.product_line_members lm WHERE lm.tenant_id=t AND lm.market_space_id=s AND lm.product_line_id=l AND lm.user_id=actor)))
$$;
REVOKE ALL ON FUNCTION cehub_ai.require_product_conversation_actor(uuid,uuid,uuid,uuid) FROM PUBLIC;
"""

GUARDS = r"""CREATE OR REPLACE FUNCTION cehub_ai.guard_private_conversation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Conversations use archive without erasing evidence' USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' AND (NEW.tenant_id<>OLD.tenant_id OR NEW.id<>OLD.id
  OR NEW.project_id IS DISTINCT FROM OLD.project_id OR NEW.created_by_user_id<>OLD.created_by_user_id
  OR NEW.meeting_id IS DISTINCT FROM OLD.meeting_id OR NEW.title<>OLD.title OR NEW.visibility<>OLD.visibility
  OR NEW.context_version<>OLD.context_version OR NEW.created_at<>OLD.created_at
  OR NEW.next_sequence NOT IN (OLD.next_sequence, OLD.next_sequence+1)) THEN
  RAISE EXCEPTION 'Conversation scope and creator are fixed' USING ERRCODE='23514';
 END IF;
 IF NEW.meeting_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cehub_project.meetings m
  WHERE m.tenant_id=NEW.tenant_id AND m.project_id IS NOT DISTINCT FROM NEW.project_id AND m.id=NEW.meeting_id) THEN
  RAISE EXCEPTION 'Conversation meeting must belong to its project' USING ERRCODE='23514';
 END IF;

 IF TG_OP='UPDATE' AND (NEW.scope_kind IS DISTINCT FROM OLD.scope_kind OR NEW.market_space_id IS DISTINCT FROM OLD.market_space_id OR NEW.product_line_id IS DISTINCT FROM OLD.product_line_id) THEN
  RAISE EXCEPTION 'Typed conversation scope is immutable' USING ERRCODE='23514'; END IF;
 IF NEW.scope_kind<>'project' AND NOT cehub_ai.conversation_actor_allowed(NEW.tenant_id,NULL,NEW.created_by_user_id,'private',NEW.created_by_user_id) THEN
  RAISE EXCEPTION 'Nonproject conversation requires its active internal owner'; END IF;
 IF NEW.market_space_id IS NOT NULL AND NOT cehub_ai.require_product_conversation_actor(NEW.tenant_id,NEW.market_space_id,NEW.product_line_id,NEW.created_by_user_id) THEN RAISE EXCEPTION 'Conversation owner lacks current product scope'; END IF;
 IF NEW.product_line_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cehub_product.product_nodes n WHERE n.tenant_id=NEW.tenant_id AND n.market_space_id=NEW.market_space_id AND n.id=NEW.product_line_id AND n.level='line') THEN
  RAISE EXCEPTION 'Conversation line must be a real line in its market space'; END IF;
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
  AND tenant_id=NEW.tenant_id AND project_id IS NOT DISTINCT FROM NEW.project_id FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.conversation_actor_allowed(c.tenant_id,c.project_id,c.created_by_user_id,c.visibility,NEW.author_user_id) OR c.context_version<>NEW.context_version
  OR c.next_sequence<>NEW.sequence OR c.archived_at IS NOT NULL THEN
  RAISE EXCEPTION 'Message must match its private owner and current sequence' USING ERRCODE='23514';
 END IF;
 IF c.market_space_id IS NOT NULL AND NOT cehub_ai.require_product_conversation_actor(c.tenant_id,c.market_space_id,c.product_line_id,NEW.author_user_id) THEN RAISE EXCEPTION 'Message author lacks current product scope'; END IF;
 IF NEW.transcript_id IS NOT NULL AND (c.meeting_id IS NULL OR NOT EXISTS(
  SELECT 1 FROM cehub_project.meeting_transcripts t WHERE t.tenant_id=NEW.tenant_id
   AND t.meeting_id=c.meeting_id AND t.id=NEW.transcript_id)) THEN
  RAISE EXCEPTION 'Message transcript must belong to this conversation meeting'
   USING ERRCODE='23514';
 END IF;

 IF c.project_id IS NULL AND (NEW.action NOT IN ('note','product_work') OR NEW.object_focus IS NOT NULL) THEN
  RAISE EXCEPTION 'Nonproject messages cannot invoke project actions'; END IF;
 IF NEW.action='product_work' AND (c.scope_kind NOT IN ('market_space','product_line') OR NEW.product_work_request->'selection'->>'product_line_id' IS DISTINCT FROM c.product_line_id::text) THEN
  RAISE EXCEPTION 'Product work must retain its conversation market scope'; END IF;
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
  AND id=NEW.conversation_id AND project_id IS NOT DISTINCT FROM NEW.project_id FOR UPDATE;
 IF NOT FOUND OR NOT cehub_ai.conversation_actor_allowed(c.tenant_id,c.project_id,c.created_by_user_id,c.visibility,NEW.uploaded_by_user_id) THEN
  RAISE EXCEPTION 'Attachment must belong to its private creator' USING ERRCODE='23514';
 END IF;
 IF c.market_space_id IS NOT NULL AND NOT cehub_ai.require_product_conversation_actor(c.tenant_id,c.market_space_id,c.product_line_id,NEW.uploaded_by_user_id) THEN RAISE EXCEPTION 'Attachment actor lacks current product scope'; END IF;

 IF c.project_id IS NULL AND (NEW.parser_version<>'conversation-pdf-xlsx.v1' OR NEW.media_type NOT IN ('application/pdf','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')) THEN
  RAISE EXCEPTION 'Nonproject attachments support PDF and XLSX only'; END IF;
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
CREATE OR REPLACE FUNCTION cehub_ai.guard_message_attachment() RETURNS trigger
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
  AND project_id IS NOT DISTINCT FROM NEW.project_id AND id=NEW.conversation_id FOR UPDATE;
 SELECT * INTO m FROM cehub_ai.conversation_messages WHERE tenant_id=NEW.tenant_id
  AND conversation_id=NEW.conversation_id AND id=NEW.message_id;
 SELECT * INTO a FROM cehub_ai.conversation_attachments WHERE tenant_id=NEW.tenant_id
  AND conversation_id=NEW.conversation_id AND id=NEW.attachment_id;
 IF m.id IS NULL OR a.id IS NULL OR c.id IS NULL OR c.archived_at IS NOT NULL
  OR c.next_sequence<>m.sequence OR a.revoked_at IS NOT NULL
  OR m.project_id IS DISTINCT FROM NEW.project_id OR a.project_id IS DISTINCT FROM NEW.project_id
  OR m.action NOT IN ('note','project_query','product_work')
  OR (m.action IN ('project_query','product_work') AND (a.classification<>'internal' OR a.status<>'extracted')) THEN
  RAISE EXCEPTION 'Message requires currently usable sources in its original submission'
   USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION cehub_ai.guard_attachment_request() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Upload request receipts are immutable' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.conversation_attachments a WHERE a.tenant_id=NEW.tenant_id AND a.conversation_id=NEW.conversation_id AND a.id=NEW.attachment_id AND a.project_id IS NOT DISTINCT FROM NEW.project_id) THEN
  RAISE EXCEPTION 'Upload request must retain its exact attachment scope'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER guard_attachment_request ON cehub_ai.conversation_attachment_requests;
CREATE TRIGGER guard_attachment_request BEFORE INSERT OR UPDATE OR DELETE ON cehub_ai.conversation_attachment_requests FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_attachment_request();

CREATE FUNCTION cehub_ai.guard_conversation_product_run() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE m cehub_ai.conversation_messages%ROWTYPE; c cehub_ai.conversations%ROWTYPE; source jsonb;
BEGIN
 IF NEW.request_id IS NULL THEN RETURN NEW; END IF;
 SELECT * INTO m FROM cehub_ai.conversation_messages WHERE tenant_id=NEW.tenant_id AND operation_request_id=NEW.request_id AND action='product_work';
 IF NOT FOUND THEN RETURN NEW; END IF;
 SELECT * INTO c FROM cehub_ai.conversations WHERE tenant_id=m.tenant_id AND id=m.conversation_id;

 IF jsonb_typeof(m.product_work_request->'selection'->'sources') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'Product request sources must be an array'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(m.product_work_request->'selection'->'sources') selected
  WHERE selected->>'kind'='private_attachment' AND (selected->>'conversation_id' IS DISTINCT FROM m.conversation_id::text OR NOT EXISTS(
   SELECT 1 FROM cehub_ai.conversation_message_attachments b WHERE b.tenant_id=m.tenant_id AND b.conversation_id=m.conversation_id AND b.message_id=m.id AND b.attachment_id::text=selected->>'id' AND b.project_id IS NULL)))
  OR EXISTS(SELECT 1 FROM cehub_ai.conversation_message_attachments b WHERE b.tenant_id=m.tenant_id AND b.conversation_id=m.conversation_id AND b.message_id=m.id AND NOT EXISTS(
   SELECT 1 FROM jsonb_array_elements(m.product_work_request->'selection'->'sources') selected WHERE selected->>'kind'='private_attachment' AND selected->>'id'=b.attachment_id::text AND selected->>'conversation_id'=m.conversation_id::text)) THEN
  RAISE EXCEPTION 'Product private sources must match this message attachment bindings'; END IF;
 source:=NEW.run_context->'product_work_source';
 IF (NEW.context_version='product-work-request-v1' AND NEW.agent_key='product_management_intelligence' AND NEW.scope_kind='market_space' AND NEW.project_id IS NULL AND NEW.market_space_id=c.market_space_id AND NEW.requested_by_user_id=m.author_user_id
  AND NEW.run_context->'product_work_selection'=m.product_work_request->'selection'
  AND NEW.run_context->>'product_work_expected_digest'=m.product_work_request->>'expected_digest'
  AND NEW.run_context->>'product_work_user_instruction'=m.product_work_request->>'user_instruction'
  AND source->>'digest'=m.product_work_request->>'expected_digest'
  AND source->>'actor_id'=m.author_user_id::text
  AND source->>'market_space_id'=c.market_space_id::text
  AND source->'selection'=m.product_work_request->'selection') IS NOT TRUE THEN
  RAISE EXCEPTION 'Product run must match the exact saved conversation request'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_conversation_product_run() FROM PUBLIC;
CREATE TRIGGER guard_conversation_product_run BEFORE INSERT OR UPDATE ON cehub_ai.agent_runs FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_conversation_product_run();
"""

OLD_GUARDS = r"""CREATE OR REPLACE FUNCTION cehub_ai.guard_private_conversation() RETURNS trigger
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
CREATE OR REPLACE FUNCTION cehub_ai.guard_message_attachment() RETURNS trigger
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
CREATE OR REPLACE FUNCTION cehub_ai.guard_attachment_request() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 RAISE EXCEPTION 'Upload request receipts are immutable' USING ERRCODE='23514';
END $$;"""

DOWNGRADE_DDL = r"""DROP TRIGGER guard_conversation_product_run ON cehub_ai.agent_runs; DROP FUNCTION cehub_ai.guard_conversation_product_run();
DROP TRIGGER guard_attachment_request ON cehub_ai.conversation_attachment_requests; CREATE TRIGGER guard_attachment_request BEFORE UPDATE OR DELETE ON cehub_ai.conversation_attachment_requests FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_attachment_request();
ALTER TABLE cehub_ai.conversation_messages DROP CONSTRAINT ck_conversation_messages_product_request, DROP CONSTRAINT ck_conversation_messages_action_allowed, DROP CONSTRAINT ck_conversation_messages_action_source, ADD CONSTRAINT ck_conversation_messages_action_allowed CHECK(action IN ('note','project_query','meeting_reading','minutes','actions','decisions','business','change_work_package','quality_work_package','meeting_planning')), ADD CONSTRAINT ck_conversation_messages_action_source CHECK((action IN ('note','project_query') AND transcript_id IS NULL AND expected_digest IS NULL AND expected_minutes_version IS NULL) OR (action NOT IN ('note','project_query','change_work_package','quality_work_package','meeting_planning') AND transcript_id IS NOT NULL AND expected_digest IS NOT NULL AND expected_digest ~ '^[0-9a-f]{64}$' AND ((action='minutes' AND expected_minutes_version IS NOT NULL AND expected_minutes_version>=0) OR (action<>'minutes' AND expected_minutes_version IS NULL))) OR (action IN ('change_work_package','quality_work_package','meeting_planning') AND transcript_id IS NULL AND expected_minutes_version IS NULL AND expected_digest IS NOT NULL AND expected_digest ~ '^[0-9a-f]{64}$')), DROP COLUMN product_work_request;
ALTER TABLE cehub_ai.conversation_message_attachments DROP CONSTRAINT fk_conversation_message_attachments_typed_attachment;
ALTER TABLE cehub_ai.conversation_message_attachments DROP CONSTRAINT fk_conversation_message_attachments_typed_message;
ALTER TABLE cehub_ai.conversation_attachment_requests DROP CONSTRAINT fk_conversation_attachment_requests_typed_attachment;
ALTER TABLE cehub_ai.conversation_attachments DROP CONSTRAINT fk_conversation_attachments_typed_conversation;
ALTER TABLE cehub_ai.conversation_messages DROP CONSTRAINT fk_conversation_messages_typed_conversation;
ALTER TABLE cehub_ai.conversation_messages DROP CONSTRAINT uq_conversation_message_typed_scope;
ALTER TABLE cehub_ai.conversation_attachments DROP CONSTRAINT uq_conversation_attachment_typed_scope;
ALTER TABLE cehub_ai.conversations DROP CONSTRAINT ck_conversations_typed_scope, DROP CONSTRAINT fk_conversations_market_space, DROP CONSTRAINT fk_conversations_product_line, DROP CONSTRAINT uq_conversation_typed_scope, DROP COLUMN scope_kind, DROP COLUMN market_space_id, DROP COLUMN product_line_id;
ALTER TABLE cehub_ai.conversations ALTER COLUMN project_id SET NOT NULL;
ALTER TABLE cehub_ai.conversation_messages ALTER COLUMN project_id SET NOT NULL;
ALTER TABLE cehub_ai.conversation_attachments ALTER COLUMN project_id SET NOT NULL;
ALTER TABLE cehub_ai.conversation_attachment_requests ALTER COLUMN project_id SET NOT NULL;
ALTER TABLE cehub_ai.conversation_message_attachments ALTER COLUMN project_id SET NOT NULL;
DROP FUNCTION cehub_ai.require_product_conversation_actor(uuid,uuid,uuid,uuid);"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(AUTHORIZATION)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.conversations WHERE scope_kind<>'project') OR EXISTS(SELECT 1 FROM cehub_ai.conversation_messages WHERE action='product_work') THEN RAISE EXCEPTION 'Retain product conversation history'; END IF; END $$;"
    )
    op.execute(OLD_GUARDS)
    op.execute(DOWNGRADE_DDL)
