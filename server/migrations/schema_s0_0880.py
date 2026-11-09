"""@小Pai in shared threads and 小Pai's proactive mentions (D37 ⑥; P34-4/5, P52, P54, P62).

- `discussion_agent_requests`: one row per human message that @-mentioned 小Pai. The
  Run lives in the requester's own Session for that thread (P52). Rows are inserted by
  the requester (RLS + guard) and change only inside the SECURITY DEFINER functions
  below; the agent role has no privilege on the table.
- 小Pai's reply reaches the thread only through `discussion_agent_deliver` (P54): the
  body is the Run's own final summary read here, never a value passed in, and the host
  has checked every source the Run read against the thread's current audience. When
  that check fails, only a fixed notice is posted and the reply stays with the
  requester, who may share a link, or the body after an explicit acknowledgement
  (`discussion_agent_share`, P62).
- `guard_discussion_message` and `require_discussion_version` are replaced so that an
  agent-authored row is accepted only for one bound request, and is retracted only by
  its requester or the project owner (P54-3). Human rules are unchanged.
- `agent_mention_notify`: 小Pai's proactive mention (P34-5): assignment, missing
  information and rule exceptions only; the requester (or rule owner) and the
  recipient must both see the subject now; same object and reason once per cooldown
  (P41-9: one working day, computed by the caller and bounded here).

Placeholder s0_0880 on s0_0869 (D37 ⑥ range s0_0880–s0_0884); renumber at integration.
Upgrade asserts the two replaced functions are exactly the s0_0869 texts.
"""

# ruff: noqa: E501 -- Reviewed applied SQL literals remain byte-identical.

from migrations.schema_s0_0869 import FUNCTIONS as S0869_FUNCTIONS

REPLACED = ("guard_discussion_message()", "require_discussion_version()")
ORIGINAL = {sig: body for sig, body, _ in S0869_FUNCTIONS if sig in REPLACED}
EXPECTED_MD5 = {
    "guard_discussion_message": "78fb2f68772c69b50e31105854b04f55",
    "require_discussion_version": "c469769917b492b9575f3af01bf825ce",
}

TABLE_SQL = (
    "\nCREATE TABLE discussion_agent_requests (\n\tcategory_id UUID NOT NULL, \n\tproduct_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tthread_id UUID NOT NULL, \n\tmessage_id UUID NOT NULL, \n\trequester_id UUID NOT NULL, \n\twriter_id UUID NOT NULL, \n\tsession_id UUID NOT NULL, \n\trun_id UUID NOT NULL, \n\tprivate_only BOOLEAN NOT NULL, \n\tdelivery VARCHAR(16) NOT NULL, \n\treason VARCHAR(40), \n\treply_message_id UUID, \n\taudience_check JSONB, \n\tmanifest JSONB, \n\tshared_message_id UUID, \n\tshare_mode VARCHAR(8), \n\tshare_receipt JSONB, \n\tsettled_at TIMESTAMP WITH TIME ZONE, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tchange_seq BIGINT NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, message_id), \n\tUNIQUE (tenant_id, run_id), \n\tCONSTRAINT discussion_agent_thread_fk FOREIGN KEY(tenant_id, thread_id) REFERENCES discussion_threads (tenant_id, id), \n\tCONSTRAINT discussion_agent_message_fk FOREIGN KEY(tenant_id, message_id) REFERENCES discussion_messages (tenant_id, id), \n\tCONSTRAINT discussion_agent_reply_fk FOREIGN KEY(tenant_id, reply_message_id) REFERENCES discussion_messages (tenant_id, id), \n\tCONSTRAINT discussion_agent_share_fk FOREIGN KEY(tenant_id, shared_message_id) REFERENCES discussion_messages (tenant_id, id), \n\tCONSTRAINT discussion_agent_run_fk FOREIGN KEY(tenant_id, run_id) REFERENCES agent_runs (tenant_id, id), \n\tCONSTRAINT discussion_agent_session_fk FOREIGN KEY(tenant_id, session_id) REFERENCES agent_sessions (tenant_id, id), \n\tCONSTRAINT discussion_agent_requester_fk FOREIGN KEY(tenant_id, requester_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT discussion_agent_writer_fk FOREIGN KEY(tenant_id, writer_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT discussion_agent_request_shape CHECK (delivery IN ('pending','public','private','none') AND ((delivery='pending') = (settled_at IS NULL)) AND (reply_message_id IS NULL OR delivery IN ('public','private')) AND (shared_message_id IS NULL OR delivery='private') AND ((shared_message_id IS NULL) = (share_mode IS NULL)) AND ((shared_message_id IS NULL) = (share_receipt IS NULL)) AND (share_mode IS NULL OR share_mode IN ('body','link')))\n)\n\n",
    "CREATE INDEX ix_discussion_agent_requests_category_id ON discussion_agent_requests (category_id)",
    "CREATE INDEX ix_discussion_agent_requests_pending ON discussion_agent_requests (tenant_id, created_at) WHERE delivery='pending'",
    "CREATE INDEX ix_discussion_agent_requests_tenant_id ON discussion_agent_requests (tenant_id)",
    "CREATE INDEX ix_discussion_agent_requests_thread ON discussion_agent_requests (tenant_id, thread_id, requester_id, created_at)",
)

_HUMAN = """tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid
 AND public.scope_actor()=public.scope_requester()
 AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid
 AND p.id=public.scope_actor() AND p.active AND p.kind='human')"""
_THREAD = "EXISTS(SELECT 1 FROM public.discussion_threads th WHERE th.tenant_id=discussion_agent_requests.tenant_id AND th.id=discussion_agent_requests.thread_id)"

GUARD_MESSAGE = """CREATE OR REPLACE FUNCTION public.guard_discussion_message() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE latest integer; agent boolean; req discussion_agent_requests;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Discussion messages are retracted, never deleted' USING ERRCODE='23514'; END IF;
 agent := EXISTS(SELECT 1 FROM principals a WHERE a.tenant_id=NEW.tenant_id AND a.id=NEW.author_id AND a.kind='agent');
 IF TG_OP='INSERT' THEN
  PERFORM pg_advisory_xact_lock(hashtextextended('discussion-thread:'||NEW.thread_id::text,0));
  SELECT coalesce(max(sequence),0) INTO latest FROM discussion_messages WHERE tenant_id=NEW.tenant_id AND thread_id=NEW.thread_id;
  IF agent THEN
   -- 小Pai's reply, notice or shared reply: only for the one request bound by
   -- discussion_agent_deliver / discussion_agent_share in this transaction (P54).
   SELECT * INTO req FROM discussion_agent_requests WHERE tenant_id=NEW.tenant_id
    AND id::text=current_setting('pdos.discussion_agent_settle',true);
   IF req.id IS NULL OR req.thread_id<>NEW.thread_id OR req.writer_id<>NEW.author_id
    OR req.requester_id IS DISTINCT FROM scope_requester()
    OR scope_actor() IS NULL OR scope_actor() NOT IN (req.writer_id, req.requester_id)
    OR NEW.sequence<>latest+1 OR NEW.revision<>1 OR NEW.state<>'posted' OR NEW.mentions<>'[]'::jsonb
    OR NEW.subject_revision IS DISTINCT FROM discussion_subject_revision(NEW.tenant_id, NEW.thread_id) THEN
    RAISE EXCEPTION 'Invalid 小Pai reply' USING ERRCODE='23514'; END IF;
  ELSIF NEW.sequence<>latest+1 OR NEW.revision<>1 OR NEW.state<>'posted' OR NEW.author_id IS DISTINCT FROM scope_actor()
   OR NEW.author_id IS DISTINCT FROM scope_requester()
   OR NEW.subject_revision IS DISTINCT FROM discussion_subject_revision(NEW.tenant_id, NEW.thread_id) THEN
   RAISE EXCEPTION 'Invalid discussion message' USING ERRCODE='23514'; END IF;
 ELSIF agent THEN
  -- Only a retraction, by the request's requester or the project owner (P54-3).
  IF current_setting('pdos.discussion_agent_retract',true) IS DISTINCT FROM OLD.id::text
   OR ROW(NEW.id,NEW.tenant_id,NEW.created_at,NEW.thread_id,NEW.sequence,NEW.author_id,NEW.request_key,NEW.request_sha256)
    IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.created_at,OLD.thread_id,OLD.sequence,OLD.author_id,OLD.request_key,OLD.request_sha256)
   OR OLD.state='retracted' OR NEW.state<>'retracted' OR NEW.revision<>OLD.revision+1
   OR NEW.subject_revision IS DISTINCT FROM OLD.subject_revision OR scope_actor() IS DISTINCT FROM scope_requester()
   OR NOT EXISTS(SELECT 1 FROM principals x WHERE x.tenant_id=NEW.tenant_id AND x.id=scope_actor() AND x.active AND x.kind='human')
   OR NOT EXISTS(SELECT 1 FROM discussion_agent_requests r JOIN projects p ON p.tenant_id=r.tenant_id AND p.id=r.project_id
    WHERE r.tenant_id=OLD.tenant_id AND OLD.id IN (r.reply_message_id, r.shared_message_id)
     AND scope_actor() IN (r.requester_id, p.owner_id)) THEN
   RAISE EXCEPTION 'Only the requester or the project owner retracts a 小Pai reply' USING ERRCODE='23514'; END IF;
 ELSE
  IF ROW(NEW.id,NEW.tenant_id,NEW.created_at,NEW.thread_id,NEW.sequence,NEW.author_id,NEW.request_key,NEW.request_sha256)
    IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.created_at,OLD.thread_id,OLD.sequence,OLD.author_id,OLD.request_key,OLD.request_sha256)
   OR OLD.state='retracted' OR NEW.state NOT IN ('edited','retracted') OR NEW.revision<>OLD.revision+1
   OR OLD.author_id IS DISTINCT FROM scope_actor() OR scope_actor() IS DISTINCT FROM scope_requester()
   OR (NEW.state='edited' AND NEW.subject_revision IS DISTINCT FROM discussion_subject_revision(NEW.tenant_id, NEW.thread_id))
   OR (NEW.state='retracted' AND NEW.subject_revision IS DISTINCT FROM OLD.subject_revision) THEN
   RAISE EXCEPTION 'Only the author edits or retracts a message' USING ERRCODE='23514'; END IF;
 END IF;
 NEW.updated_at=statement_timestamp();
 NEW.change_seq=nextval('public.discussion_change_seq');
 RETURN NEW;
END $$"""

REQUIRE_VERSION = """CREATE OR REPLACE FUNCTION public.require_discussion_version() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE m discussion_messages;
BEGIN
 SELECT * INTO m FROM discussion_messages WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 -- A 小Pai reply's retraction version names the human who retracted it (P54-3).
 IF NOT EXISTS(SELECT 1 FROM discussion_message_versions v WHERE v.tenant_id=m.tenant_id AND v.message_id=m.id
   AND v.revision=m.revision AND v.thread_id=m.thread_id AND v.state=m.state
   AND (v.editor_id=m.author_id OR (m.state='retracted' AND EXISTS(SELECT 1 FROM principals a
    WHERE a.tenant_id=m.tenant_id AND a.id=m.author_id AND a.kind='agent')))
   AND v.subject_revision IS NOT DISTINCT FROM m.subject_revision
   AND (m.state='retracted' OR (v.body=m.body AND v.mentions=m.mentions))) THEN
  RAISE EXCEPTION 'Discussion message lacks its version' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$"""

FUNCTIONS = (
    (
        "guard_discussion_agent_request()",
        """CREATE FUNCTION public.guard_discussion_agent_request() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r agent_runs; m discussion_messages; th discussion_threads;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Agent requests are settled, never deleted' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' THEN
  SELECT * INTO r FROM agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;
  SELECT * INTO m FROM discussion_messages WHERE tenant_id=NEW.tenant_id AND id=NEW.message_id;
  SELECT * INTO th FROM discussion_threads WHERE tenant_id=NEW.tenant_id AND id=NEW.thread_id;
  -- The requester's own message in a thread of a project they fully see starts their
  -- own queued Run in their own Session (P52); 小Pai is the bound writer.
  IF r.id IS NULL OR m.id IS NULL OR th.id IS NULL
   OR NEW.requester_id IS DISTINCT FROM scope_actor() OR NEW.requester_id IS DISTINCT FROM scope_requester()
   OR m.thread_id<>NEW.thread_id OR m.author_id<>NEW.requester_id OR m.state<>'posted'
   OR th.category_id<>NEW.category_id OR th.product_id<>NEW.product_id OR th.project_id<>NEW.project_id
   OR NOT discussion_project_open(NEW.tenant_id, NEW.project_id)
   OR r.requester_id<>NEW.requester_id OR r.writer_id<>NEW.writer_id OR r.session_id<>NEW.session_id
   OR r.category_id IS DISTINCT FROM NEW.category_id OR r.product_id IS DISTINCT FROM NEW.product_id
   OR r.project_id IS DISTINCT FROM NEW.project_id OR r.state<>'queued' OR r.trigger<>'conversation'
   OR NOT EXISTS(SELECT 1 FROM principals w WHERE w.tenant_id=NEW.tenant_id AND w.id=NEW.writer_id AND w.active AND w.kind='agent')
   OR NOT EXISTS(SELECT 1 FROM agent_sessions x WHERE x.tenant_id=NEW.tenant_id AND x.id=NEW.session_id AND x.owner_id=NEW.requester_id
    AND x.project_id=NEW.project_id)
   OR NEW.delivery<>'pending' OR NEW.reason IS NOT NULL OR NEW.reply_message_id IS NOT NULL OR NEW.audience_check IS NOT NULL
   OR NEW.manifest IS NOT NULL OR NEW.shared_message_id IS NOT NULL OR NEW.settled_at IS NOT NULL THEN
   RAISE EXCEPTION 'Invalid 小Pai request' USING ERRCODE='23514'; END IF;
 ELSE
  IF current_setting('pdos.discussion_agent_settle',true) IS DISTINCT FROM OLD.id::text
   OR ROW(NEW.id,NEW.tenant_id,NEW.created_at,NEW.category_id,NEW.product_id,NEW.project_id,NEW.thread_id,NEW.message_id,
    NEW.requester_id,NEW.writer_id,NEW.session_id,NEW.run_id,NEW.private_only)
    IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.created_at,OLD.category_id,OLD.product_id,OLD.project_id,OLD.thread_id,OLD.message_id,
    OLD.requester_id,OLD.writer_id,OLD.session_id,OLD.run_id,OLD.private_only)
   OR (OLD.delivery<>'pending' AND (NEW.delivery<>OLD.delivery OR NEW.reason IS DISTINCT FROM OLD.reason
    OR NEW.reply_message_id IS DISTINCT FROM OLD.reply_message_id OR NEW.audience_check IS DISTINCT FROM OLD.audience_check
    OR NEW.manifest IS DISTINCT FROM OLD.manifest OR NEW.settled_at IS DISTINCT FROM OLD.settled_at
    OR OLD.shared_message_id IS NOT NULL))
   OR (OLD.delivery='pending' AND NEW.shared_message_id IS NOT NULL) THEN
   RAISE EXCEPTION '小Pai requests change only through delivery or share' USING ERRCODE='23514'; END IF;
 END IF;
 NEW.updated_at=statement_timestamp();
 NEW.change_seq=nextval('public.discussion_change_seq');
 RETURN NEW;
END $$""",
        (),
    ),
    (
        "discussion_agent_deliver(uuid,uuid,text,text,jsonb,jsonb)",
        """CREATE FUNCTION public.discussion_agent_deliver(t uuid, p_request uuid, p_verdict text, p_reason text,
  p_receipt jsonb, p_manifest jsonb) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE req discussion_agent_requests; r agent_runs; th discussion_threads; summary text; reply text;
 outcome text := p_verdict; why text := p_reason; created uuid; latest integer;
BEGIN
 IF t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid OR p_verdict NOT IN ('public','private','none')
  OR jsonb_typeof(p_receipt)<>'object' OR (p_manifest IS NOT NULL AND jsonb_typeof(p_manifest)<>'object')
  OR (p_verdict<>'public' AND p_reason IS NULL) THEN
  RAISE EXCEPTION 'Invalid 小Pai delivery' USING ERRCODE='23514'; END IF;
 SELECT * INTO req FROM discussion_agent_requests WHERE tenant_id=t AND id=p_request FOR UPDATE;
 IF NOT FOUND OR scope_actor() IS DISTINCT FROM req.writer_id OR scope_requester() IS DISTINCT FROM req.requester_id
  OR NOT EXISTS(SELECT 1 FROM principals w WHERE w.tenant_id=t AND w.id=req.writer_id AND w.active AND w.kind='agent') THEN
  RAISE EXCEPTION '小Pai delivery needs its bound writer and requester' USING ERRCODE='23514'; END IF;
 IF req.delivery<>'pending' THEN RETURN req.reply_message_id; END IF;
 SELECT * INTO STRICT r FROM agent_runs WHERE tenant_id=t AND id=req.run_id;
 IF r.reverted_at IS NULL AND r.state NOT IN ('completed','partial','failed','cancelled') THEN
  RAISE EXCEPTION '小Pai run has not ended' USING ERRCODE='23514'; END IF;
 SELECT * INTO STRICT th FROM discussion_threads WHERE tenant_id=t AND id=req.thread_id;
 -- The body is the Run's own final reply, never a value supplied by the caller (P54-2).
 summary := btrim(coalesce(r.result->>'summary',''));
 IF r.reverted_at IS NOT NULL OR r.state NOT IN ('completed','partial') OR summary='' THEN
  outcome := 'none';
  why := CASE WHEN r.reverted_at IS NOT NULL THEN 'run_reverted' WHEN r.state='cancelled' THEN 'run_cancelled'
   WHEN r.state='failed' THEN 'run_failed' ELSE 'no_reply' END;
 ELSIF NOT discussion_person_open(t, th.category_id, th.product_id, th.project_id, th.subject_type, th.subject_id, req.requester_id) THEN
  outcome := 'none'; why := 'requester_no_access';
 ELSIF req.private_only AND outcome='public' THEN
  outcome := 'private'; why := 'private_only';
 END IF;
 IF outcome='public' THEN
  why := NULL;
  reply := CASE WHEN char_length(summary)>7800 THEN left(summary,7800)||E'\\n\\n……（回复较长，完整内容请在小Pai 中查看）' ELSE summary END;
 ELSIF outcome='private' THEN
  reply := '小Pai 已回复发起人（只给发起人看）。';
 END IF;
 PERFORM set_config('pdos.discussion_agent_settle', req.id::text, true);
 IF reply IS NOT NULL THEN
  PERFORM pg_advisory_xact_lock(hashtextextended('discussion-thread:'||th.id::text,0));
  SELECT coalesce(max(sequence),0) INTO latest FROM discussion_messages WHERE tenant_id=t AND thread_id=th.id;
  INSERT INTO discussion_messages(id, tenant_id, created_at, thread_id, sequence, author_id, revision, state, body, mentions,
    subject_revision, updated_at, change_seq, request_key, request_sha256)
  VALUES (gen_random_uuid(), t, statement_timestamp(), th.id, latest+1, req.writer_id, 1, 'posted', reply, '[]'::jsonb,
    discussion_subject_revision(t, th.id), statement_timestamp(), 0, req.id, encode(sha256(convert_to(reply,'UTF8')),'hex'))
  RETURNING id INTO created;
  INSERT INTO discussion_message_versions(id, tenant_id, created_at, message_id, thread_id, revision, state, body, mentions,
    subject_revision, editor_id, request_key, request_sha256)
  VALUES (gen_random_uuid(), t, statement_timestamp(), created, th.id, 1, 'posted', reply, '[]'::jsonb,
    discussion_subject_revision(t, th.id), req.writer_id, req.id, encode(sha256(convert_to(reply,'UTF8')),'hex'));
 END IF;
 UPDATE discussion_agent_requests SET delivery=outcome, reason=why, reply_message_id=created,
  audience_check=p_receipt||jsonb_build_object('verdict', p_verdict, 'delivery', outcome, 'run_state', r.state,
   'settled_at', statement_timestamp()),
  manifest=p_manifest, settled_at=statement_timestamp()
  WHERE tenant_id=t AND id=req.id;
 PERFORM set_config('pdos.discussion_agent_settle', '', true);
 RETURN created;
END $$""",
        ("pdos_next_app",),
    ),
    (
        "discussion_agent_share(uuid,uuid,text,boolean,uuid,jsonb)",
        """CREATE FUNCTION public.discussion_agent_share(t uuid, p_request uuid, p_mode text, p_acknowledged boolean,
  p_key uuid, p_receipt jsonb) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE req discussion_agent_requests; r agent_runs; th discussion_threads; summary text; reply text; customer boolean;
 created uuid; latest integer;
BEGIN
 IF t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid OR p_mode NOT IN ('body','link')
  OR p_key IS NULL OR jsonb_typeof(p_receipt)<>'object' THEN
  RAISE EXCEPTION 'Invalid share' USING ERRCODE='23514'; END IF;
 SELECT * INTO req FROM discussion_agent_requests WHERE tenant_id=t AND id=p_request FOR UPDATE;
 IF NOT FOUND OR scope_actor() IS DISTINCT FROM req.requester_id OR scope_requester() IS DISTINCT FROM req.requester_id
  OR NOT EXISTS(SELECT 1 FROM principals x WHERE x.tenant_id=t AND x.id=req.requester_id AND x.active AND x.kind='human') THEN
  RAISE EXCEPTION 'Only the requester shares 小Pai''s reply' USING ERRCODE='23514'; END IF;
 IF req.shared_message_id IS NOT NULL THEN
  IF req.share_mode=p_mode THEN RETURN req.shared_message_id; END IF;
  RAISE EXCEPTION '小Pai''s reply is already shared' USING ERRCODE='23514'; END IF;
 IF req.delivery<>'private' THEN RAISE EXCEPTION 'Only a private reply is shared' USING ERRCODE='23514'; END IF;
 SELECT * INTO STRICT r FROM agent_runs WHERE tenant_id=t AND id=req.run_id;
 SELECT * INTO STRICT th FROM discussion_threads WHERE tenant_id=t AND id=req.thread_id;
 summary := btrim(coalesce(r.result->>'summary',''));
 IF r.reverted_at IS NOT NULL OR r.state NOT IN ('completed','partial') OR summary=''
  OR NOT discussion_person_open(t, th.category_id, th.product_id, th.project_id, th.subject_type, th.subject_id, req.requester_id) THEN
  RAISE EXCEPTION 'The reply can no longer be shared' USING ERRCODE='23514'; END IF;
 -- P62-1: a Run that read customer-private material shares a link only; P62-2: any
 -- other uncovered body needs the requester's explicit acknowledgement.
 customer := jsonb_array_length(coalesce(r.customer_identities,'[]'::jsonb))>0
  OR coalesce(r.data_categories,'[]'::jsonb) ?| ARRAY['customer','customer_original'];
 IF p_mode='body' AND (customer OR NOT coalesce(p_acknowledged,false)) THEN
  RAISE EXCEPTION 'Sharing the body needs a non-customer reply and an acknowledgement' USING ERRCODE='23514'; END IF;
 reply := CASE p_mode WHEN 'body' THEN
   CASE WHEN char_length(summary)>7800 THEN left(summary,7800)||E'\\n\\n……（回复较长，完整内容请在小Pai 中查看）' ELSE summary END
  ELSE '发起人分享了小Pai 回复的链接：能查看这次回复全部来源的成员可以打开。' END;
 PERFORM set_config('pdos.discussion_agent_settle', req.id::text, true);
 PERFORM pg_advisory_xact_lock(hashtextextended('discussion-thread:'||th.id::text,0));
 SELECT coalesce(max(sequence),0) INTO latest FROM discussion_messages WHERE tenant_id=t AND thread_id=th.id;
 INSERT INTO discussion_messages(id, tenant_id, created_at, thread_id, sequence, author_id, revision, state, body, mentions,
   subject_revision, updated_at, change_seq, request_key, request_sha256)
 VALUES (gen_random_uuid(), t, statement_timestamp(), th.id, latest+1, req.writer_id, 1, 'posted', reply, '[]'::jsonb,
   discussion_subject_revision(t, th.id), statement_timestamp(), 0, p_key, encode(sha256(convert_to(reply,'UTF8')),'hex'))
 RETURNING id INTO created;
 INSERT INTO discussion_message_versions(id, tenant_id, created_at, message_id, thread_id, revision, state, body, mentions,
   subject_revision, editor_id, request_key, request_sha256)
 VALUES (gen_random_uuid(), t, statement_timestamp(), created, th.id, 1, 'posted', reply, '[]'::jsonb,
   discussion_subject_revision(t, th.id), req.writer_id, p_key, encode(sha256(convert_to(reply,'UTF8')),'hex'));
 UPDATE discussion_agent_requests SET shared_message_id=created, share_mode=p_mode,
  share_receipt=p_receipt||jsonb_build_object('shared_by', req.requester_id, 'mode', p_mode, 'customer_derived', customer,
   'acknowledged', coalesce(p_acknowledged,false), 'shared_at', statement_timestamp())
  WHERE tenant_id=t AND id=req.id;
 PERFORM set_config('pdos.discussion_agent_settle', '', true);
 RETURN created;
END $$""",
        ("pdos_next_app",),
    ),
    (
        "discussion_agent_retract(uuid,uuid,integer,uuid,text)",
        """CREATE FUNCTION public.discussion_agent_retract(t uuid, p_message uuid, p_expected integer, p_key uuid, p_sha text)
 RETURNS integer
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE m discussion_messages; th discussion_threads; prior discussion_message_versions;
BEGIN
 IF t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid OR p_key IS NULL
  OR p_sha IS NULL OR p_sha !~ '^[a-f0-9]{64}$' OR scope_actor() IS DISTINCT FROM scope_requester()
  OR NOT EXISTS(SELECT 1 FROM principals x WHERE x.tenant_id=t AND x.id=scope_actor() AND x.active AND x.kind='human') THEN
  RAISE EXCEPTION 'Invalid retraction' USING ERRCODE='23514'; END IF;
 SELECT * INTO prior FROM discussion_message_versions WHERE tenant_id=t AND editor_id=scope_actor() AND request_key=p_key;
 IF FOUND THEN
  IF prior.message_id<>p_message OR prior.state<>'retracted' OR prior.request_sha256<>p_sha THEN
   RAISE EXCEPTION 'Request key already used' USING ERRCODE='23514'; END IF;
  RETURN prior.revision; END IF;
 SELECT * INTO m FROM discussion_messages WHERE tenant_id=t AND id=p_message FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unknown message' USING ERRCODE='23514'; END IF;
 SELECT * INTO STRICT th FROM discussion_threads WHERE tenant_id=t AND id=m.thread_id;
 IF NOT discussion_person_open(t, th.category_id, th.product_id, th.project_id, th.subject_type, th.subject_id, scope_actor())
  OR NOT EXISTS(SELECT 1 FROM discussion_agent_requests r JOIN projects p ON p.tenant_id=r.tenant_id AND p.id=r.project_id
   WHERE r.tenant_id=t AND m.id IN (r.reply_message_id, r.shared_message_id) AND scope_actor() IN (r.requester_id, p.owner_id)) THEN
  RAISE EXCEPTION 'Only the requester or the project owner retracts a 小Pai reply' USING ERRCODE='42501'; END IF;
 IF m.state='retracted' THEN RAISE EXCEPTION 'Message already retracted' USING ERRCODE='55000'; END IF;
 IF m.revision<>p_expected THEN RAISE EXCEPTION 'Message changed' USING ERRCODE='40001'; END IF;
 PERFORM set_config('pdos.discussion_agent_retract', m.id::text, true);
 UPDATE discussion_messages SET revision=m.revision+1, state='retracted', body='', mentions='[]'::jsonb WHERE tenant_id=t AND id=m.id;
 INSERT INTO discussion_message_versions(id, tenant_id, created_at, message_id, thread_id, revision, state, body, mentions,
   subject_revision, editor_id, request_key, request_sha256)
 VALUES (gen_random_uuid(), t, statement_timestamp(), m.id, m.thread_id, m.revision+1, 'retracted', '', '[]'::jsonb,
   m.subject_revision, scope_actor(), p_key, p_sha);
 PERFORM set_config('pdos.discussion_agent_retract', '', true);
 RETURN m.revision+1;
END $$""",
        ("pdos_next_app",),
    ),
    (
        "discussion_agent_states(uuid,uuid)",
        """CREATE FUNCTION public.discussion_agent_states(t uuid, thread uuid)
 RETURNS TABLE(request_id uuid, run_state text, error_code text)
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 -- Run status only (the card in the thread); never a goal, a source or a reply.
 SELECT q.id, CASE WHEN r.reverted_at IS NOT NULL THEN 'reverted' ELSE r.state END::text, r.error_code::text
 FROM discussion_agent_requests q
 JOIN agent_runs r ON r.tenant_id=q.tenant_id AND r.id=q.run_id
 JOIN discussion_threads th ON th.tenant_id=q.tenant_id AND th.id=q.thread_id
 WHERE t=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND q.tenant_id=t AND q.thread_id=thread
  AND scope_actor()=scope_requester()
  AND discussion_person_open(t, th.category_id, th.product_id, th.project_id, th.subject_type, th.subject_id, scope_requester())
$$""",
        ("pdos_next_app",),
    ),
    (
        "discussion_thread_audience(uuid,uuid)",
        """CREATE FUNCTION public.discussion_thread_audience(t uuid, thread uuid) RETURNS SETOF uuid
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 -- Everyone who can see the thread's subject now; only for a caller who sees it too.
 SELECT DISTINCT p.id FROM discussion_threads th
 JOIN grants g ON g.tenant_id=th.tenant_id AND g.category_id=th.category_id
 JOIN principals p ON p.tenant_id=g.tenant_id AND p.id=g.principal_id AND p.active AND p.kind='human'
 WHERE t=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND th.tenant_id=t AND th.id=thread
  AND discussion_person_open(t, th.category_id, th.product_id, th.project_id, th.subject_type, th.subject_id, scope_requester())
  AND discussion_person_open(t, th.category_id, th.product_id, th.project_id, th.subject_type, th.subject_id, p.id)
 ORDER BY p.id
$$""",
        ("pdos_next_app",),
    ),
    (
        "discussion_agent_reply_text(uuid,uuid)",
        """CREATE FUNCTION public.discussion_agent_reply_text(t uuid, p_request uuid) RETURNS text
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 -- The requester's own reply, or a reply shared as a link: the caller's host has
 -- checked the reader against the Run's frozen sources first (P62-1).
 SELECT btrim(r.result->>'summary') FROM discussion_agent_requests q
 JOIN agent_runs r ON r.tenant_id=q.tenant_id AND r.id=q.run_id
 JOIN discussion_threads th ON th.tenant_id=q.tenant_id AND th.id=q.thread_id
 WHERE t=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND q.tenant_id=t AND q.id=p_request
  AND scope_actor()=scope_requester()
  AND EXISTS(SELECT 1 FROM principals x WHERE x.tenant_id=t AND x.id=scope_actor() AND x.active AND x.kind='human')
  AND r.reverted_at IS NULL AND r.state IN ('completed','partial')
  AND (scope_requester()=q.requester_id OR (q.share_mode='link' AND q.delivery='private'))
  AND discussion_person_open(t, th.category_id, th.product_id, th.project_id, th.subject_type, th.subject_id, scope_requester())
$$""",
        ("pdos_next_app",),
    ),
    (
        "discussion_agent_pending(uuid,integer)",
        """CREATE FUNCTION public.discussion_agent_pending(t uuid, maximum integer)
 RETURNS TABLE(request_id uuid, category_id uuid, requester_id uuid, writer_id uuid)
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 -- Dispatcher view: identities of requests whose Run has ended, nothing else.
 SELECT q.id, q.category_id, q.requester_id, q.writer_id FROM discussion_agent_requests q
 JOIN agent_runs r ON r.tenant_id=q.tenant_id AND r.id=q.run_id
 WHERE t=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND q.tenant_id=t AND q.delivery='pending'
  AND (r.reverted_at IS NOT NULL OR r.state IN ('completed','partial','failed','cancelled'))
 ORDER BY q.created_at LIMIT GREATEST(0, LEAST(maximum, 100))
$$""",
        ("pdos_next_dispatch",),
    ),
    (
        "discussion_agent_reference(uuid,uuid)",
        """CREATE FUNCTION public.discussion_agent_reference(t uuid, p_request uuid)
 RETURNS TABLE(request_id uuid, category_id uuid, requester_id uuid, writer_id uuid, delivery text)
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT q.id, q.category_id, q.requester_id, q.writer_id, q.delivery::text FROM discussion_agent_requests q
 WHERE t=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND q.tenant_id=t AND q.id=p_request
$$""",
        ("pdos_next_dispatch",),
    ),
    (
        "agent_mention_notify(uuid,uuid,text,uuid,text,uuid,uuid,jsonb,integer)",
        """CREATE FUNCTION public.agent_mention_notify(t uuid, p_recipient uuid, p_reason text, p_project uuid, p_kind text,
  p_subject uuid, p_thread uuid, p_latest jsonb, p_cooldown integer) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE proj projects; category text; mkey text; created uuid;
BEGIN
 IF t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
  OR p_reason NOT IN ('task.assigned','agent.needs_info','agent.rule_exception')
  OR p_cooldown NOT BETWEEN 86400 AND 432000 OR jsonb_typeof(p_latest)<>'object' THEN
  RAISE EXCEPTION 'Invalid 小Pai mention' USING ERRCODE='23514'; END IF;
 -- Proactive mentions are 小Pai's own, for an active human requester or rule owner (P34-5).
 IF NOT EXISTS(SELECT 1 FROM principals w WHERE w.tenant_id=t AND w.id=scope_actor() AND w.active AND w.kind='agent')
  OR NOT EXISTS(SELECT 1 FROM principals x WHERE x.tenant_id=t AND x.id=scope_requester() AND x.active AND x.kind='human') THEN
  RAISE EXCEPTION 'Proactive mentions are 小Pai''s own' USING ERRCODE='23514'; END IF;
 IF p_recipient=scope_requester() OR p_recipient=scope_actor() THEN RETURN NULL; END IF;
 -- Reading never exceeds the requester's (or rule owner's) current range; the
 -- recipient must see the subject now as well.
 IF NOT notification_subject_open(t, scope_requester(), p_kind, p_subject, p_project)
  OR NOT notification_subject_open(t, p_recipient, p_kind, p_subject, p_project) THEN RETURN NULL; END IF;
 SELECT * INTO STRICT proj FROM projects WHERE tenant_id=t AND id=p_project;
 category := CASE p_reason WHEN 'task.assigned' THEN 'assigned' ELSE 'agent' END;
 mkey := category||':'||p_kind||':'||p_subject::text||':'||coalesce(p_thread::text,'-');
 PERFORM pg_advisory_xact_lock(hashtextextended('agent-mention:'||t::text||':'||p_recipient::text||':'||mkey||':'||p_reason,0));
 -- Same object, same reason: one within the cooldown, read or not (P34-5, P41-9).
 IF EXISTS(SELECT 1 FROM notifications n WHERE n.tenant_id=t AND n.recipient_id=p_recipient AND n.merge_key=mkey
   AND n.reason=p_reason AND n.first_at>=statement_timestamp()-make_interval(secs=>p_cooldown)
   AND EXISTS(SELECT 1 FROM principals a WHERE a.tenant_id=t AND a.id=ANY(n.actor_ids) AND a.kind='agent')) THEN
  RETURN NULL; END IF;
 INSERT INTO notifications(id, tenant_id, created_at, recipient_id, category_id, project_id, category, reason, subject_kind,
   subject_id, thread_id, merge_key, actor_ids, event_count, first_at, last_at, latest, delivery, change_seq)
 VALUES (gen_random_uuid(), t, statement_timestamp(), p_recipient, proj.category_id, p_project, category, p_reason, p_kind,
   p_subject, p_thread, mkey, ARRAY[scope_actor()], 1, statement_timestamp(), statement_timestamp(), p_latest, 'instant', 0)
 RETURNING id INTO created;
 RETURN created;
END $$""",
        ("pdos_next_app",),
    ),
)

SECURITY_SQL = (
    "ALTER TABLE public.discussion_agent_requests ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.discussion_agent_requests FORCE ROW LEVEL SECURITY",
    "CREATE POLICY owner_internal ON public.discussion_agent_requests TO pdos_next_owner USING(true) WITH CHECK(true)",
    "REVOKE ALL ON public.discussion_agent_requests FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch",
    "GRANT SELECT,INSERT ON public.discussion_agent_requests TO pdos_next_app",
    f"CREATE POLICY request_read ON public.discussion_agent_requests FOR SELECT TO pdos_next_app USING({_HUMAN} AND {_THREAD})",
    f"CREATE POLICY request_start ON public.discussion_agent_requests FOR INSERT TO pdos_next_app WITH CHECK({_HUMAN} AND requester_id=public.scope_actor() AND {_THREAD})",
)

TRIGGER_SQL = (
    "CREATE TRIGGER request_guard BEFORE INSERT OR UPDATE OR DELETE ON public.discussion_agent_requests FOR EACH ROW EXECUTE FUNCTION public.guard_discussion_agent_request()",
)

SCHEMA_SQL = (
    *TABLE_SQL,
    *(body for _, body, _ in FUNCTIONS),
    *(f"REVOKE ALL ON FUNCTION public.{sig} FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch" for sig, _, _ in FUNCTIONS),
    *(f"GRANT EXECUTE ON FUNCTION public.{sig} TO {role}" for sig, _, roles in FUNCTIONS for role in roles),
    *SECURITY_SQL,
    *TRIGGER_SQL,
    GUARD_MESSAGE,
    REQUIRE_VERSION,
)

DOWNGRADE_SQL = (
    """DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.discussion_agent_requests) OR EXISTS(SELECT 1 FROM public.discussion_messages m
     JOIN public.principals a ON a.tenant_id=m.tenant_id AND a.id=m.author_id WHERE a.kind='agent') THEN
     RAISE EXCEPTION '小Pai thread history requires s0_0880'; END IF; END $$""",
    *(ORIGINAL[sig].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1) for sig in REPLACED),
    "DROP TABLE public.discussion_agent_requests",
    *(f"DROP FUNCTION public.{sig}" for sig, _, _ in reversed(FUNCTIONS)),
)
