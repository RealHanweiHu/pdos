# ruff: noqa: E501
"""Frozen registered snapshot provenance and exact Unicode page consumption.

Legacy registrations retain their operational behavior. Only explicitly marked
registration receipts and complete, current-Run read bindings become page proofs.
All additions are private owner helpers/triggers; no reader gains access to another
requester's original Run or model response. Existing source and receipt guards stay.
"""

SCHEMA_SQL = (
    r"""CREATE FUNCTION public.kernel_snapshot_registration_proven(s public_web_snapshots) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $function$
DECLARE a action_receipts; r agent_runs; actor_kind text; ref jsonb;
 c agent_tool_calls; m agent_tool_calls; request jsonb; response_position integer;
BEGIN
 SELECT * INTO a FROM action_receipts WHERE tenant_id=s.tenant_id AND id=s.receipt_id;
 SELECT * INTO r FROM agent_runs WHERE tenant_id=s.tenant_id AND id=s.registered_by_run_id;
 SELECT kind INTO actor_kind FROM principals WHERE tenant_id=s.tenant_id AND id=a.actor_id;
 IF a.id IS NULL OR r.id IS NULL OR actor_kind IS NULL
  OR a.category_id IS DISTINCT FROM s.category_id OR a.requester_id<>s.owner_id
  OR r.requester_id<>s.owner_id OR a.subject_revision<>1 OR a.run_id IS NOT NULL
  OR jsonb_typeof(a.result) IS DISTINCT FROM 'object' OR a.result->'proof_version' IS DISTINCT FROM '1'::jsonb
  OR a.result->>'registered_by_run_id' IS DISTINCT FROM r.id::text
  OR s.content_hash IS DISTINCT FROM encode(sha256(convert_to(s.markdown,'UTF8')),'hex')
  OR s.visibility IS DISTINCT FROM (CASE WHEN r.private_context THEN 'private' ELSE 'category' END)
  OR NOT EXISTS(SELECT 1 FROM principals WHERE tenant_id=s.tenant_id AND id=r.requester_id AND kind='human')
  OR NOT EXISTS(SELECT 1 FROM principals WHERE tenant_id=s.tenant_id AND id=r.writer_id AND kind='agent') THEN RETURN false; END IF;
 IF a.operation='research.snapshot.register' THEN
  IF r.category_id IS DISTINCT FROM s.category_id OR a.product_id IS DISTINCT FROM r.product_id
   OR a.subject_type<>'public_web_snapshot' OR a.subject_id<>s.id
   OR a.result->>'snapshot_id' IS DISTINCT FROM s.id::text
   OR a.result->>'content_hash' IS DISTINCT FROM s.content_hash THEN RETURN false; END IF;
  IF actor_kind='agent' THEN
   IF a.agent_run_id IS DISTINCT FROM r.id OR a.actor_id<>r.writer_id
    OR a.confirmation_id IS NOT NULL OR a.result ? 'prepared_by_run_id' THEN RETURN false; END IF;
   SELECT * INTO c FROM agent_tool_calls WHERE tenant_id=s.tenant_id AND run_id=r.id
    AND receipt_id=a.id AND tool=a.operation AND state='completed';
   IF c.id IS NULL OR c.error_code IS NOT NULL
    OR c.execution_binding->>'kind' IS DISTINCT FROM 'domain_t0'
    OR c.execution_binding->>'operation' IS DISTINCT FROM a.operation
    OR NOT coalesce(c.execution_binding->>'model_call_id' ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
     AND c.execution_binding->>'response_index' ~ '^(0|[1-9][0-9]*)$'
     AND (c.execution_binding->>'response_index')::numeric<=2147483647,false) THEN RETURN false; END IF;
   response_position=(c.execution_binding->>'response_index')::integer;
   SELECT * INTO m FROM agent_tool_calls WHERE tenant_id=s.tenant_id AND run_id=r.id
    AND id=(c.execution_binding->>'model_call_id')::uuid;
   IF m.id IS NULL OR m.id=c.id OR m.tool<>'model' OR m.state<>'completed'
    OR m.error_code IS NOT NULL OR m.receipt_id IS NOT NULL
    OR m.execution_binding->>'kind' IS DISTINCT FROM 'model'
    OR m.execution_binding->>'isolation' IS DISTINCT FROM 'main'
    OR m.execution_binding->'cancel_epoch' IS DISTINCT FROM c.execution_binding->'cancel_epoch'
    OR m.execution_binding->'model_version' IS DISTINCT FROM c.execution_binding->'model_version'
    OR m.execution_binding->'model_route_digest' IS DISTINCT FROM c.execution_binding->'model_route_digest'
    OR m.execution_binding->'tool_definitions_digest' IS DISTINCT FROM c.execution_binding->'tool_definitions_digest'
    OR m.execution_binding->'model_version' IS DISTINCT FROM r.versions->'model_version'
    OR m.execution_binding->'model_route_digest' IS DISTINCT FROM r.versions->'model_route_digest'
    OR m.execution_binding->'tool_definitions_digest' IS DISTINCT FROM r.versions->'tool_definitions'->'main'
    OR m.execution_binding->'prompt_digest' IS DISTINCT FROM r.versions->'prompt_prefixes'->'main'
    OR jsonb_typeof(m.result->'calls') IS DISTINCT FROM 'array'
    OR c.call_key IS DISTINCT FROM 'agent:'||r.id::text||':model:'||m.id::text||':'||response_position::text
    THEN RETURN false; END IF;
   request=m.result->'calls'->response_position;
   IF NOT coalesce(jsonb_typeof(request)='object' AND request->>'name'=a.operation
    AND jsonb_typeof(request->'arguments')='object',false)
    OR c.input_digest IS DISTINCT FROM encode(sha256(convert_to(
     kernel_read_canonical_json(jsonb_build_array(c.tool,request->'arguments')),'UTF8')),'hex') THEN RETURN false; END IF;
  ELSE
   IF actor_kind<>'human' OR a.actor_id<>a.requester_id
    OR (a.agent_run_id IS NOT NULL AND a.agent_run_id<>r.id)
    OR a.result->>'prepared_by_run_id' IS DISTINCT FROM r.id::text
    OR NOT EXISTS(SELECT 1 FROM confirmations cp WHERE cp.tenant_id=s.tenant_id AND cp.id=a.confirmation_id
     AND cp.actor_id=a.actor_id AND cp.category_id=s.category_id AND cp.product_id IS NOT DISTINCT FROM a.product_id
     AND cp.operation=a.operation AND cp.consumed) THEN RETURN false; END IF;
  END IF;
 ELSIF a.operation='category.create' THEN
  IF r.category_id IS NOT NULL OR r.private_context OR r.product_id IS NOT NULL
   OR a.subject_type<>'category' OR a.subject_id<>s.category_id OR a.product_id IS NOT NULL
   OR a.agent_run_id IS NOT NULL OR actor_kind<>'human' OR a.actor_id<>a.requester_id
   OR a.result->>'category_id' IS DISTINCT FROM s.category_id::text
   OR a.result->>'prepared_by_run_id' IS DISTINCT FROM r.id::text
   OR jsonb_typeof(a.result->'snapshot_refs') IS DISTINCT FROM 'array'
   OR NOT EXISTS(SELECT 1 FROM category_creation_confirmations cp WHERE cp.tenant_id=s.tenant_id
    AND cp.actor_id=a.actor_id AND cp.reserved_category_id=s.category_id AND cp.consumed
    AND cp.payload_digest=a.request_digest AND cp.snapshot->'payload'->>'prepared_by_run_id'=r.id::text)
   THEN RETURN false; END IF;
  IF (SELECT count(*) FROM jsonb_array_elements(a.result->'snapshot_refs') item WHERE item->>'snapshot_id'=s.id::text)<>1 THEN RETURN false; END IF;
  SELECT item INTO ref FROM jsonb_array_elements(a.result->'snapshot_refs') item WHERE item->>'snapshot_id'=s.id::text;
  IF NOT coalesce(jsonb_typeof(ref)='object' AND ref ?& ARRAY['snapshot_id','content_hash','call_id']
   AND (ref-ARRAY['snapshot_id','content_hash','call_id'])='{}'::jsonb
   AND ref->>'content_hash'=s.content_hash
   AND ref->>'call_id' ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$',false) THEN RETURN false; END IF;
  SELECT * INTO c FROM agent_tool_calls WHERE tenant_id=s.tenant_id AND run_id=r.id AND id=(ref->>'call_id')::uuid;
  IF c.id IS NULL OR c.tool<>'research.read' OR c.state<>'completed' OR c.error_code IS NOT NULL OR c.receipt_id IS NOT NULL
   OR c.result->>'snapshot_id' IS DISTINCT FROM s.id::text OR c.result->>'content_hash' IS DISTINCT FROM s.content_hash
   THEN RETURN false; END IF;
 ELSE RETURN false;
 END IF;
 RETURN true;
EXCEPTION WHEN data_exception THEN RETURN false;
END $function$""",
    r"""CREATE FUNCTION public.kernel_snapshot_registration_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $function$
DECLARE s public_web_snapshots; a action_receipts; r agent_runs; sx xid; ax xid;
BEGIN
 SELECT * INTO s FROM public_web_snapshots WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 SELECT * INTO a FROM action_receipts WHERE tenant_id=s.tenant_id AND id=s.receipt_id;
 -- The absence of this new marker never upgrades a legacy registration to proof.
 IF NOT coalesce(a.result ? 'proof_version',false) THEN RETURN NULL; END IF;
 SELECT * INTO r FROM agent_runs WHERE tenant_id=s.tenant_id AND id=s.registered_by_run_id;
 SELECT xmin INTO sx FROM public_web_snapshots WHERE tenant_id=s.tenant_id AND id=s.id;
 SELECT xmin INTO ax FROM action_receipts WHERE tenant_id=s.tenant_id AND id=a.id;
 IF kernel_snapshot_registration_proven(s) IS DISTINCT FROM true OR sx IS DISTINCT FROM ax
  OR r.state NOT IN ('queued','running','waiting_input','completed','partial') OR r.reverted_at IS NOT NULL
  OR s.tenant_id IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
  OR a.actor_id IS DISTINCT FROM scope_actor() OR a.requester_id IS DISTINCT FROM scope_requester()
  OR category_access(s.tenant_id,s.category_id) IS DISTINCT FROM true
  OR NOT EXISTS(SELECT 1 FROM principals WHERE tenant_id=s.tenant_id AND id=r.requester_id AND active)
  OR NOT EXISTS(SELECT 1 FROM principals WHERE tenant_id=s.tenant_id AND id=r.writer_id AND active) THEN
  RAISE EXCEPTION 'Marked snapshot registration requires its exact current committed provenance' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $function$""",
    r"""CREATE FUNCTION public.kernel_snapshot_page_proven(c agent_tool_calls) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $function$
DECLARE r agent_runs; m agent_tool_calls; s public_web_snapshots; b jsonb=c.execution_binding;
 request jsonb; args jsonb; expected jsonb; response_position integer; start_at integer; end_at integer; body text;
BEGIN
 IF c.state<>'completed' OR c.tool<>'research.read' OR c.error_code IS NOT NULL OR c.receipt_id IS NOT NULL
  OR b->>'kind' IS DISTINCT FROM 'read' OR b->>'read_kind' IS DISTINCT FROM 'registered_snapshot/v1'
  OR b->>'isolation' IS DISTINCT FROM 'research' OR jsonb_typeof(c.result) IS DISTINCT FROM 'object'
  OR NOT coalesce(b->>'model_call_id' ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
   AND jsonb_typeof(b->'response_index')='number' AND b->>'response_index' ~ '^(0|[1-9][0-9]*)$'
   AND (b->>'response_index')::numeric<=2147483647
   AND jsonb_typeof(b->'page_chars')='number' AND b->>'page_chars' ~ '^[1-9][0-9]*$'
   AND (b->>'page_chars')::numeric BETWEEN 1 AND 200000
   AND c.result->>'snapshot_id' ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$',false) THEN RETURN false; END IF;
 SELECT * INTO r FROM agent_runs WHERE tenant_id=c.tenant_id AND id=c.run_id;
 IF r.id IS NULL OR r.tenant_id IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
  OR r.requester_id IS DISTINCT FROM scope_requester()
  OR (scope_actor() IN (r.writer_id,r.requester_id)) IS DISTINCT FROM true
  OR r.state NOT IN ('queued','running','waiting_input','completed','partial') OR r.reverted_at IS NOT NULL
  OR r.category_id IS NULL OR category_access(r.tenant_id,r.category_id) IS DISTINCT FROM true
  OR NOT EXISTS(SELECT 1 FROM principals p JOIN grants g ON g.tenant_id=p.tenant_id AND g.principal_id=p.id
   WHERE p.tenant_id=r.tenant_id AND p.id=r.writer_id AND p.kind='agent' AND p.active
    AND g.category_id=r.category_id AND (g.expires_at IS NULL OR g.expires_at>statement_timestamp())) THEN RETURN false; END IF;
 SELECT * INTO s FROM public_web_snapshots WHERE tenant_id=r.tenant_id AND category_id=r.category_id
  AND id=(c.result->>'snapshot_id')::uuid;
 IF s.id IS NULL OR s.visibility<>'category' OR s.status NOT IN ('ok','partial')
  OR m3_evidence_source_reader(r.tenant_id,r.category_id,'snapshot',s.id) IS DISTINCT FROM true
  OR kernel_snapshot_registration_proven(s) IS DISTINCT FROM true THEN RETURN false; END IF;
 response_position=(b->>'response_index')::integer;
 SELECT * INTO m FROM agent_tool_calls WHERE tenant_id=r.tenant_id AND run_id=r.id AND id=(b->>'model_call_id')::uuid;
 IF m.id IS NULL OR m.id=c.id OR m.tool<>'model' OR m.state<>'completed'
  OR m.error_code IS NOT NULL OR m.receipt_id IS NOT NULL
  OR m.execution_binding->>'kind' IS DISTINCT FROM 'model'
  OR m.execution_binding->>'isolation' IS DISTINCT FROM 'research'
  OR m.execution_binding->'cancel_epoch' IS DISTINCT FROM to_jsonb(r.cancel_epoch)
  OR m.execution_binding->'model_version' IS DISTINCT FROM r.versions->'model_version'
  OR m.execution_binding->'model_route_digest' IS DISTINCT FROM r.versions->'model_route_digest'
  OR m.execution_binding->'tool_definitions_digest' IS DISTINCT FROM r.versions->'tool_definitions'->'research'
  OR m.execution_binding->'prompt_digest' IS DISTINCT FROM r.versions->'prompt_prefixes'->'research'
  OR jsonb_typeof(m.result->'calls') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 expected=jsonb_build_object(
  'kind','read','read_kind','registered_snapshot/v1','proof_version',1,'graph','xiaopai','step','tools',
  'isolation','research','tenant_id',r.tenant_id,'category_id',r.category_id,
  'run_id',r.id,'session_id',r.session_id,'requester_id',r.requester_id,'writer_id',r.writer_id,
  'product_id',r.product_id,'proposal_id',r.proposal_id,'cancel_epoch',r.cancel_epoch,
  'private_context',r.private_context,
  'data_categories',(SELECT coalesce(jsonb_agg(value ORDER BY value COLLATE "C"),'[]'::jsonb) FROM jsonb_array_elements_text(r.data_categories)),
  'customer_identities',r.customer_identities,'tool',c.tool,
  'call_key','agent:'||r.id::text||':model:'||m.id::text||':'||response_position::text,
  'model_call_id',m.id,'response_index',response_position,
  'model_version',m.execution_binding->'model_version',
  'model_route_digest',m.execution_binding->'model_route_digest',
  'tool_definitions_digest',m.execution_binding->'tool_definitions_digest',
  'prompt_digest',m.execution_binding->'prompt_digest','page_chars',b->'page_chars');
 request=m.result->'calls'->response_position; args=request->'arguments';
 IF b IS DISTINCT FROM expected OR c.call_key IS DISTINCT FROM expected->>'call_key'
  OR NOT coalesce(jsonb_typeof(request)='object' AND request->>'name'=c.tool
   AND jsonb_typeof(args)='object' AND (args-ARRAY['url','cursor'])='{}'::jsonb
   AND jsonb_typeof(args->'url')='string' AND args->>'url' IN (s.url,s.final_url)
   AND (NOT (args ? 'cursor') OR (jsonb_typeof(args->'cursor')='number'
    AND args->>'cursor' ~ '^(0|[1-9][0-9]*)$' AND (args->>'cursor')::numeric<=2147483647)),false)
  OR c.input_digest IS DISTINCT FROM encode(sha256(convert_to(
   kernel_read_canonical_json(jsonb_build_array(c.tool,args)),'UTF8')),'hex') THEN RETURN false; END IF;
 start_at=coalesce((args->>'cursor')::integer,0);
 -- PostgreSQL character offsets and Python string slices both count Unicode
 -- code points; substring is 1-based while persisted cursor/end remain 0-based.
 end_at=least(start_at::bigint+(b->>'page_chars')::integer,char_length(s.markdown))::integer;
 IF start_at>=end_at THEN RETURN false; END IF;
 body=substring(s.markdown FROM start_at+1 FOR end_at-start_at);
 expected=jsonb_build_object('proof_kind','registered_snapshot_page','proof_version',1,
  'snapshot_id',s.id,'version',1,'content_hash',s.content_hash,'registration_receipt_id',s.receipt_id,
  'source_status',s.status,'cursor',start_at,'end',end_at,
  'locator','chars:'||start_at::text||':'||end_at::text,'markdown',body,
  'page_hash',encode(sha256(convert_to(body,'UTF8')),'hex'),
  'next_cursor',CASE WHEN end_at<char_length(s.markdown) THEN end_at ELSE NULL END);
 RETURN c.result IS NOT DISTINCT FROM expected;
EXCEPTION WHEN data_exception THEN RETURN false;
END $function$""",
    r"""CREATE FUNCTION public.kernel_snapshot_page_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $function$
BEGIN
 IF NEW.execution_binding->>'read_kind'='registered_snapshot/v1' AND NEW.state='completed'
  AND kernel_snapshot_page_proven(NEW) IS DISTINCT FROM true THEN
  RAISE EXCEPTION 'Registered snapshot read requires exact registered Unicode page proof' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $function$""",
    r"""CREATE FUNCTION public.m3_snapshot_claim_read_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $function$
DECLARE s public_web_snapshots; c agent_tool_calls; part text; line_body text;
 line_index integer=0; offset_at integer=0; start_at integer; end_at integer;
BEGIN
 IF NEW.origin<>'ai_draft' OR NEW.source_kind<>'snapshot' THEN RETURN NEW; END IF;
 SELECT * INTO s FROM public_web_snapshots WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.snapshot_id;
 IF s.id IS NULL THEN RAISE EXCEPTION 'Snapshot Claim source unavailable' USING ERRCODE='23514'; END IF;
 -- The retained same-Run registration path keeps its predecessor source checks.
 IF s.registered_by_run_id=NEW.run_id THEN RETURN NEW; END IF;
 IF NEW.source_revision<>1 OR NEW.run_id IS NULL OR NEW.line<1 OR NEW.quote='' THEN
  RAISE EXCEPTION 'Cross-Run snapshot Claim requires an exact source line and quote' USING ERRCODE='23514';
 END IF;
 -- Python splitlines(keepends=True): CRLF is one boundary; Unicode line/paragraph
 -- separators, NEL, vertical tab, form feed and record separators are boundaries.
 FOR part IN SELECT captures[1] FROM regexp_matches(s.markdown,
  E'([^\\r\\n\\v\\f\\x1c\\x1d\\x1e\\u0085\\u2028\\u2029]*(?:\\r\\n|[\\r\\n\\v\\f\\x1c\\x1d\\x1e\\u0085\\u2028\\u2029]|$))','g') AS pieces(captures) LOOP
  IF part='' THEN CONTINUE; END IF;
  line_index=line_index+1;
  IF line_index=NEW.line THEN
   line_body=regexp_replace(part,E'(\\r\\n|[\\r\\n\\v\\f\\x1c\\x1d\\x1e\\u0085\\u2028\\u2029])$','');
   EXIT;
  END IF;
  offset_at=offset_at+char_length(part);
 END LOOP;
 IF line_body IS NULL THEN RAISE EXCEPTION 'Snapshot Claim line unavailable' USING ERRCODE='23514'; END IF;
 FOR c IN SELECT * FROM agent_tool_calls WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id
  AND state='completed' AND tool='research.read' AND execution_binding->>'read_kind'='registered_snapshot/v1'
  AND result->>'snapshot_id'=s.id::text LOOP
  IF kernel_snapshot_page_proven(c) THEN
   start_at=greatest(0,(c.result->>'cursor')::integer-offset_at);
   end_at=least(char_length(line_body),(c.result->>'end')::integer-offset_at);
   IF start_at<end_at AND position(NEW.quote IN substring(line_body FROM start_at+1 FOR end_at-start_at))>0 THEN RETURN NEW; END IF;
  END IF;
 END LOOP;
 RAISE EXCEPTION 'Cross-Run snapshot Claim requires its current Run page covering the exact quote' USING ERRCODE='23514';
END $function$""",
    "REVOKE ALL ON FUNCTION public.kernel_snapshot_registration_proven(public_web_snapshots) FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch",
    "REVOKE ALL ON FUNCTION public.kernel_snapshot_registration_guard() FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch",
    "REVOKE ALL ON FUNCTION public.kernel_snapshot_page_proven(agent_tool_calls) FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch",
    "REVOKE ALL ON FUNCTION public.kernel_snapshot_page_guard() FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch",
    "REVOKE ALL ON FUNCTION public.m3_snapshot_claim_read_guard() FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch",
    "CREATE CONSTRAINT TRIGGER kernel_snapshot_registration_provenance AFTER INSERT ON public.public_web_snapshots DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.kernel_snapshot_registration_guard()",
    "CREATE TRIGGER kernel_snapshot_page_provenance BEFORE INSERT OR UPDATE ON public.agent_tool_calls FOR EACH ROW EXECUTE FUNCTION public.kernel_snapshot_page_guard()",
    "CREATE TRIGGER m3_snapshot_claim_read_provenance BEFORE INSERT ON public.claims FOR EACH ROW EXECUTE FUNCTION public.m3_snapshot_claim_read_guard()",
)

DOWNGRADE_SQL = (
    "DROP TRIGGER m3_snapshot_claim_read_provenance ON public.claims",
    "DROP TRIGGER kernel_snapshot_page_provenance ON public.agent_tool_calls",
    "DROP TRIGGER kernel_snapshot_registration_provenance ON public.public_web_snapshots",
    "DROP FUNCTION public.m3_snapshot_claim_read_guard()",
    "DROP FUNCTION public.kernel_snapshot_page_guard()",
    "DROP FUNCTION public.kernel_snapshot_page_proven(agent_tool_calls)",
    "DROP FUNCTION public.kernel_snapshot_registration_guard()",
    "DROP FUNCTION public.kernel_snapshot_registration_proven(public_web_snapshots)",
)
