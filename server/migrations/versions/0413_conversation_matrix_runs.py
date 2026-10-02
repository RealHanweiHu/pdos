"""Private conversation matrix requests retain the original deterministic coverage result."""

# ruff: noqa: E501
from alembic import op

revision = "0413_conversation_matrix_runs"
down_revision = "0412_product_conversations"
branch_labels = None
depends_on = None

NEW_REQUEST_CHECK = r"""((action='product_work' AND project_id IS NULL AND product_work_request IS NOT NULL AND jsonb_typeof(product_work_request)='object' AND jsonb_typeof(product_work_request->'selection')='object' AND product_work_request->>'expected_digest' ~ '^[0-9a-f]{64}$' AND jsonb_typeof(product_work_request->'user_instruction')='string') OR (action<>'product_work' AND product_work_request IS NULL)) IS TRUE AND (product_work_request IS NULL OR ((NOT (product_work_request ? 'kind') OR (jsonb_typeof(product_work_request->'kind')='string' AND product_work_request->>'kind'='work')) OR (product_work_request->>'kind'='matrix' AND product_work_request - ARRAY['kind','selection','expected_digest','user_instruction','product_line_id']::text[]='{}'::jsonb AND product_work_request ? 'product_line_id' AND jsonb_typeof(product_work_request->'product_line_id') IN ('string','null') AND (product_work_request->'selection') - ARRAY['record_id','roadmap_ids']::text[]='{}'::jsonb AND jsonb_typeof(product_work_request->'selection'->'record_id')='string' AND product_work_request->'selection'->>'record_id' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND jsonb_typeof(product_work_request->'selection'->'roadmap_ids')='array')) IS TRUE) AND (project_id IS NOT NULL OR (action IN ('note','product_work') AND object_focus IS NULL))"""

OLD_REQUEST_CHECK = r"""((action='product_work' AND project_id IS NULL AND product_work_request IS NOT NULL AND jsonb_typeof(product_work_request)='object' AND jsonb_typeof(product_work_request->'selection')='object' AND product_work_request->>'expected_digest' ~ '^[0-9a-f]{64}$' AND jsonb_typeof(product_work_request->'user_instruction')='string') OR (action<>'product_work' AND product_work_request IS NULL)) IS TRUE AND (project_id IS NOT NULL OR (action IN ('note','product_work') AND object_focus IS NULL))"""

UPGRADE_DDL = r"""ALTER TABLE cehub_ai.conversation_messages DROP CONSTRAINT ck_conversation_messages_product_request, ADD CONSTRAINT ck_conversation_messages_product_request CHECK(((action='product_work' AND project_id IS NULL AND product_work_request IS NOT NULL AND jsonb_typeof(product_work_request)='object' AND jsonb_typeof(product_work_request->'selection')='object' AND product_work_request->>'expected_digest' ~ '^[0-9a-f]{64}$' AND jsonb_typeof(product_work_request->'user_instruction')='string') OR (action<>'product_work' AND product_work_request IS NULL)) IS TRUE AND (product_work_request IS NULL OR ((NOT (product_work_request ? 'kind') OR (jsonb_typeof(product_work_request->'kind')='string' AND product_work_request->>'kind'='work')) OR (product_work_request->>'kind'='matrix' AND product_work_request - ARRAY['kind','selection','expected_digest','user_instruction','product_line_id']::text[]='{}'::jsonb AND product_work_request ? 'product_line_id' AND jsonb_typeof(product_work_request->'product_line_id') IN ('string','null') AND (product_work_request->'selection') - ARRAY['record_id','roadmap_ids']::text[]='{}'::jsonb AND jsonb_typeof(product_work_request->'selection'->'record_id')='string' AND product_work_request->'selection'->>'record_id' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND jsonb_typeof(product_work_request->'selection'->'roadmap_ids')='array')) IS TRUE) AND (project_id IS NOT NULL OR (action IN ('note','product_work') AND object_focus IS NULL)));"""

DOWNGRADE_DDL = r"""ALTER TABLE cehub_ai.conversation_messages DROP CONSTRAINT ck_conversation_messages_product_request, ADD CONSTRAINT ck_conversation_messages_product_request CHECK(((action='product_work' AND project_id IS NULL AND product_work_request IS NOT NULL AND jsonb_typeof(product_work_request)='object' AND jsonb_typeof(product_work_request->'selection')='object' AND product_work_request->>'expected_digest' ~ '^[0-9a-f]{64}$' AND jsonb_typeof(product_work_request->'user_instruction')='string') OR (action<>'product_work' AND product_work_request IS NULL)) IS TRUE AND (project_id IS NOT NULL OR (action IN ('note','product_work') AND object_focus IS NULL)));"""

GUARDS = r"""CREATE OR REPLACE FUNCTION cehub_ai.guard_conversation_message() RETURNS trigger
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

 IF NEW.action='product_work' THEN
  IF c.scope_kind NOT IN ('market_space','product_line') THEN
   RAISE EXCEPTION 'Product work must retain its conversation market scope'; END IF;
  IF ((CASE WHEN NEW.product_work_request ? 'kind' THEN NEW.product_work_request->>'kind' ELSE 'work' END) IN ('work','matrix')) IS NOT TRUE THEN
   RAISE EXCEPTION 'Unknown product conversation request kind'; END IF;
  IF NEW.product_work_request->>'kind'='matrix' THEN
   IF (NEW.product_work_request-ARRAY['kind','selection','expected_digest','user_instruction','product_line_id']) IS DISTINCT FROM '{}'::jsonb
    OR (NEW.product_work_request ? 'product_line_id') IS NOT TRUE
    OR NEW.product_work_request->>'product_line_id' IS DISTINCT FROM c.product_line_id::text
    OR jsonb_typeof(NEW.product_work_request->'selection'->'roadmap_ids') IS DISTINCT FROM 'array'
    OR ((NEW.product_work_request->'selection')-ARRAY['record_id','roadmap_ids']) IS DISTINCT FROM '{}'::jsonb
    OR NOT EXISTS(SELECT 1 FROM cehub_product.product_matrix_records r WHERE r.tenant_id=c.tenant_id
     AND r.market_space_id=c.market_space_id AND r.product_line_id IS NOT DISTINCT FROM c.product_line_id
     AND r.id::text=NEW.product_work_request->'selection'->>'record_id') THEN
    RAISE EXCEPTION 'Matrix request must use an original record in the conversation scope'; END IF;
   IF ((NEW.product_work_request->'selection'->>'record_id') ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') IS NOT TRUE
    OR jsonb_array_length(NEW.product_work_request->'selection'->'roadmap_ids')>8
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.product_work_request->'selection'->'roadmap_ids') value
     WHERE (jsonb_typeof(value)='string' AND (value#>>'{}') ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') IS NOT TRUE)
    OR (SELECT count(*)<>count(DISTINCT value) FROM jsonb_array_elements(NEW.product_work_request->'selection'->'roadmap_ids') value) THEN
    RAISE EXCEPTION 'Matrix selection requires canonical unique UUIDs and at most eight roadmaps'; END IF;

  ELSIF NEW.product_work_request->'selection'->>'product_line_id' IS DISTINCT FROM c.product_line_id::text THEN
   RAISE EXCEPTION 'Product work must retain its conversation market scope'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION cehub_ai.guard_conversation_product_run() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE m cehub_ai.conversation_messages%ROWTYPE; c cehub_ai.conversations%ROWTYPE; source jsonb;
BEGIN
 IF NEW.request_id IS NULL THEN RETURN NEW; END IF;
 SELECT * INTO m FROM cehub_ai.conversation_messages WHERE tenant_id=NEW.tenant_id AND operation_request_id=NEW.request_id AND action='product_work';
 IF NOT FOUND THEN RETURN NEW; END IF;
 SELECT * INTO c FROM cehub_ai.conversations WHERE tenant_id=m.tenant_id AND id=m.conversation_id;

 IF ((CASE WHEN m.product_work_request ? 'kind' THEN m.product_work_request->>'kind' ELSE 'work' END) IN ('work','matrix')) IS NOT TRUE THEN
  RAISE EXCEPTION 'Unknown product conversation request kind'; END IF;
 IF m.product_work_request->>'kind'='matrix' THEN
  IF EXISTS(SELECT 1 FROM cehub_ai.conversation_message_attachments b WHERE b.tenant_id=m.tenant_id AND b.conversation_id=m.conversation_id AND b.message_id=m.id) THEN
   RAISE EXCEPTION 'Matrix requests cannot use private attachment bindings'; END IF;
  source:=NEW.run_context->'matrix_source';
  IF (NEW.context_version='product-matrix-request-v1' AND NEW.agent_key='product_management_intelligence'
   AND NEW.project_id IS NULL AND NEW.scope_kind='market_space' AND NEW.market_space_id=c.market_space_id
   AND NEW.requested_by_user_id=m.author_user_id
   AND NEW.run_context->'matrix_selection'=m.product_work_request->'selection'
   AND NEW.run_context->>'matrix_expected_digest'=m.product_work_request->>'expected_digest'
   AND NEW.run_context->>'matrix_user_instruction'=m.product_work_request->>'user_instruction'
   AND source->>'actor_id'=m.author_user_id::text AND source->>'market_space_id'=c.market_space_id::text
   AND source->'selection'=m.product_work_request->'selection'
   AND source->>'digest'=m.product_work_request->>'expected_digest'
   AND m.product_work_request->>'product_line_id' IS NOT DISTINCT FROM c.product_line_id::text
   AND EXISTS(SELECT 1 FROM cehub_product.product_matrix_records r WHERE r.tenant_id=c.tenant_id
    AND r.market_space_id=c.market_space_id AND r.product_line_id IS NOT DISTINCT FROM c.product_line_id
    AND r.id::text=m.product_work_request->'selection'->>'record_id'
    AND r.result_digest=source->>'record_result_digest')) IS NOT TRUE THEN
   RAISE EXCEPTION 'Matrix run must match its exact saved request and original frozen result'; END IF;
  RETURN NEW;
 END IF;

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
 IF m.id IS NOT NULL AND a.id IS NOT NULL AND c.id IS NOT NULL
  AND c.project_id IS NOT DISTINCT FROM NEW.project_id
  AND m.project_id IS NOT DISTINCT FROM NEW.project_id
  AND a.project_id IS NOT DISTINCT FROM NEW.project_id
  AND m.action='product_work' AND m.product_work_request->>'kind'='matrix' THEN
  RAISE EXCEPTION 'Matrix requests cannot use private attachment bindings'; END IF;
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
REVOKE ALL ON FUNCTION cehub_ai.guard_conversation_message() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.guard_conversation_product_run() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_ai.guard_message_attachment() FROM PUBLIC;
"""

OLD_GUARDS = r"""CREATE OR REPLACE FUNCTION cehub_ai.guard_conversation_message() RETURNS trigger
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
CREATE OR REPLACE FUNCTION cehub_ai.guard_conversation_product_run() RETURNS trigger
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
END $$;"""

DOWNGRADE_PROTECTION = r"""DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM cehub_ai.conversation_messages WHERE action='product_work' AND product_work_request->>'kind'='matrix')
 OR EXISTS(SELECT 1 FROM cehub_ai.agent_runs r JOIN cehub_ai.conversation_messages m
  ON m.tenant_id=r.tenant_id AND m.operation_request_id=r.request_id
  WHERE m.action='product_work' AND r.context_version='product-matrix-request-v1') THEN
  RAISE EXCEPTION 'Retain conversation matrix request and run history'; END IF;
END $$;"""


def upgrade() -> None:
    op.execute(UPGRADE_DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute(DOWNGRADE_PROTECTION)
    op.execute(OLD_GUARDS)
    op.execute(DOWNGRADE_DDL)
