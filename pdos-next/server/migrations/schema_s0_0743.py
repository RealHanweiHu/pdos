# ruff: noqa: E501
"""Frozen read provenance and exact computed-Claim consumer guards.

Additive to the actual 0742 catalog: predecessor call immutability, terminal
semantics, RLS, business grants and claim source/receipt guards remain intact.
Canonical JSON deliberately rejects floating-point JSON numbers: PostgreSQL
jsonb cannot reconstruct their original Python int/float representation. Read
proof arguments use exact integers or decimal strings until that contract changes.
"""

SCHEMA_SQL = (
    r"""CREATE FUNCTION public.kernel_read_canonical_json(value jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT
SET search_path=pg_catalog,public,pg_temp AS $function$
DECLARE result text;
BEGIN
 CASE jsonb_typeof(value)
 WHEN 'object' THEN
  SELECT '{'||coalesce(string_agg(to_jsonb(key)::text||':'||public.kernel_read_canonical_json(item),',' ORDER BY key COLLATE "C"),'')||'}'
   INTO result FROM jsonb_each(value) AS fields(key,item);
 WHEN 'array' THEN
  SELECT '['||coalesce(string_agg(public.kernel_read_canonical_json(item),',' ORDER BY ord),'')||']'
   INTO result FROM jsonb_array_elements(value) WITH ORDINALITY AS items(item,ord);
 WHEN 'number' THEN
  IF value::text !~ '^-?(0|[1-9][0-9]*)$' THEN
   RAISE EXCEPTION 'Read proof JSON numbers require exact integers or decimal strings' USING ERRCODE='23514';
  END IF;
  result=value::text;
 ELSE result=value::text;
 END CASE;
 RETURN result;
END $function$""",
    r"""CREATE FUNCTION public.kernel_read_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $function$
DECLARE b jsonb=NEW.execution_binding; r agent_runs; m agent_tool_calls;
 expected jsonb; request jsonb; response_position integer; isolation text; read_kind_value text;
BEGIN
 -- Legacy reads are operational history, never a new proof. Existing immutable
 -- execution_binding and terminal guards still govern every update.
 IF NOT (b ? 'read_kind') THEN RETURN NEW; END IF;
 IF b->>'kind' IS DISTINCT FROM 'read' THEN
  RAISE EXCEPTION 'Read provenance requires read binding' USING ERRCODE='23514';
 END IF;
 -- The controlled technical release must remain possible after cancellation or
 -- ACL withdrawal. It cannot create a completed proof or alter its binding.
 IF TG_OP='UPDATE' AND NEW.state IN ('failed','unknown')
  AND NEW.execution_binding IS NOT DISTINCT FROM OLD.execution_binding THEN RETURN NEW; END IF;
 IF NOT coalesce(jsonb_typeof(b)='object'
  AND b->>'read_kind' IN ('ordinary/v1','compute/v1','registered_snapshot/v1')
  AND jsonb_typeof(b->'response_index')='number'
  AND b->>'response_index' ~ '^(0|[1-9][0-9]*)$'
  AND length(b->>'response_index')<=10
  AND (b->>'response_index')::numeric<=2147483647
  AND b->>'model_call_id' ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
  AND b->>'isolation' IN ('main','research','extract','mcp'),false) THEN
  RAISE EXCEPTION 'Read provenance shape invalid' USING ERRCODE='23514';
 END IF;
 response_position=(b->>'response_index')::integer; isolation=b->>'isolation'; read_kind_value=b->>'read_kind';
 SELECT * INTO r FROM agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id FOR SHARE;
 IF r.id IS NULL OR r.tenant_id IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
  OR r.requester_id IS DISTINCT FROM scope_requester() OR r.writer_id IS DISTINCT FROM scope_actor()
  OR r.state NOT IN ('queued','running','waiting_input') OR r.reverted_at IS NOT NULL
  OR NOT EXISTS(SELECT 1 FROM principals WHERE tenant_id=r.tenant_id AND id=r.writer_id AND active AND kind='agent')
  OR NOT EXISTS(SELECT 1 FROM principals WHERE tenant_id=r.tenant_id AND id=r.requester_id AND active AND kind='human')
  OR (r.category_id IS NOT NULL AND category_access(r.tenant_id,r.category_id) IS DISTINCT FROM true) THEN
  RAISE EXCEPTION 'Read provenance requires current active Run and principals' USING ERRCODE='23514';
 END IF;
 SELECT * INTO m FROM agent_tool_calls WHERE tenant_id=r.tenant_id AND run_id=r.id AND id=(b->>'model_call_id')::uuid;
 IF m.id IS NULL OR m.id=NEW.id OR m.tool<>'model' OR m.state<>'completed'
  OR m.error_code IS NOT NULL OR m.receipt_id IS NOT NULL
  OR m.execution_binding->>'kind' IS DISTINCT FROM 'model'
  OR m.execution_binding->>'isolation' IS DISTINCT FROM isolation
  OR m.execution_binding->'cancel_epoch' IS DISTINCT FROM to_jsonb(r.cancel_epoch)
  OR m.execution_binding->'model_version' IS DISTINCT FROM r.versions->'model_version'
  OR m.execution_binding->'model_route_digest' IS DISTINCT FROM r.versions->'model_route_digest'
  OR m.execution_binding->'tool_definitions_digest' IS DISTINCT FROM r.versions->'tool_definitions'->isolation
  OR m.execution_binding->'prompt_digest' IS DISTINCT FROM r.versions->'prompt_prefixes'->isolation
  OR jsonb_typeof(m.result->'calls') IS DISTINCT FROM 'array'
  OR NEW.tool IN ('model','skill.load') OR NEW.receipt_id IS NOT NULL THEN
  RAISE EXCEPTION 'Read provenance requires actual completed model response' USING ERRCODE='23514';
 END IF;
 IF NOT coalesce(jsonb_typeof(m.execution_binding->'model_version')='string'
  AND length(m.execution_binding->>'model_version') BETWEEN 1 AND 160
  AND jsonb_typeof(m.execution_binding->'model_route_digest')='string'
  AND m.execution_binding->>'model_route_digest' ~ '^[a-f0-9]{64}$'
  AND jsonb_typeof(m.execution_binding->'tool_definitions_digest')='string'
  AND m.execution_binding->>'tool_definitions_digest' ~ '^[a-f0-9]{64}$'
  AND jsonb_typeof(m.execution_binding->'prompt_digest')='string'
  AND m.execution_binding->>'prompt_digest' ~ '^[a-f0-9]{64}$',false) THEN
  RAISE EXCEPTION 'Read model version facts invalid' USING ERRCODE='23514';
 END IF;
 expected=jsonb_build_object(
  'kind','read','read_kind',read_kind_value,'proof_version',1,'graph','xiaopai','step','tools',
  'isolation',isolation,'tenant_id',r.tenant_id,'category_id',r.category_id,
  'run_id',r.id,'session_id',r.session_id,'requester_id',r.requester_id,'writer_id',r.writer_id,
  'product_id',r.product_id,'proposal_id',r.proposal_id,'cancel_epoch',r.cancel_epoch,
  'private_context',r.private_context,
  'data_categories',(SELECT coalesce(jsonb_agg(value ORDER BY value COLLATE "C"),'[]'::jsonb) FROM jsonb_array_elements_text(r.data_categories)),
  'customer_identities',r.customer_identities,'tool',NEW.tool,
  'call_key','agent:'||r.id::text||':model:'||m.id::text||':'||response_position::text,
  'model_call_id',m.id,'response_index',response_position,
  'model_version',m.execution_binding->'model_version',
  'model_route_digest',m.execution_binding->'model_route_digest',
  'tool_definitions_digest',m.execution_binding->'tool_definitions_digest',
  'prompt_digest',m.execution_binding->'prompt_digest');
 IF read_kind_value='compute/v1' THEN
  IF isolation<>'main' OR NEW.tool NOT IN ('calc.market_size','calc.opportunity_score','calc.cost_subtotal','calc.spec_compare','calc.price_band','calc.derivation_diff')
   OR NOT coalesce(jsonb_typeof(b->'engine_version')='string'
    AND length(b->>'engine_version') BETWEEN 1 AND 160
    AND jsonb_typeof(b->'result_digest')='string'
    AND b->>'result_digest' ~ '^[a-f0-9]{64}$',false) THEN
   RAISE EXCEPTION 'Compute read provenance invalid' USING ERRCODE='23514';
  END IF;
  expected=expected||jsonb_build_object('engine_version',b->'engine_version','result_digest',b->'result_digest');
 ELSIF read_kind_value='registered_snapshot/v1' THEN
  IF isolation<>'research' OR NEW.tool<>'research.read' OR r.category_id IS NULL
   OR NOT coalesce(jsonb_typeof(b->'page_chars')='number'
    AND b->>'page_chars' ~ '^[1-9][0-9]*$'
    AND (b->>'page_chars')::numeric BETWEEN 1 AND 200000,false) THEN
   RAISE EXCEPTION 'Snapshot read provenance invalid' USING ERRCODE='23514';
  END IF;
  expected=expected||jsonb_build_object('page_chars',b->'page_chars');
 END IF;
 IF b IS DISTINCT FROM expected OR NEW.call_key IS DISTINCT FROM expected->>'call_key' THEN
  RAISE EXCEPTION 'Read binding must retain every exact immutable Run/model fact' USING ERRCODE='23514';
 END IF;
 request=m.result->'calls'->response_position;
 IF NOT coalesce(jsonb_typeof(request)='object' AND request->>'name'=NEW.tool
  AND jsonb_typeof(request->'arguments')='object',false)
  OR NEW.input_digest IS DISTINCT FROM encode(sha256(convert_to(
   public.kernel_read_canonical_json(jsonb_build_array(NEW.tool,request->'arguments')),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Read input must match its actual model response position' USING ERRCODE='23514';
 END IF;
 IF NEW.state='completed' THEN
  IF NEW.error_code IS NOT NULL OR jsonb_typeof(NEW.result) IS DISTINCT FROM 'object' THEN
   RAISE EXCEPTION 'Completed read requires a successful object result' USING ERRCODE='23514';
  END IF;
  IF read_kind_value='compute/v1' AND (
   NEW.result->'engine_version' IS DISTINCT FROM b->'engine_version'
   OR NEW.result->>'input_digest' IS DISTINCT FROM NEW.input_digest
   OR b->>'result_digest' IS DISTINCT FROM encode(sha256(convert_to(public.kernel_read_canonical_json(NEW.result),'UTF8')),'hex')) THEN
   RAISE EXCEPTION 'Compute result must match its immutable complete result digest' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $function$""",
    r"""CREATE FUNCTION public.m3_computed_claim_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $function$
DECLARE c agent_tool_calls; r agent_runs; m agent_tool_calls; b jsonb; selected jsonb; expected jsonb; request jsonb; response_position integer;
BEGIN
 IF NEW.origin<>'ai_draft' OR NEW.nature<>'computed' THEN RETURN NEW; END IF;
 IF NOT coalesce(jsonb_typeof(NEW.extraction_ref)='object'
  AND NEW.extraction_ref ?& ARRAY['call_id','result_path']
  AND (NEW.extraction_ref-ARRAY['call_id','result_path'])='{}'::jsonb
  AND NEW.extraction_ref->>'call_id' ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
  AND NEW.extraction_ref->'result_path'='["proof_claims","single_currency_subtotal"]'::jsonb,false) THEN
  RAISE EXCEPTION 'Computed Claim requires a closed exact proof reference' USING ERRCODE='23514';
 END IF;
 SELECT * INTO r FROM agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id FOR SHARE;
 SELECT * INTO c FROM agent_tool_calls WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id
  AND id=(NEW.extraction_ref->>'call_id')::uuid;
 b=c.execution_binding;
 IF r.id IS NULL OR c.id IS NULL OR r.tenant_id IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
  OR r.category_id IS DISTINCT FROM NEW.category_id OR r.product_id IS DISTINCT FROM NEW.product_id
  OR r.proposal_id IS DISTINCT FROM NEW.proposal_id OR r.requester_id<>NEW.human_owner_id OR r.writer_id<>NEW.writer_id
  OR r.requester_id IS DISTINCT FROM scope_requester() OR (scope_actor() IN (r.writer_id,r.requester_id)) IS DISTINCT FROM true
  OR r.state NOT IN ('queued','running','waiting_input','completed','partial') OR r.reverted_at IS NOT NULL
  OR c.state<>'completed' OR c.error_code IS NOT NULL OR c.receipt_id IS NOT NULL OR c.tool<>'calc.cost_subtotal'
  OR b->>'kind' IS DISTINCT FROM 'read' OR b->>'read_kind' IS DISTINCT FROM 'compute/v1'
  OR b->>'isolation' IS DISTINCT FROM 'main' OR b->'cancel_epoch' IS DISTINCT FROM to_jsonb(r.cancel_epoch)
  OR b->>'run_id' IS DISTINCT FROM r.id::text OR b->>'requester_id' IS DISTINCT FROM r.requester_id::text
  OR b->>'writer_id' IS DISTINCT FROM r.writer_id::text
  OR b->>'model_version' IS DISTINCT FROM r.versions->>'model_version'
  OR b->>'model_route_digest' IS DISTINCT FROM r.versions->>'model_route_digest'
  OR b->>'tool_definitions_digest' IS DISTINCT FROM r.versions->'tool_definitions'->>'main'
  OR b->>'prompt_digest' IS DISTINCT FROM r.versions->'prompt_prefixes'->>'main'
  OR category_access(r.tenant_id,r.category_id) IS DISTINCT FROM true
  OR NOT EXISTS(SELECT 1 FROM principals p JOIN grants g ON g.tenant_id=p.tenant_id AND g.principal_id=p.id
   WHERE p.tenant_id=r.tenant_id AND p.id=r.writer_id AND p.kind='agent' AND p.active
    AND g.category_id=r.category_id AND (g.expires_at IS NULL OR g.expires_at>statement_timestamp())) THEN
  RAISE EXCEPTION 'Computed Claim requires current same-Run completed computation' USING ERRCODE='23514';
 END IF;
 -- Recheck historical rows, including those predating this migration; a
 -- self-declared new read_kind on a predecessor row is not itself evidence.
 IF NOT coalesce(jsonb_typeof(b->'response_index')='number'
  AND b->>'response_index' ~ '^(0|[1-9][0-9]*)$'
  AND length(b->>'response_index')<=10 AND (b->>'response_index')::numeric<=2147483647
  AND b->>'model_call_id' ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
  AND jsonb_typeof(b->'engine_version')='string' AND length(b->>'engine_version') BETWEEN 1 AND 160
  AND jsonb_typeof(b->'result_digest')='string' AND b->>'result_digest' ~ '^[a-f0-9]{64}$',false) THEN
  RAISE EXCEPTION 'Computed Claim proof shape invalid' USING ERRCODE='23514';
 END IF;
 response_position=(b->>'response_index')::integer;
 SELECT * INTO m FROM agent_tool_calls WHERE tenant_id=r.tenant_id AND run_id=r.id AND id=(b->>'model_call_id')::uuid;
 IF m.id IS NULL OR m.id=c.id OR m.tool<>'model' OR m.state<>'completed'
  OR m.error_code IS NOT NULL OR m.receipt_id IS NOT NULL
  OR m.execution_binding->>'kind' IS DISTINCT FROM 'model'
  OR m.execution_binding->>'isolation' IS DISTINCT FROM 'main'
  OR m.execution_binding->'cancel_epoch' IS DISTINCT FROM to_jsonb(r.cancel_epoch)
  OR jsonb_typeof(m.result->'calls') IS DISTINCT FROM 'array'
  OR (m.execution_binding->'model_version') IS DISTINCT FROM b->'model_version'
  OR (m.execution_binding->'model_route_digest') IS DISTINCT FROM b->'model_route_digest'
  OR (m.execution_binding->'tool_definitions_digest') IS DISTINCT FROM b->'tool_definitions_digest'
  OR (m.execution_binding->'prompt_digest') IS DISTINCT FROM b->'prompt_digest' THEN
  RAISE EXCEPTION 'Computed Claim requires its actual model execution' USING ERRCODE='23514';
 END IF;
 expected=jsonb_build_object(
  'kind','read','read_kind','compute/v1','proof_version',1,'graph','xiaopai','step','tools',
  'isolation','main','tenant_id',r.tenant_id,'category_id',r.category_id,
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
  'prompt_digest',m.execution_binding->'prompt_digest',
  'engine_version',b->'engine_version','result_digest',b->'result_digest');
 request=m.result->'calls'->response_position;
 IF b IS DISTINCT FROM expected OR c.call_key IS DISTINCT FROM expected->>'call_key'
  OR NOT coalesce(jsonb_typeof(request)='object' AND request->>'name'=c.tool
   AND jsonb_typeof(request->'arguments')='object',false)
  OR c.input_digest IS DISTINCT FROM encode(sha256(convert_to(
   public.kernel_read_canonical_json(jsonb_build_array(c.tool,request->'arguments')),'UTF8')),'hex')
  OR c.result->'engine_version' IS DISTINCT FROM b->'engine_version'
  OR c.result->>'input_digest' IS DISTINCT FROM c.input_digest THEN
  RAISE EXCEPTION 'Computed Claim read facts must match actual model input and Run' USING ERRCODE='23514';
 END IF;
 selected=c.result#>ARRAY['proof_claims','single_currency_subtotal'];
 IF jsonb_typeof(selected) IS DISTINCT FROM 'object' OR NEW.content IS DISTINCT FROM selected
  OR b->>'result_digest' IS DISTINCT FROM encode(sha256(convert_to(public.kernel_read_canonical_json(c.result),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Computed Claim content must equal the complete selected result' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $function$""",
    "REVOKE ALL ON FUNCTION public.kernel_read_canonical_json(jsonb) FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch",
    "REVOKE ALL ON FUNCTION public.kernel_read_guard() FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch",
    "REVOKE ALL ON FUNCTION public.m3_computed_claim_guard() FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch",
    "CREATE TRIGGER kernel_read_provenance BEFORE INSERT OR UPDATE ON public.agent_tool_calls FOR EACH ROW EXECUTE FUNCTION public.kernel_read_guard()",
    "CREATE TRIGGER m3_computed_claim_provenance BEFORE INSERT ON public.claims FOR EACH ROW EXECUTE FUNCTION public.m3_computed_claim_guard()",
)

DOWNGRADE_SQL = (
    "DROP TRIGGER m3_computed_claim_provenance ON public.claims",
    "DROP TRIGGER kernel_read_provenance ON public.agent_tool_calls",
    "DROP FUNCTION public.m3_computed_claim_guard()",
    "DROP FUNCTION public.kernel_read_guard()",
    "DROP FUNCTION public.kernel_read_canonical_json(jsonb)",
)
