# ruff: noqa: E501
"""Frozen personal-Run category candidate and named initial-material provenance."""

SCHEMA_SQL = ('CREATE FUNCTION public.kernel_category_candidate_normalize(v jsonb, shape text) RETURNS jsonb\n'
 'LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $function$\n'
 'DECLARE defaults jsonb; result jsonb; item jsonb; key text; child_shape text; assembled jsonb;\n'
 'BEGIN\n'
 " IF jsonb_typeof(v) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'Candidate object expected' "
 "USING ERRCODE='23514'; END IF;\n"
 ' CASE shape\n'
 " WHEN 'candidate' THEN "
 'defaults=\'{"groups":{"knowledge":[],"parameters":[],"snapshot_refs":[]}}\';\n'
 ' WHEN \'groups\' THEN defaults=\'{"knowledge":[],"parameters":[],"snapshot_refs":[]}\';\n'
 ' WHEN \'knowledge\' THEN defaults=\'{"regions":[],"source_refs":[]}\';\n'
 " WHEN 'parameter' THEN "
 'defaults=\'{"enum_values":null,"unit":null,"standard_condition":null,"method":null,"acceptance_criterion":null}\';\n'
 ' WHEN \'reference\' THEN defaults=\'{"line":null,"quote":null,"statement":null}\';\n'
 " WHEN 'snapshot_ref' THEN defaults='{}';\n"
 " WHEN 'boundary' THEN "
 'defaults=\'{"includes":[],"excludes":[],"criteria":[],"criteria_note":null,"edge_cases":[],"classification_rule":null,"decision_record":null,"material":{}}\';\n'
 " WHEN 'segment' THEN "
 'defaults=\'{"jtbd":[],"buying_criteria":[],"channels":[],"regions":[],"material":{}}\';\n'
 ' WHEN \'competitor\' THEN defaults=\'{"metrics":[],"features":[],"prices":[]}\';\n'
 " WHEN 'metric' THEN "
 'defaults=\'{"value":null,"lower":null,"upper":null,"text":null,"unit":null,"condition_note":null,"source_ref":null}\';\n'
 " WHEN 'price' THEN "
 'defaults=\'{"amount":null,"currency":null,"observed_on":null,"price_type":"unknown","includes_tax":null,"includes_shipping":null,"channel":null,"region":null,"source_ref":null}\';\n'
 ' WHEN \'voice\' THEN defaults=\'{"representative_refs":[]}\';\n'
 " WHEN 'regulation' THEN "
 'defaults=\'{"applicability":null,"classification_state":"ai_draft","material":{}}\';\n'
 ' WHEN \'research_question\' THEN defaults=\'{"assumption":null}\';\n'
 " ELSE RAISE EXCEPTION 'Unknown candidate object shape' USING ERRCODE='23514';\n"
 ' END CASE;\n'
 ' result=defaults||v;\n'
 ' -- Only typed DTO strings are trimmed. Opaque material/assumption dictionaries\n'
 ' -- and their internal values remain exactly as supplied by the actual model.\n'
 ' FOR key,item IN SELECT * FROM jsonb_each(result) LOOP\n'
 "  IF jsonb_typeof(item)='string' AND key NOT IN "
 "('type','kind','value_type','direction','nature','price_type') THEN\n"
 '   '
 "result=jsonb_set(result,ARRAY[key],to_jsonb(regexp_replace(item#>>'{}','^[[:space:]]+|[[:space:]]+$','','g')));\n"
 '  END IF;\n'
 ' END LOOP;\n'
 " IF shape='candidate' THEN "
 "result=jsonb_set(result,'{groups}',kernel_category_candidate_normalize(result->'groups','groups')); "
 'END IF;\n'
 " IF shape='knowledge' THEN "
 "result=jsonb_set(result,'{content}',kernel_category_candidate_normalize(result->'content',result->>'kind')); "
 'END IF;\n'
 ' FOR key,item IN SELECT * FROM jsonb_each(result) LOOP\n'
 "  child_shape=CASE WHEN shape='groups' AND key='knowledge' THEN 'knowledge'\n"
 "   WHEN shape='groups' AND key='parameters' THEN 'parameter'\n"
 "   WHEN shape='groups' AND key='snapshot_refs' THEN 'snapshot_ref'\n"
 "   WHEN shape='knowledge' AND key='source_refs' THEN 'reference'\n"
 "   WHEN shape='voice' AND key='representative_refs' THEN 'reference'\n"
 "   WHEN shape='competitor' AND key IN ('metrics','features') THEN 'metric'\n"
 "   WHEN shape='competitor' AND key='prices' THEN 'price' ELSE NULL END;\n"
 '  IF child_shape IS NOT NULL THEN\n'
 '   SELECT coalesce(jsonb_agg(kernel_category_candidate_normalize(entry,child_shape) ORDER BY '
 "ord),'[]'::jsonb)\n"
 '    INTO assembled FROM jsonb_array_elements(item) WITH ORDINALITY entries(entry,ord);\n'
 '   result=jsonb_set(result,ARRAY[key],assembled);\n'
 "  ELSIF shape IN ('metric','price') AND key='source_ref' AND item<>'null'::jsonb THEN\n"
 "   result=jsonb_set(result,ARRAY[key],kernel_category_candidate_normalize(item,'reference'));\n"
 "  ELSIF key IN ('edge_cases','buying_criteria') AND jsonb_typeof(item)='array' THEN\n"
 "   SELECT coalesce(jsonb_agg(CASE WHEN jsonb_typeof(entry)='string'\n"
 "    THEN to_jsonb(regexp_replace(entry#>>'{}','^[[:space:]]+|[[:space:]]+$','','g')) ELSE entry "
 "END ORDER BY ord),'[]'::jsonb)\n"
 '    INTO assembled FROM jsonb_array_elements(item) WITH ORDINALITY entries(entry,ord);\n'
 '   result=jsonb_set(result,ARRAY[key],assembled);\n'
 "  ELSIF key IN ('regions','includes','excludes','criteria','jtbd','channels','enum_values') AND "
 "jsonb_typeof(item)='array' THEN\n"
 '   SELECT '
 "coalesce(jsonb_agg(to_jsonb(regexp_replace(entry#>>'{}','^[[:space:]]+|[[:space:]]+$','','g')) "
 "ORDER BY ord),'[]'::jsonb)\n"
 '    INTO assembled FROM jsonb_array_elements(item) WITH ORDINALITY entries(entry,ord);\n'
 '   result=jsonb_set(result,ARRAY[key],assembled);\n'
 '  END IF;\n'
 ' END LOOP;\n'
 " IF shape='reference' THEN\n"
 "  result=jsonb_set(result,'{id}',to_jsonb((result->>'id')::uuid));\n"
 "  result=jsonb_set(result,'{version}',to_jsonb((result->>'version')::integer));\n"
 "  IF result->'line'<>'null'::jsonb THEN "
 "result=jsonb_set(result,'{line}',to_jsonb((result->>'line')::integer)); END IF;\n"
 " ELSIF shape='snapshot_ref' THEN "
 "result=jsonb_set(result,'{call_id}',to_jsonb((result->>'call_id')::uuid));\n"
 " ELSIF shape='metric' THEN\n"
 "  result=jsonb_set(result,'{parameter_id}',to_jsonb((result->>'parameter_id')::uuid));\n"
 '  '
 "result=jsonb_set(result,'{parameter_version}',to_jsonb((result->>'parameter_version')::integer));\n"
 ' END IF;\n'
 " -- Decimal fields serialize as exact strings; a metric's string/boolean value\n"
 ' -- is preserved by its union, whereas JSON number values select Decimal.\n'
 " FOR key IN SELECT unnest(CASE shape WHEN 'price' THEN ARRAY['amount'] WHEN 'metric' THEN "
 "ARRAY['lower','upper','value'] ELSE ARRAY[]::text[] END) LOOP\n"
 "  IF jsonb_typeof(result->key)='number' THEN "
 'result=jsonb_set(result,ARRAY[key],to_jsonb(result->>key)); END IF;\n'
 ' END LOOP;\n'
 ' RETURN result;\n'
 'END $function$',
 'CREATE FUNCTION public.kernel_category_snapshot_read_proven(t uuid, rid uuid, call_id uuid, sid '
 'uuid) RETURNS boolean\n'
 'LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS '
 '$function$\n'
 'DECLARE r agent_runs; c agent_tool_calls; m agent_tool_calls; s public_web_snapshots;\n'
 ' b jsonb; expected jsonb; request jsonb; args jsonb; idx integer; start_at integer; end_at '
 'integer;\n'
 ' stamp text; full_snapshot jsonb; bounds text[];\n'
 'BEGIN\n'
 ' SELECT * INTO r FROM agent_runs WHERE tenant_id=t AND id=rid;\n'
 ' SELECT * INTO c FROM agent_tool_calls WHERE tenant_id=t AND run_id=rid AND id=call_id;\n'
 ' SELECT * INTO s FROM public_web_snapshots WHERE tenant_id=t AND id=sid AND '
 'registered_by_run_id=rid;\n'
 ' b=c.execution_binding;\n'
 " IF r.id IS NULL OR c.id IS NULL OR s.id IS NULL OR c.state<>'completed' OR "
 "c.tool<>'research.read'\n"
 "  OR c.error_code IS NOT NULL OR c.receipt_id IS NOT NULL OR b->>'kind' IS DISTINCT FROM 'read'\n"
 "  OR b->>'read_kind' IS DISTINCT FROM 'ordinary/v1' OR b->>'isolation' IS DISTINCT FROM "
 "'research'\n"
 "  OR NOT coalesce(b->>'model_call_id' ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'\n"
 "   AND jsonb_typeof(b->'response_index')='number' AND b->>'response_index' ~ "
 "'^(0|[1-9][0-9]*)$'\n"
 "   AND (b->>'response_index')::numeric<=2147483647,false) THEN RETURN false; END IF;\n"
 " idx=(b->>'response_index')::integer;\n"
 ' SELECT * INTO m FROM agent_tool_calls WHERE tenant_id=t AND run_id=rid AND '
 "id=(b->>'model_call_id')::uuid;\n"
 " IF m.id IS NULL OR m.tool<>'model' OR m.state<>'completed' OR m.error_code IS NOT NULL OR "
 'm.receipt_id IS NOT NULL\n'
 "  OR m.execution_binding->>'kind' IS DISTINCT FROM 'model' OR m.execution_binding->>'isolation' "
 "IS DISTINCT FROM 'research'\n"
 "  OR m.execution_binding->'cancel_epoch' IS DISTINCT FROM to_jsonb(r.cancel_epoch)\n"
 "  OR m.execution_binding->'model_version' IS DISTINCT FROM r.versions->'model_version'\n"
 "  OR m.execution_binding->'model_route_digest' IS DISTINCT FROM "
 "r.versions->'model_route_digest'\n"
 "  OR m.execution_binding->'tool_definitions_digest' IS DISTINCT FROM "
 "r.versions->'tool_definitions'->'research'\n"
 "  OR m.execution_binding->'prompt_digest' IS DISTINCT FROM "
 "r.versions->'prompt_prefixes'->'research'\n"
 "  OR jsonb_typeof(m.result->'calls') IS DISTINCT FROM 'array' THEN RETURN false; END IF;\n"
 ' '
 "expected=jsonb_build_object('kind','read','read_kind','ordinary/v1','proof_version',1,'graph','xiaopai','step','tools',\n"
 '  '
 "'isolation','research','tenant_id',r.tenant_id,'category_id',r.category_id,'run_id',r.id,'session_id',r.session_id,\n"
 '  '
 "'requester_id',r.requester_id,'writer_id',r.writer_id,'product_id',r.product_id,'proposal_id',r.proposal_id,\n"
 "  'cancel_epoch',r.cancel_epoch,'private_context',r.private_context,\n"
 "  'data_categories',(SELECT coalesce(jsonb_agg(value ORDER BY value COLLATE "
 '"C"),\'[]\'::jsonb) FROM jsonb_array_elements_text(r.data_categories)),\n'
 "  'customer_identities',r.customer_identities,'tool',c.tool,\n"
 '  '
 "'call_key','agent:'||r.id::text||':model:'||m.id::text||':'||idx::text,'model_call_id',m.id,'response_index',idx,\n"
 '  '
 "'model_version',m.execution_binding->'model_version','model_route_digest',m.execution_binding->'model_route_digest',\n"
 '  '
 "'tool_definitions_digest',m.execution_binding->'tool_definitions_digest','prompt_digest',m.execution_binding->'prompt_digest');\n"
 " request=m.result->'calls'->idx; args=request->'arguments';\n"
 " IF b IS DISTINCT FROM expected OR c.call_key IS DISTINCT FROM expected->>'call_key'\n"
 "  OR request->>'name' IS DISTINCT FROM 'research.read'\n"
 "  OR NOT coalesce(jsonb_typeof(args)='object' AND (args-ARRAY['url','cursor'])='{}'::jsonb\n"
 "   AND args->>'url'=s.url AND (NOT (args ? 'cursor') OR (jsonb_typeof(args->'cursor')='number'\n"
 "    AND args->>'cursor' ~ '^(0|[1-9][0-9]*)$' AND "
 "(args->>'cursor')::numeric<=2147483647)),false)\n"
 '  OR c.input_digest IS DISTINCT FROM '
 "encode(sha256(convert_to(kernel_read_canonical_json(jsonb_build_array(c.tool,args)),'UTF8')),'hex') "
 'THEN RETURN false; END IF;\n'
 " bounds=regexp_match(c.result->>'locator','^chars:(0|[1-9][0-9]*):(0|[1-9][0-9]*)$');\n"
 ' IF bounds IS NULL THEN RETURN false; END IF;\n'
 ' start_at=bounds[1]::integer; end_at=bounds[2]::integer;\n'
 " IF start_at<>coalesce((args->>'cursor')::integer,0) OR start_at>end_at OR "
 'end_at>char_length(s.markdown)\n'
 '  OR (start_at=end_at AND end_at<char_length(s.markdown))\n'
 "  OR s.content_hash IS DISTINCT FROM encode(sha256(convert_to(s.markdown,'UTF8')),'hex') THEN "
 'RETURN false; END IF;\n'
 ' -- The research producer records timezone-aware UTC datetime values. Match\n'
 ' -- Python str(datetime): fractional microseconds only when nonzero.\n'
 " stamp=to_char(s.retrieved_at AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS');\n"
 ' IF extract(microseconds FROM s.retrieved_at)::bigint%1000000<>0 THEN '
 "stamp=stamp||to_char(s.retrieved_at AT TIME ZONE 'UTC','.US'); END IF;\n"
 " stamp=stamp||'+00:00';\n"
 ' '
 "full_snapshot=jsonb_build_object('id',s.id,'url',s.url,'final_url',s.final_url,'title',s.title,'summary',s.summary,\n"
 '  '
 "'retrieved_at',stamp,'markdown',s.markdown,'content_hash',s.content_hash,'provider',s.provider,'credibility',s.credibility,'status',s.status);\n"
 ' '
 "expected=jsonb_build_object('snapshot_id',s.id,'snapshot_digest',encode(sha256(convert_to(kernel_read_canonical_json(full_snapshot),'UTF8')),'hex'),\n"
 "  'content_hash',s.content_hash,'locator',c.result->'locator','markdown',substring(s.markdown "
 'FROM start_at+1 FOR end_at-start_at),\n'
 "  'next_cursor',CASE WHEN end_at<char_length(s.markdown) THEN end_at ELSE NULL END);\n"
 ' RETURN c.result IS NOT DISTINCT FROM expected;\n'
 'EXCEPTION WHEN data_exception THEN RETURN false;\n'
 'END $function$',
 'CREATE FUNCTION public.kernel_category_creation_proven(t uuid, cid uuid) RETURNS boolean\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $function$\n'
 'DECLARE category categories; receipt action_receipts; cp category_creation_confirmations; actor '
 'principals;\n'
 ' run agent_runs; event agent_run_events; loaded agent_run_events; model agent_tool_calls;\n'
 ' payload jsonb; body jsonb; source jsonb; skill jsonb; input jsonb; original jsonb; item jsonb; '
 'ref jsonb;\n'
 " bound jsonb; expected jsonb; expected_snapshots jsonb='[]'; snapshot public_web_snapshots; "
 'read_call agent_tool_calls;\n'
 ' material category_knowledge_entries; part text; line_body text; line_index integer; offset_at '
 'integer; start_at integer; end_at integer; covered boolean;\n'
 ' idx integer; group_key text; cx xid; rx xid; px xid; count_rows integer;\n'
 'BEGIN\n'
 ' SELECT * INTO category FROM categories WHERE tenant_id=t AND id=cid;\n'
 ' IF category.id IS NULL OR category.created_by_run_id IS NULL THEN RETURN false; END IF;\n'
 ' SELECT * INTO run FROM agent_runs WHERE tenant_id=t AND id=category.created_by_run_id FOR '
 'SHARE;\n'
 ' SELECT * INTO actor FROM principals WHERE tenant_id=t AND id=category.owner_id;\n'
 ' SELECT count(*) INTO count_rows FROM action_receipts WHERE tenant_id=t AND category_id=cid AND '
 "operation='category.create';\n"
 ' IF count_rows<>1 THEN RETURN false; END IF;\n'
 ' SELECT * INTO receipt FROM action_receipts WHERE tenant_id=t AND category_id=cid AND '
 "operation='category.create';\n"
 ' SELECT * INTO cp FROM category_creation_confirmations WHERE tenant_id=t AND '
 'reserved_category_id=cid\n'
 '  AND actor_id=category.owner_id AND consumed AND payload_digest=receipt.request_digest;\n'
 ' IF cp.id IS NULL OR actor.id IS NULL OR run.id IS NULL\n'
 "  OR t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid\n"
 '  OR category.owner_id IS DISTINCT FROM scope_actor() OR category.owner_id IS DISTINCT FROM '
 'scope_requester()\n'
 "  OR actor.kind<>'human' OR NOT actor.active OR category.revision<>1 OR "
 "category.status<>'active'\n"
 '  OR receipt.actor_id<>actor.id OR receipt.requester_id<>actor.id OR '
 "receipt.subject_type<>'category'\n"
 '  OR receipt.subject_id<>cid OR receipt.subject_revision<>1 OR receipt.product_id IS NOT NULL\n'
 '  OR receipt.run_id IS NOT NULL OR receipt.agent_run_id IS NOT NULL OR receipt.confirmation_id '
 'IS NOT NULL\n'
 "  OR receipt.result->'proof_version' IS DISTINCT FROM '1'::jsonb\n"
 "  OR receipt.result->>'origin' IS DISTINCT FROM 'ai_draft'\n"
 "  OR receipt.result->>'category_id' IS DISTINCT FROM cid::text\n"
 "  OR receipt.result->>'prepared_by_run_id' IS DISTINCT FROM run.id::text\n"
 "  OR receipt.result->>'registered_by_run_id' IS DISTINCT FROM run.id::text\n"
 '  OR run.requester_id<>actor.id OR run.category_id IS NOT NULL OR run.product_id IS NOT NULL OR '
 'run.proposal_id IS NOT NULL\n'
 "  OR run.private_context OR run.customer_identities IS DISTINCT FROM '[]'::jsonb\n"
 "  OR run.read_sources IS DISTINCT FROM '[]'::jsonb\n"
 "  OR coalesce(run.data_categories ?| ARRAY['customer','customer_original'],true)\n"
 '  OR NOT EXISTS(SELECT 1 FROM agent_sessions conversation WHERE conversation.tenant_id=t AND '
 'conversation.id=run.session_id\n'
 '   AND conversation.owner_id=actor.id AND conversation.category_id IS NULL AND '
 'conversation.product_id IS NULL AND conversation.proposal_id IS NULL)\n'
 "  OR run.state NOT IN ('queued','running','waiting_input','completed','partial') OR "
 'run.reverted_at IS NOT NULL\n'
 '  OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=t AND p.id=run.writer_id AND '
 "p.kind='agent' AND p.active)\n"
 "  OR cp.snapshot->'actor_access_epoch' IS DISTINCT FROM to_jsonb(actor.access_epoch)\n"
 '  OR cp.expires_at<=statement_timestamp() OR cp.created_at>receipt.created_at\n'
 '  OR NOT EXISTS(SELECT 1 FROM grants g WHERE g.tenant_id=t AND g.category_id=cid AND '
 'g.principal_id=actor.id\n'
 '   AND g.can_write AND (g.expires_at IS NULL OR g.expires_at>statement_timestamp())) THEN RETURN '
 'false; END IF;\n'
 ' SELECT xmin INTO cx FROM categories WHERE tenant_id=t AND id=cid;\n'
 ' SELECT xmin INTO rx FROM action_receipts WHERE tenant_id=t AND id=receipt.id;\n'
 ' SELECT xmin INTO px FROM category_creation_confirmations WHERE tenant_id=t AND id=cp.id;\n'
 ' IF cx IS DISTINCT FROM rx OR px IS DISTINCT FROM rx THEN RETURN false; END IF;\n'
 " payload=cp.snapshot->'payload';\n"
 " IF jsonb_typeof(payload) IS DISTINCT FROM 'object'\n"
 "  OR payload->'deidentified_confirmed' IS DISTINCT FROM 'true'::jsonb OR payload->>'seed_key' IS "
 'NOT NULL\n'
 "  OR payload->>'prepared_by_run_id' IS DISTINCT FROM run.id::text\n"
 '  OR receipt.request_digest IS DISTINCT FROM '
 "encode(sha256(convert_to(kernel_read_canonical_json(payload),'UTF8')),'hex')\n"
 "  OR payload->>'candidate_digest' IS DISTINCT FROM receipt.result->>'candidate_digest'\n"
 "  OR cp.snapshot->>'material_digest' IS DISTINCT FROM payload->>'candidate_digest'\n"
 "  OR cp.snapshot->>'category_candidate_event_id' IS DISTINCT FROM "
 "receipt.result->>'category_candidate_event_id'\n"
 "  OR NOT coalesce(receipt.result->>'category_candidate_event_id' ~ "
 "'^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$',false)\n"
 '  THEN RETURN false; END IF;\n'
 ' SELECT * INTO event FROM agent_run_events WHERE tenant_id=t AND run_id=run.id\n'
 "  AND id=(receipt.result->>'category_candidate_event_id')::uuid;\n"
 " body=event.body; source=body->'source'; skill=source->'skill'; input=body->'input';\n"
 " IF event.id IS NULL OR NOT coalesce(jsonb_typeof(body)='object'\n"
 '  AND body ?& '
 "ARRAY['type','intent_key','session_id','cancel_epoch','input','arguments','source','model_binding','snapshots','candidate_digest']\n"
 '  AND '
 "(body-ARRAY['type','intent_key','session_id','cancel_epoch','input','arguments','source','model_binding','snapshots','candidate_digest'])='{}'::jsonb\n"
 "  AND body->>'type'='category_candidate' AND body->>'session_id'=run.session_id::text\n"
 "  AND body->'cancel_epoch'=to_jsonb(run.cancel_epoch)\n"
 "  AND body->>'candidate_digest'=payload->>'candidate_digest'\n"
 "  AND jsonb_typeof(source)='object' AND source ?& "
 "ARRAY['skill','model_call_id','response_index']\n"
 "  AND (source-ARRAY['skill','model_call_id','response_index'])='{}'::jsonb\n"
 "  AND source->>'model_call_id' ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'\n"
 "  AND jsonb_typeof(source->'response_index')='number' AND source->>'response_index' ~ "
 "'^(0|[1-9][0-9]*)$'\n"
 "  AND (source->>'response_index')::numeric<=2147483647\n"
 "  AND jsonb_typeof(skill)='object' AND skill ?& ARRAY['key','version','digest','load_event_id']\n"
 "  AND (skill-ARRAY['key','version','digest','load_event_id'])='{}'::jsonb\n"
 "  AND skill->>'load_event_id' ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$',false) THEN RETURN "
 'false; END IF;\n'
 " expected=jsonb_build_object('operation','category.create','tenant_id',t,'run_id',run.id,\n"
 "  'requester_id',run.requester_id,'writer_id',run.writer_id,'body',body-'candidate_digest');\n"
 " IF body->>'candidate_digest' IS DISTINCT FROM "
 "encode(sha256(convert_to(kernel_read_canonical_json(expected),'UTF8')),'hex') THEN RETURN false; "
 'END IF;\n'
 " idx=(source->>'response_index')::integer;\n"
 ' SELECT * INTO model FROM agent_tool_calls WHERE tenant_id=t AND run_id=run.id AND '
 "id=(source->>'model_call_id')::uuid;\n"
 ' bound=model.execution_binding;\n'
 " IF model.id IS NULL OR model.tool<>'model' OR model.state<>'completed' OR model.error_code IS "
 'NOT NULL OR model.receipt_id IS NOT NULL\n'
 "  OR bound IS DISTINCT FROM body->'model_binding' OR bound->>'kind' IS DISTINCT FROM 'model'\n"
 "  OR bound->>'isolation' IS DISTINCT FROM 'main' OR bound->'cancel_epoch' IS DISTINCT FROM "
 'to_jsonb(run.cancel_epoch)\n'
 "  OR bound->'model_version' IS DISTINCT FROM run.versions->'model_version'\n"
 "  OR bound->'model_route_digest' IS DISTINCT FROM run.versions->'model_route_digest'\n"
 "  OR bound->'tool_definitions_digest' IS DISTINCT FROM run.versions->'tool_definitions'->'main'\n"
 "  OR bound->'prompt_digest' IS DISTINCT FROM run.versions->'prompt_prefixes'->'main'\n"
 "  OR jsonb_typeof(model.result->'calls') IS DISTINCT FROM 'array'\n"
 "  OR jsonb_typeof(bound->'loaded_skills') IS DISTINCT FROM 'array'\n"
 "  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(bound->'loaded_skills') actual WHERE "
 'actual=skill)\n'
 "  OR body->>'intent_key' IS DISTINCT FROM "
 "'agent:'||run.id::text||':model:'||model.id::text||':'||idx::text THEN RETURN false; END IF;\n"
 ' SELECT * INTO loaded FROM agent_run_events WHERE tenant_id=t AND run_id=run.id AND '
 "id=(skill->>'load_event_id')::uuid;\n"
 " IF loaded.id IS NULL OR loaded.body IS DISTINCT FROM jsonb_build_object('type','skill_loaded',\n"
 "  'key',skill->'key','version',skill->'version','digest',skill->'digest','isolation','main') "
 'THEN RETURN false; END IF;\n'
 " original=model.result->'calls'->idx;\n"
 " IF original->>'name' IS DISTINCT FROM 'category.create' OR original->'arguments' IS DISTINCT "
 "FROM body->'arguments'\n"
 '  OR input IS DISTINCT FROM '
 "kernel_category_candidate_normalize(original->'arguments','candidate')\n"
 "  OR (input-ARRAY['key','name','purpose','groups'])<>'{}'::jsonb\n"
 "  OR NOT (input ?& ARRAY['key','name','purpose','groups'])\n"
 "  OR payload->>'key' IS DISTINCT FROM input->>'key' OR payload->>'name' IS DISTINCT FROM "
 "input->>'name'\n"
 "  OR payload->>'purpose' IS DISTINCT FROM input->>'purpose'\n"
 "  OR category.key IS DISTINCT FROM input->>'key' OR category.name IS DISTINCT FROM "
 "input->>'name'\n"
 "  OR category.purpose IS DISTINCT FROM input->>'purpose'\n"
 "  OR receipt.result->>'key' IS DISTINCT FROM category.key OR receipt.result->>'name' IS DISTINCT "
 'FROM category.name\n'
 "  OR jsonb_typeof(input->'groups') IS DISTINCT FROM 'object'\n"
 "  OR jsonb_typeof(payload->'groups') IS DISTINCT FROM 'object'\n"
 "  OR (input->'groups'-ARRAY['knowledge','parameters','snapshot_refs'])<>'{}'::jsonb\n"
 "  OR (payload->'groups'-ARRAY['knowledge','parameters','snapshot_refs'])<>'{}'::jsonb\n"
 "  OR receipt.result->'groups' IS DISTINCT FROM payload->'groups'\n"
 "  OR receipt.result->>'groups_digest' IS DISTINCT FROM "
 "encode(sha256(convert_to(kernel_read_canonical_json(payload->'groups'),'UTF8')),'hex') THEN "
 'RETURN false; END IF;\n'
 " FOREACH group_key IN ARRAY ARRAY['knowledge','parameters','snapshot_refs'] LOOP\n"
 "  IF jsonb_typeof(input->'groups'->group_key) IS DISTINCT FROM 'array'\n"
 "   OR jsonb_typeof(payload->'groups'->group_key) IS DISTINCT FROM 'array'\n"
 "   OR (payload->'groups'->group_key<>'[]'::jsonb AND payload->'groups'->group_key IS DISTINCT "
 "FROM input->'groups'->group_key) THEN RETURN false; END IF;\n"
 ' END LOOP;\n'
 " IF jsonb_typeof(receipt.result->'parameters') IS DISTINCT FROM 'array'\n"
 "  OR jsonb_typeof(receipt.result->'knowledge') IS DISTINCT FROM 'array'\n"
 "  OR jsonb_typeof(receipt.result->'snapshot_refs') IS DISTINCT FROM 'array'\n"
 "  OR jsonb_typeof(body->'snapshots') IS DISTINCT FROM 'array'\n"
 '  OR '
 "jsonb_array_length(receipt.result->'parameters')<>jsonb_array_length(payload->'groups'->'parameters')\n"
 '  OR '
 "jsonb_array_length(receipt.result->'knowledge')<>jsonb_array_length(payload->'groups'->'knowledge')\n"
 "  OR jsonb_array_length(receipt.result->'parameters')<>(SELECT count(*) FROM parameter_versions "
 'WHERE tenant_id=t AND category_id=cid AND receipt_id=receipt.id)\n'
 "  OR jsonb_array_length(receipt.result->'knowledge')<>(SELECT count(*) FROM "
 'category_knowledge_entries WHERE tenant_id=t AND category_id=cid AND receipt_id=receipt.id) THEN '
 'RETURN false; END IF;\n'
 " FOR item IN SELECT * FROM jsonb_array_elements(payload->'groups'->'snapshot_refs') LOOP\n"
 '  SELECT * INTO read_call FROM agent_tool_calls WHERE tenant_id=t AND run_id=run.id AND '
 "id=(item->>'call_id')::uuid;\n"
 "  IF read_call.id IS NULL OR read_call.state<>'completed' OR read_call.tool<>'research.read' OR "
 'read_call.error_code IS NOT NULL\n'
 "   OR read_call.receipt_id IS NOT NULL OR read_call.result->>'content_hash' IS DISTINCT FROM "
 "item->>'content_hash'\n"
 '   OR '
 "kernel_category_snapshot_read_proven(t,run.id,read_call.id,(read_call.result->>'snapshot_id')::uuid) "
 'IS DISTINCT FROM true\n'
 "   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(body->'snapshots') fact\n"
 "    WHERE fact->>'read_call_id'=read_call.id::text AND "
 "fact->>'snapshot_id'=read_call.result->>'snapshot_id'\n"
 "     AND fact->>'content_hash'=item->>'content_hash' AND "
 "fact->>'snapshot_digest'=read_call.result->>'snapshot_digest'\n"
 "     AND fact->>'page_start'=split_part(read_call.result->>'locator',':',2)\n"
 "     AND fact->>'page_end'=split_part(read_call.result->>'locator',':',3)\n"
 '     AND '
 "(fact-ARRAY['snapshot_id','read_call_id','content_hash','snapshot_digest','page_start','page_end'])='{}'::jsonb) "
 'THEN RETURN false; END IF;\n'
 '  '
 "ref=jsonb_build_object('snapshot_id',read_call.result->'snapshot_id','content_hash',item->'content_hash','call_id',read_call.id);\n"
 '  IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(expected_snapshots) x WHERE '
 "x->>'snapshot_id'=ref->>'snapshot_id') THEN "
 'expected_snapshots=expected_snapshots||jsonb_build_array(ref); END IF;\n'
 ' END LOOP;\n'
 " IF receipt.result->'snapshot_refs' IS DISTINCT FROM expected_snapshots\n"
 '  OR jsonb_array_length(expected_snapshots)<>(SELECT count(*) FROM public_web_snapshots WHERE '
 'tenant_id=t AND category_id=cid AND receipt_id=receipt.id) THEN RETURN false; END IF;\n'
 ' FOR ref IN SELECT * FROM jsonb_array_elements(expected_snapshots) LOOP\n'
 '  SELECT * INTO snapshot FROM public_web_snapshots WHERE tenant_id=t AND category_id=cid AND '
 "id=(ref->>'snapshot_id')::uuid;\n"
 '  IF snapshot.id IS NULL OR snapshot.receipt_id<>receipt.id OR '
 'snapshot.registered_by_run_id<>run.id\n'
 "   OR snapshot.owner_id<>actor.id OR snapshot.visibility<>'category' OR snapshot.content_hash IS "
 "DISTINCT FROM ref->>'content_hash'\n"
 '   OR kernel_snapshot_registration_proven(snapshot) IS DISTINCT FROM true\n'
 "   OR kernel_category_snapshot_read_proven(t,run.id,(ref->>'call_id')::uuid,snapshot.id) IS "
 'DISTINCT FROM true THEN RETURN false; END IF;\n'
 ' END LOOP;\n'
 '\n'
 ' -- Initial knowledge may cite only explicit tenant humans or the selected public\n'
 ' -- pages. Confirmation cannot turn an unread location into a source fact.\n'
 ' FOR material IN SELECT * FROM category_knowledge_entries WHERE tenant_id=t AND category_id=cid '
 'AND receipt_id=receipt.id LOOP\n'
 "  IF material.kind IN ('competitor','voice','regulation') AND "
 'jsonb_array_length(material.source_refs)=0 THEN RETURN false; END IF;\n'
 '  FOR ref IN SELECT * FROM jsonb_array_elements(material.source_refs) LOOP\n'
 "   IF ref->>'type'='human' THEN\n"
 "    IF NOT coalesce(length(btrim(ref->>'statement'))>0,false)\n"
 "     OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=t AND p.id=(ref->>'id')::uuid "
 "AND p.kind='human' AND p.active) THEN RETURN false; END IF;\n"
 "   ELSIF ref->>'type'='snapshot' THEN\n"
 "    IF NOT coalesce(ref->'version'='1'::jsonb AND jsonb_typeof(ref->'line')='number'\n"
 "     AND (ref->>'line')::integer>0 AND length(ref->>'quote')>0,false) THEN RETURN false; END "
 'IF;\n'
 '    SELECT * INTO snapshot FROM public_web_snapshots WHERE tenant_id=t AND category_id=cid\n'
 "     AND receipt_id=receipt.id AND id=(ref->>'id')::uuid;\n"
 '    IF snapshot.id IS NULL THEN RETURN false; END IF;\n'
 '    line_index=0; offset_at=0; line_body=NULL; covered=false;\n'
 '    FOR part IN SELECT captures[1] FROM regexp_matches(snapshot.markdown,\n'
 '     '
 "E'([^\\\\r\\\\n\\\\v\\\\f\\\\x1c\\\\x1d\\\\x1e\\\\u0085\\\\u2028\\\\u2029]*(?:\\\\r\\\\n|[\\\\r\\\\n\\\\v\\\\f\\\\x1c\\\\x1d\\\\x1e\\\\u0085\\\\u2028\\\\u2029]|$))','g') "
 'AS pieces(captures) LOOP\n'
 "     IF part='' THEN CONTINUE; END IF;\n"
 '     line_index=line_index+1;\n'
 "     IF line_index=(ref->>'line')::integer THEN\n"
 '      '
 "line_body=regexp_replace(part,E'(\\\\r\\\\n|[\\\\r\\\\n\\\\v\\\\f\\\\x1c\\\\x1d\\\\x1e\\\\u0085\\\\u2028\\\\u2029])$',''); "
 'EXIT;\n'
 '     END IF;\n'
 '     offset_at=offset_at+char_length(part);\n'
 '    END LOOP;\n'
 '    IF line_body IS NULL THEN RETURN false; END IF;\n'
 "    FOR item IN SELECT * FROM jsonb_array_elements(payload->'groups'->'snapshot_refs') LOOP\n"
 '     SELECT * INTO read_call FROM agent_tool_calls WHERE tenant_id=t AND run_id=run.id AND '
 "id=(item->>'call_id')::uuid;\n"
 "     IF read_call.result->>'snapshot_id'=snapshot.id::text THEN\n"
 "      start_at=greatest(0,split_part(read_call.result->>'locator',':',2)::integer-offset_at);\n"
 '      '
 "end_at=least(char_length(line_body),split_part(read_call.result->>'locator',':',3)::integer-offset_at);\n"
 "      IF start_at<end_at AND position(ref->>'quote' IN substring(line_body FROM start_at+1 FOR "
 'end_at-start_at))>0 THEN covered=true; EXIT; END IF;\n'
 '     END IF;\n'
 '    END LOOP;\n'
 '    IF NOT covered THEN RETURN false; END IF;\n'
 '   ELSE RETURN false;\n'
 '   END IF;\n'
 '  END LOOP;\n'
 ' END LOOP;\n'
 ' RETURN true;\n'
 'EXCEPTION WHEN data_exception OR no_data_found OR too_many_rows THEN RETURN false;\n'
 'END $function$',
 'CREATE FUNCTION public.kernel_category_candidate_guard() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $function$\n'
 'BEGIN\n'
 " IF TG_OP='UPDATE' THEN\n"
 '  IF NEW.created_by_run_id IS DISTINCT FROM OLD.created_by_run_id THEN\n'
 "   RAISE EXCEPTION 'Category original candidate Run is immutable' USING ERRCODE='23514';\n"
 '  END IF;\n'
 '  RETURN NEW;\n'
 ' END IF;\n'
 ' IF NEW.created_by_run_id IS NULL AND EXISTS(SELECT 1 FROM action_receipts a WHERE '
 'a.tenant_id=NEW.tenant_id\n'
 "  AND a.category_id=NEW.id AND a.operation='category.create'\n"
 "  AND (a.result->>'origin'='ai_draft' OR a.result->>'prepared_by_run_id' IS NOT NULL)) THEN\n"
 "  RAISE EXCEPTION 'AI category creation must retain its original Run' USING ERRCODE='23514';\n"
 ' END IF;\n'
 ' IF NEW.created_by_run_id IS NOT NULL AND kernel_category_creation_proven(NEW.tenant_id,NEW.id) '
 'IS DISTINCT FROM true THEN\n'
 "  RAISE EXCEPTION 'AI category creation requires its exact named personal-Run candidate "
 "confirmation' USING ERRCODE='23514';\n"
 ' END IF;\n'
 ' RETURN NULL;\n'
 'END $function$',
 'CREATE OR REPLACE FUNCTION public.m3_material_atom()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 'DECLARE r action_receipts; ar agent_runs; pc proposal_prepared_candidates;\n'
 ' prior category_knowledge_entries;\n'
 ' expected_type text; identity uuid; latest integer;\n'
 ' confirmed_proof confirmations; confirmation_required boolean;\n'
 ' confirmation_xmin xid; receipt_xmin xid; material_xmin xid;\n'
 ' creation_proof category_creation_confirmations; position_index integer; creation_ai '
 'boolean=false;\n'
 ' confirmed_item jsonb; expected_content jsonb; expected_refs jsonb; sample_count bigint;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=NEW.tenant_id AND '
 'id=NEW.receipt_id;\n'
 ' IF r.category_id IS DISTINCT FROM NEW.category_id OR r.product_id IS NOT NULL\n'
 '  OR r.actor_id IS DISTINCT FROM scope_actor() OR r.requester_id IS DISTINCT FROM '
 'scope_requester()\n'
 '  OR r.run_id IS NOT NULL THEN\n'
 "  RAISE EXCEPTION 'material receipt scope mismatch' USING ERRCODE='23514';\n"
 ' END IF;\n'
 '\n'
 " -- Row versions must originate in the receipt's transaction, not a later replay.\n"
 ' SELECT rr.xmin INTO STRICT receipt_xmin FROM action_receipts rr\n'
 '  WHERE rr.tenant_id=NEW.tenant_id AND rr.id=r.id;\n'
 " EXECUTE format('SELECT xmin FROM public.%I WHERE tenant_id=$1 AND id=$2', TG_TABLE_NAME)\n"
 '  INTO STRICT material_xmin USING NEW.tenant_id,NEW.id;\n'
 ' IF material_xmin IS DISTINCT FROM receipt_xmin THEN\n'
 "  RAISE EXCEPTION 'material and receipt must commit together' USING ERRCODE='23514';\n"
 ' END IF;\n'
 '\n'
 " confirmation_required=r.operation IN ('category.parameter.publish',\n"
 "  'category.knowledge.withdraw','category.knowledge.promote');\n"
 " IF TG_TABLE_NAME<>'promotion_proofs' THEN\n"
 '  confirmation_required=confirmation_required OR (NEW.confirmed_by IS NOT NULL AND '
 "r.operation<>'category.create');\n"
 ' END IF;\n'
 ' IF confirmation_required THEN\n'
 '  -- Fetch the row and transaction identities separately: %ROWTYPE has no xmin.\n'
 '  SELECT * INTO STRICT confirmed_proof FROM confirmations cp\n'
 '   WHERE cp.tenant_id=NEW.tenant_id AND cp.id=r.confirmation_id;\n'
 '  SELECT cp.xmin INTO confirmation_xmin FROM confirmations cp\n'
 '   WHERE cp.tenant_id=NEW.tenant_id AND cp.id=r.confirmation_id;\n'
 '  IF confirmed_proof.consumed IS DISTINCT FROM true OR confirmed_proof.actor_id<>r.actor_id\n'
 '   OR confirmed_proof.category_id IS DISTINCT FROM r.category_id\n'
 '   OR confirmed_proof.operation<>r.operation OR confirmed_proof.product_id IS NOT NULL\n'
 '   OR confirmation_xmin IS DISTINCT FROM receipt_xmin\n'
 "   OR jsonb_typeof(confirmed_proof.snapshot->'payload') IS DISTINCT FROM 'object' THEN\n"
 "   RAISE EXCEPTION 'material requires its same-transaction consumed confirmation'\n"
 "    USING ERRCODE='23514';\n"
 '  END IF;\n'
 ' ELSE\n'
 '  IF r.confirmation_id IS NOT NULL THEN\n'
 "   RAISE EXCEPTION 'unconfirmed material cannot borrow a confirmation' USING ERRCODE='23514';\n"
 '  END IF;\n'
 ' END IF;\n'
 " IF r.operation='category.create' AND TG_TABLE_NAME IN\n"
 "  ('parameter_versions','category_knowledge_entries') THEN\n"
 '  SELECT * INTO STRICT creation_proof FROM category_creation_confirmations cp\n'
 '   WHERE cp.tenant_id=NEW.tenant_id AND cp.actor_id=r.actor_id\n'
 '    AND cp.reserved_category_id=NEW.category_id AND cp.consumed\n'
 '    AND cp.payload_digest=r.request_digest;\n'
 '  SELECT cp.xmin INTO STRICT confirmation_xmin FROM category_creation_confirmations cp\n'
 '   WHERE cp.tenant_id=NEW.tenant_id AND cp.id=creation_proof.id;\n'
 "  creation_ai=creation_proof.snapshot->'payload'->>'prepared_by_run_id' IS NOT NULL;\n"
 '  IF creation_ai AND kernel_category_creation_proven(NEW.tenant_id,NEW.category_id) IS DISTINCT '
 'FROM true THEN\n'
 "   RAISE EXCEPTION 'Initial AI material requires the exact category candidate' USING "
 "ERRCODE='23514';\n"
 '  END IF;\n'
 '  IF confirmation_xmin IS DISTINCT FROM receipt_xmin\n'
 '   OR (SELECT count(*) FROM action_receipts rr WHERE rr.tenant_id=NEW.tenant_id\n'
 "       AND rr.category_id=NEW.category_id AND rr.operation='category.create')<>1\n"
 "   OR (NOT creation_ai AND creation_proof.snapshot->'payload'->>'candidate_digest' IS NOT NULL)\n"
 "   OR (creation_proof.snapshot->'payload'->>'deidentified_confirmed')::boolean\n"
 '      IS DISTINCT FROM true\n'
 "   OR r.subject_type<>'category' OR r.subject_id<>NEW.category_id\n"
 '   OR r.subject_revision<>1 OR NEW.version<>1\n'
 '   OR r.actor_id<>r.requester_id\n'
 '   OR NEW.origin IS DISTINCT FROM (CASE\n'
 "    WHEN creation_ai THEN 'ai_draft'\n"
 "    WHEN creation_proof.snapshot->'payload'->>'seed_key' IS NULL THEN 'human' ELSE 'imported' "
 'END)\n'
 "   OR jsonb_typeof(r.result->'parameters') IS DISTINCT FROM 'array'\n"
 "   OR jsonb_typeof(r.result->'knowledge') IS DISTINCT FROM 'array'\n"
 "   OR jsonb_typeof(creation_proof.snapshot->'payload'->'groups'->'parameters')\n"
 "      IS DISTINCT FROM 'array'\n"
 "   OR jsonb_typeof(creation_proof.snapshot->'payload'->'groups'->'knowledge')\n"
 "      IS DISTINCT FROM 'array' THEN\n"
 "   RAISE EXCEPTION 'category material creation proof mismatch' USING ERRCODE='23514';\n"
 '  END IF;\n'
 "  IF jsonb_array_length(r.result->'parameters')<>\n"
 "      jsonb_array_length(creation_proof.snapshot->'payload'->'groups'->'parameters')\n"
 "   OR jsonb_array_length(r.result->'knowledge')<>\n"
 "      jsonb_array_length(creation_proof.snapshot->'payload'->'groups'->'knowledge')\n"
 "   OR jsonb_array_length(r.result->'parameters')<>(SELECT count(*) FROM parameter_versions v\n"
 '      WHERE v.tenant_id=NEW.tenant_id AND v.category_id=NEW.category_id AND v.receipt_id=r.id)\n'
 "   OR jsonb_array_length(r.result->'knowledge')<>(SELECT count(*) FROM "
 'category_knowledge_entries k\n'
 '      WHERE k.tenant_id=NEW.tenant_id AND k.category_id=NEW.category_id AND k.receipt_id=r.id) '
 'THEN\n'
 "   RAISE EXCEPTION 'category initial material manifest is incomplete' USING ERRCODE='23514';\n"
 '  END IF;\n'
 "  IF TG_TABLE_NAME='parameter_versions' THEN\n"
 '   SELECT (m.ordinality-1)::integer INTO STRICT position_index\n'
 "    FROM jsonb_array_elements(r.result->'parameters') WITH ORDINALITY m(item,ordinality)\n"
 "    WHERE m.item->>'parameter_id'=NEW.parameter_id::text\n"
 "     AND m.item->>'key'=NEW.key AND (m.item->>'version')::integer=NEW.version;\n"
 "   confirmed_item=creation_proof.snapshot->'payload'->'groups'->'parameters'->position_index;\n"
 '   IF '
 "(to_jsonb(NEW)-ARRAY['id','tenant_id','category_id','created_at','parameter_id','version',\n"
 "        'replaces_version','origin','writer_id','run_id','confirmed_by','receipt_id',\n"
 "        'prepared_candidate_id']) IS DISTINCT FROM confirmed_item THEN\n"
 "    RAISE EXCEPTION 'initial parameter differs from confirmed content' USING ERRCODE='23514';\n"
 '   END IF;\n'
 '  ELSE\n'
 '   SELECT (m.ordinality-1)::integer INTO STRICT position_index\n'
 "    FROM jsonb_array_elements(r.result->'knowledge') WITH ORDINALITY m(item,ordinality)\n"
 "    WHERE m.item->>'entry_id'=NEW.id::text AND m.item->>'lineage_id'=NEW.lineage_id::text\n"
 "     AND (m.item->>'version')::integer=NEW.version;\n"
 "   confirmed_item=creation_proof.snapshot->'payload'->'groups'->'knowledge'->position_index;\n"
 "   expected_content=confirmed_item->'content';\n"
 "   expected_refs=confirmed_item->'source_refs';\n"
 "   IF confirmed_item->>'kind'='voice' THEN\n"
 "    expected_refs=expected_refs||(expected_content->'representative_refs');\n"
 "    SELECT count(DISTINCT ROW(ref->>'id',ref->>'version',ref->>'line'))\n"
 '     INTO sample_count FROM jsonb_array_elements(expected_refs) ref;\n'
 "    expected_content=expected_content||jsonb_build_object('sample_size',sample_count);\n"
 "   ELSIF confirmed_item->>'kind'='competitor' THEN\n"
 "    SELECT expected_refs||coalesce(jsonb_agg(entry->'source_ref' ORDER BY ordinality), "
 "'[]'::jsonb)\n"
 '     INTO expected_refs FROM jsonb_array_elements(\n'
 '      '
 "(expected_content->'metrics')||(expected_content->'features')||(expected_content->'prices'))\n"
 '      WITH ORDINALITY refs(entry,ordinality)\n'
 "      WHERE jsonb_typeof(entry->'source_ref')='object';\n"
 '   END IF;\n'
 "   IF NEW.kind IS DISTINCT FROM confirmed_item->>'kind'\n"
 '    OR NEW.content IS DISTINCT FROM expected_content\n'
 "    OR to_jsonb(NEW.regions) IS DISTINCT FROM confirmed_item->'regions'\n"
 '    OR NEW.source_refs IS DISTINCT FROM expected_refs\n'
 "    OR NEW.action<>'add' OR NEW.withdraw_reason IS NOT NULL THEN\n"
 "    RAISE EXCEPTION 'initial knowledge differs from confirmed content' USING ERRCODE='23514';\n"
 '   END IF;\n'
 '  END IF;\n'
 ' END IF;\n'
 " IF TG_TABLE_NAME='promotion_proofs' THEN\n"
 "  IF NEW.id::text IS DISTINCT FROM r.result->>'promotion_proof_id'\n"
 "   OR confirmed_proof.subject_type<>'proposal'\n"
 '   OR confirmed_proof.subject_id<>NEW.source_proposal_id\n'
 '   OR confirmed_proof.revision<>NEW.source_proposal_revision\n'
 "   OR (confirmed_proof.snapshot->'payload'->>'source_proposal_id')::uuid\n"
 '      IS DISTINCT FROM NEW.source_proposal_id\n'
 "   OR (confirmed_proof.snapshot->'payload'->>'source_proposal_revision')::integer\n"
 '      IS DISTINCT FROM NEW.source_proposal_revision\n'
 "   OR confirmed_proof.snapshot->'payload'->'source_item_refs' IS DISTINCT FROM "
 'NEW.source_item_refs\n'
 "   OR (confirmed_proof.snapshot->'payload'->>'deidentified_confirmed')::boolean IS DISTINCT FROM "
 'true\n'
 "   OR r.operation<>'category.knowledge.promote' OR r.actor_id<>NEW.deidentified_by\n"
 '   OR r.actor_id<>r.requester_id OR NOT EXISTS(SELECT 1 FROM principals p\n'
 "    WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.deidentified_by AND p.kind='human')\n"
 '   OR NOT EXISTS(SELECT 1 FROM category_knowledge_entries k WHERE k.tenant_id=NEW.tenant_id\n'
 '    AND k.category_id=NEW.category_id AND k.id=NEW.knowledge_entry_id AND k.receipt_id=r.id\n'
 "    AND r.subject_type='category_knowledge' AND r.subject_id=k.lineage_id\n"
 '    AND r.subject_revision=k.version)\n'
 '   OR NOT EXISTS(SELECT 1 FROM proposal_revisions pv WHERE pv.tenant_id=NEW.tenant_id\n'
 '    AND pv.category_id=NEW.category_id AND pv.proposal_id=NEW.source_proposal_id\n'
 '    AND pv.revision=NEW.source_proposal_revision)\n'
 "   OR NOT coalesce((NEW.checks->>'refs_clean')::boolean,false)\n"
 "   OR NOT coalesce((NEW.checks->>'filenames_clean')::boolean,false)\n"
 "   OR NOT coalesce((NEW.checks->>'identities_clean')::boolean,false) THEN\n"
 "   RAISE EXCEPTION 'promotion proof does not bind the named receipt' USING ERRCODE='23514';\n"
 '  END IF;\n'
 '  RETURN NULL;\n'
 ' END IF;\n'
 " IF TG_TABLE_NAME='parameter_versions' THEN\n"
 "  expected_type='parameter'; identity=NEW.parameter_id;\n"
 "  IF r.operation NOT IN ('category.parameter.publish','category.create') THEN\n"
 "   RAISE EXCEPTION 'parameter receipt operation mismatch' USING ERRCODE='23514';\n"
 '  END IF;\n'
 '  SELECT max(version) INTO latest FROM parameter_versions WHERE tenant_id=NEW.tenant_id\n'
 '   AND parameter_id=NEW.parameter_id;\n'
 '  IF NOT EXISTS(SELECT 1 FROM parameter_current c WHERE c.tenant_id=NEW.tenant_id\n'
 '   AND c.category_id=NEW.category_id AND c.parameter_id=NEW.parameter_id\n'
 '   AND c.key=NEW.key AND c.current_version=latest)\n'
 '   OR (NEW.version=1 AND NEW.replaces_version IS NOT NULL)\n'
 '   OR (NEW.version>1 AND (NEW.replaces_version IS DISTINCT FROM NEW.version-1\n'
 '    OR NOT EXISTS(SELECT 1 FROM parameter_versions v WHERE v.tenant_id=NEW.tenant_id\n'
 '     AND v.category_id=NEW.category_id AND v.parameter_id=NEW.parameter_id\n'
 '     AND v.version=NEW.version-1 AND v.key=NEW.key))) THEN\n'
 "   RAISE EXCEPTION 'parameter version and current must commit together' USING ERRCODE='23514';\n"
 '  END IF;\n'
 ' ELSE\n'
 "  expected_type='category_knowledge'; identity=NEW.lineage_id;\n"
 "  IF r.operation NOT IN ('category.knowledge.add','category.knowledge.withdraw',\n"
 "   'category.knowledge.promote','category.create')\n"
 "   OR (NEW.action='withdraw') IS DISTINCT FROM (r.operation='category.knowledge.withdraw') THEN\n"
 "   RAISE EXCEPTION 'knowledge receipt operation mismatch' USING ERRCODE='23514';\n"
 '  END IF;\n'
 '  SELECT max(version) INTO latest FROM category_knowledge_entries WHERE tenant_id=NEW.tenant_id\n'
 '   AND lineage_id=NEW.lineage_id;\n'
 '  IF NOT EXISTS(SELECT 1 FROM category_knowledge_current c WHERE c.tenant_id=NEW.tenant_id\n'
 '   AND c.category_id=NEW.category_id AND c.lineage_id=NEW.lineage_id AND '
 'c.current_version=latest)\n'
 "   OR (NEW.version=1 AND NEW.action<>'add') THEN\n"
 "   RAISE EXCEPTION 'knowledge entry and current must commit together' USING ERRCODE='23514';\n"
 '  END IF;\n'
 '  IF NEW.version>1 THEN\n'
 '   SELECT * INTO STRICT prior FROM category_knowledge_entries WHERE tenant_id=NEW.tenant_id\n'
 '    AND category_id=NEW.category_id AND lineage_id=NEW.lineage_id AND version=NEW.version-1;\n'
 "   IF NEW.kind<>prior.kind OR NEW.action='add' THEN\n"
 "    RAISE EXCEPTION 'knowledge lineage mismatch' USING ERRCODE='23514';\n"
 '   END IF;\n'
 '  END IF;\n'
 "  IF r.operation='category.knowledge.promote' AND NOT EXISTS(SELECT 1 FROM promotion_proofs p\n"
 '   WHERE p.tenant_id=NEW.tenant_id AND p.knowledge_entry_id=NEW.id AND p.receipt_id=r.id) THEN\n'
 "   RAISE EXCEPTION 'promotion requires its private proof' USING ERRCODE='23514';\n"
 '  END IF;\n'
 ' END IF;\n'
 ' IF NOT ((r.subject_type=expected_type AND r.subject_id=identity AND '
 'r.subject_revision=NEW.version)\n'
 "  OR (r.operation='category.create' AND r.subject_type='category'\n"
 '   AND r.subject_id=NEW.category_id AND NEW.version=1)) THEN\n'
 "  RAISE EXCEPTION 'material receipt subject mismatch' USING ERRCODE='23514';\n"
 ' END IF;\n'
 '\n'
 ' IF confirmation_required THEN\n'
 "  confirmed_item=confirmed_proof.snapshot->'payload';\n"
 "  IF TG_TABLE_NAME='parameter_versions' THEN\n"
 '   IF '
 "(to_jsonb(NEW)-ARRAY['id','tenant_id','category_id','created_at','parameter_id','version',\n"
 "        'replaces_version','origin','writer_id','run_id','confirmed_by','receipt_id',\n"
 "        'prepared_candidate_id']) IS DISTINCT FROM\n"
 "       (confirmed_item-ARRAY['parameter_id','expected_current_version','prepared_by_run_id',\n"
 "                            'candidate_digest'])\n"
 "    OR (confirmed_item->>'expected_current_version')::integer IS DISTINCT FROM NEW.version-1\n"
 "    OR (NEW.version=1 AND confirmed_item->>'parameter_id' IS NOT NULL)\n"
 "    OR (NEW.version>1 AND (confirmed_item->>'parameter_id')::uuid\n"
 '        IS DISTINCT FROM NEW.parameter_id)\n'
 "    OR (NEW.version=1 AND (confirmed_proof.subject_type<>'category'\n"
 '         OR confirmed_proof.subject_id<>NEW.category_id))\n'
 "    OR (NEW.version>1 AND (confirmed_proof.subject_type<>'parameter'\n"
 '         OR confirmed_proof.subject_id<>NEW.parameter_id\n'
 '         OR confirmed_proof.revision<>NEW.version-1)) THEN\n'
 "    RAISE EXCEPTION 'published parameter differs from confirmation' USING ERRCODE='23514';\n"
 '   END IF;\n'
 "  ELSIF r.operation='category.knowledge.withdraw' THEN\n"
 "   IF (confirmed_item->>'lineage_id')::uuid IS DISTINCT FROM NEW.lineage_id\n"
 "    OR (confirmed_item->>'expected_version')::integer IS DISTINCT FROM NEW.version-1\n"
 "    OR confirmed_item->>'reason' IS DISTINCT FROM NEW.withdraw_reason\n"
 '    OR coalesce(length(NEW.withdraw_reason),0)=0\n'
 "    OR confirmed_proof.subject_type<>'category_knowledge'\n"
 '    OR confirmed_proof.subject_id<>NEW.lineage_id OR confirmed_proof.revision<>NEW.version-1\n'
 '    OR NEW.content IS DISTINCT FROM prior.content OR NEW.regions IS DISTINCT FROM prior.regions\n'
 '    OR NEW.source_refs IS DISTINCT FROM prior.source_refs THEN\n'
 "    RAISE EXCEPTION 'knowledge withdrawal differs from confirmation or prior version'\n"
 "     USING ERRCODE='23514';\n"
 '   END IF;\n'
 '  ELSE\n'
 "   expected_content=confirmed_item->'content';\n"
 "   expected_refs=coalesce(confirmed_item->'source_refs','[]'::jsonb);\n"
 "   IF confirmed_item->>'kind'='voice' THEN\n"
 "    expected_refs=expected_refs||(expected_content->'representative_refs');\n"
 "    SELECT count(DISTINCT ROW(ref->>'id',ref->>'version',ref->>'line'))\n"
 '     INTO sample_count FROM jsonb_array_elements(expected_refs) ref;\n'
 "    expected_content=expected_content||jsonb_build_object('sample_size',sample_count);\n"
 "   ELSIF confirmed_item->>'kind'='competitor' THEN\n"
 "    SELECT expected_refs||coalesce(jsonb_agg(entry->'source_ref' ORDER BY ordinality), "
 "'[]'::jsonb)\n"
 '     INTO expected_refs FROM jsonb_array_elements(\n'
 '      '
 "(expected_content->'metrics')||(expected_content->'features')||(expected_content->'prices'))\n"
 '      WITH ORDINALITY refs(entry,ordinality)\n'
 "      WHERE jsonb_typeof(entry->'source_ref')='object';\n"
 '   END IF;\n'
 "   IF r.operation='category.knowledge.promote' THEN\n"
 "    expected_refs='[]'::jsonb;\n"
 "    IF NEW.version<>1 OR NEW.action<>'add' OR confirmed_proof.subject_type<>'proposal'\n"
 '     OR confirmed_proof.subject_id IS DISTINCT FROM '
 "(confirmed_item->>'source_proposal_id')::uuid\n"
 '     OR confirmed_proof.revision IS DISTINCT FROM\n'
 "        (confirmed_item->>'source_proposal_revision')::integer\n"
 "     OR (confirmed_item->>'deidentified_confirmed')::boolean IS DISTINCT FROM true THEN\n"
 "     RAISE EXCEPTION 'promoted knowledge differs from confirmed source' USING ERRCODE='23514';\n"
 '    END IF;\n'
 '   ELSE\n'
 "    IF (NEW.version=1 AND (confirmed_item->>'supersedes' IS NOT NULL\n"
 "         OR confirmed_proof.subject_type<>'category'\n"
 '         OR confirmed_proof.subject_id<>NEW.category_id))\n'
 '     OR (NEW.version>1 AND (\n'
 "         (confirmed_item->'supersedes'->>'lineage_id')::uuid IS DISTINCT FROM NEW.lineage_id\n"
 "         OR (confirmed_item->'supersedes'->>'expected_version')::integer\n"
 '            IS DISTINCT FROM NEW.version-1\n'
 "         OR confirmed_proof.subject_type<>'category_knowledge'\n"
 '         OR confirmed_proof.subject_id<>NEW.lineage_id OR '
 'confirmed_proof.revision<>NEW.version-1)) THEN\n'
 "     RAISE EXCEPTION 'knowledge supersession differs from confirmation' USING ERRCODE='23514';\n"
 '    END IF;\n'
 '   END IF;\n'
 "   IF NEW.kind IS DISTINCT FROM confirmed_item->>'kind'\n"
 '    OR NEW.content IS DISTINCT FROM expected_content OR NEW.source_refs IS DISTINCT FROM '
 'expected_refs\n'
 "    OR to_jsonb(NEW.regions) IS DISTINCT FROM coalesce(confirmed_item->'regions','[]'::jsonb)\n"
 '    OR NEW.withdraw_reason IS NOT NULL THEN\n'
 "    RAISE EXCEPTION 'knowledge content differs from confirmation' USING ERRCODE='23514';\n"
 '   END IF;\n'
 '  END IF;\n'
 ' END IF;\n'
 " IF NEW.origin='human' OR (NEW.origin='imported' AND r.operation='category.create') THEN\n"
 '  IF NEW.writer_id<>r.actor_id OR r.actor_id<>r.requester_id\n'
 '   OR NEW.run_id IS NOT NULL OR NEW.confirmed_by IS NOT NULL\n'
 '   OR NEW.prepared_candidate_id IS NOT NULL OR r.agent_run_id IS NOT NULL\n'
 '   OR (confirmation_required AND (\n'
 "    confirmed_proof.snapshot->'payload'->>'prepared_by_run_id' IS NOT NULL\n"
 "    OR confirmed_proof.snapshot->'payload'->>'candidate_digest' IS NOT NULL))\n"
 '   OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=NEW.tenant_id\n'
 "    AND p.id=NEW.writer_id AND p.kind='human') THEN\n"
 "   RAISE EXCEPTION 'material human provenance mismatch' USING ERRCODE='23514';\n"
 '  END IF;\n'
 " ELSIF NEW.origin='ai_draft' THEN\n"
 "  IF r.operation='category.create' THEN\n"
 '   SELECT * INTO STRICT ar FROM agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;\n'
 '   IF NOT creation_ai OR ar.id::text IS DISTINCT FROM '
 "creation_proof.snapshot->'payload'->>'prepared_by_run_id'\n"
 '    OR NEW.writer_id<>ar.writer_id OR NEW.confirmed_by IS DISTINCT FROM r.actor_id\n'
 '    OR NEW.prepared_candidate_id IS NOT NULL OR r.agent_run_id IS NOT NULL THEN\n'
 "    RAISE EXCEPTION 'Initial material retains original AI writer and named category creator' "
 "USING ERRCODE='23514';\n"
 '   END IF;\n'
 '  ELSE\n'
 '  SELECT * INTO STRICT ar FROM agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;\n'
 '  IF ar.category_id IS DISTINCT FROM NEW.category_id OR ar.writer_id<>NEW.writer_id\n'
 "   OR ar.requester_id<>r.requester_id OR ar.reverted_at IS NOT NULL OR ar.state='cancelled'\n"
 '   OR r.agent_run_id IS DISTINCT FROM ar.id OR ar.product_id IS NOT NULL\n'
 '   OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=NEW.tenant_id\n'
 "    AND p.id=NEW.writer_id AND p.kind='agent') THEN\n"
 "   RAISE EXCEPTION 'material AI provenance mismatch' USING ERRCODE='23514';\n"
 '  END IF;\n'
 "  IF r.operation='category.knowledge.add' AND ar.private_context THEN\n"
 "   RAISE EXCEPTION 'private run cannot add shared knowledge' USING ERRCODE='23514';\n"
 '  END IF;\n'
 '  IF NEW.confirmed_by IS NULL THEN\n'
 "   IF r.operation<>'category.knowledge.add' OR r.actor_id<>ar.writer_id\n"
 '    OR NEW.prepared_candidate_id IS NOT NULL\n'
 "    OR (NEW.version>1 AND (prior.origin<>'ai_draft' OR prior.confirmed_by IS NOT NULL))\n"
 '    OR NOT EXISTS(SELECT 1 FROM agent_tool_calls tc WHERE tc.tenant_id=NEW.tenant_id\n'
 "     AND tc.run_id=ar.id AND tc.receipt_id=r.id AND tc.state='completed'\n"
 "     AND tc.execution_binding->>'operation'=r.operation) THEN\n"
 "    RAISE EXCEPTION 'material T0 requires its trusted call' USING ERRCODE='23514';\n"
 '   END IF;\n'
 '  ELSE\n'
 '   SELECT * INTO STRICT pc FROM proposal_prepared_candidates WHERE tenant_id=NEW.tenant_id\n'
 '    AND id=NEW.prepared_candidate_id;\n'
 '   IF NEW.confirmed_by<>r.actor_id OR r.actor_id<>r.requester_id\n'
 '    OR pc.category_id<>NEW.category_id OR pc.run_id<>ar.id OR pc.writer_id<>ar.writer_id\n'
 '    OR pc.requester_id<>r.requester_id OR pc.operation<>r.operation\n'
 "    OR ((confirmed_proof.snapshot->'payload')-ARRAY['prepared_by_run_id','candidate_digest'])\n"
 '       IS DISTINCT FROM pc.payload\n'
 "    OR confirmed_proof.snapshot->'payload'->>'prepared_by_run_id' IS DISTINCT FROM ar.id::text\n"
 "    OR confirmed_proof.snapshot->'payload'->>'candidate_digest' IS DISTINCT FROM "
 'pc.candidate_digest\n'
 "    OR (pc.execution_binding->'model'->>'cancel_epoch')::integer IS DISTINCT FROM "
 'ar.cancel_epoch\n'
 '    OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=NEW.tenant_id\n'
 "     AND p.id=NEW.confirmed_by AND p.kind='human') THEN\n"
 "    RAISE EXCEPTION 'material candidate confirmation mismatch' USING ERRCODE='23514';\n"
 '   END IF;\n'
 '  END IF;\n'
 '  END IF;\n'
 ' ELSE\n'
 "  RAISE EXCEPTION 'material import requires a registered import path' USING ERRCODE='23514';\n"
 ' END IF;\n'
 ' RETURN NULL;\n'
 'END $function$\n',
 'REVOKE ALL ON FUNCTION public.kernel_category_candidate_normalize(jsonb,text) FROM '
 'PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.kernel_category_snapshot_read_proven(uuid,uuid,uuid,uuid) FROM '
 'PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.kernel_category_creation_proven(uuid,uuid) FROM '
 'PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.kernel_category_candidate_guard() FROM '
 'PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch',
 'CREATE CONSTRAINT TRIGGER kernel_category_candidate AFTER INSERT ON public.categories DEFERRABLE '
 'INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.kernel_category_candidate_guard()',
 'CREATE TRIGGER kernel_category_original_run BEFORE UPDATE ON public.categories FOR EACH ROW '
 'EXECUTE FUNCTION public.kernel_category_candidate_guard()')

DOWNGRADE_SQL = ('DROP TRIGGER kernel_category_original_run ON public.categories',
 'DROP TRIGGER kernel_category_candidate ON public.categories',
 'CREATE OR REPLACE FUNCTION public.m3_material_atom()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 'DECLARE r action_receipts; ar agent_runs; pc proposal_prepared_candidates;\n'
 ' prior category_knowledge_entries;\n'
 ' expected_type text; identity uuid; latest integer;\n'
 ' confirmed_proof confirmations; confirmation_required boolean;\n'
 ' confirmation_xmin xid; receipt_xmin xid; material_xmin xid;\n'
 ' creation_proof category_creation_confirmations; position_index integer;\n'
 ' confirmed_item jsonb; expected_content jsonb; expected_refs jsonb; sample_count bigint;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=NEW.tenant_id AND '
 'id=NEW.receipt_id;\n'
 ' IF r.category_id IS DISTINCT FROM NEW.category_id OR r.product_id IS NOT NULL\n'
 '  OR r.actor_id IS DISTINCT FROM scope_actor() OR r.requester_id IS DISTINCT FROM '
 'scope_requester()\n'
 '  OR r.run_id IS NOT NULL THEN\n'
 "  RAISE EXCEPTION 'material receipt scope mismatch' USING ERRCODE='23514';\n"
 ' END IF;\n'
 '\n'
 " -- Row versions must originate in the receipt's transaction, not a later replay.\n"
 ' SELECT rr.xmin INTO STRICT receipt_xmin FROM action_receipts rr\n'
 '  WHERE rr.tenant_id=NEW.tenant_id AND rr.id=r.id;\n'
 " EXECUTE format('SELECT xmin FROM public.%I WHERE tenant_id=$1 AND id=$2', TG_TABLE_NAME)\n"
 '  INTO STRICT material_xmin USING NEW.tenant_id,NEW.id;\n'
 ' IF material_xmin IS DISTINCT FROM receipt_xmin THEN\n'
 "  RAISE EXCEPTION 'material and receipt must commit together' USING ERRCODE='23514';\n"
 ' END IF;\n'
 '\n'
 " confirmation_required=r.operation IN ('category.parameter.publish',\n"
 "  'category.knowledge.withdraw','category.knowledge.promote');\n"
 " IF TG_TABLE_NAME<>'promotion_proofs' THEN\n"
 '  confirmation_required=confirmation_required OR NEW.confirmed_by IS NOT NULL;\n'
 ' END IF;\n'
 ' IF confirmation_required THEN\n'
 '  -- Fetch the row and transaction identities separately: %ROWTYPE has no xmin.\n'
 '  SELECT * INTO STRICT confirmed_proof FROM confirmations cp\n'
 '   WHERE cp.tenant_id=NEW.tenant_id AND cp.id=r.confirmation_id;\n'
 '  SELECT cp.xmin INTO confirmation_xmin FROM confirmations cp\n'
 '   WHERE cp.tenant_id=NEW.tenant_id AND cp.id=r.confirmation_id;\n'
 '  IF confirmed_proof.consumed IS DISTINCT FROM true OR confirmed_proof.actor_id<>r.actor_id\n'
 '   OR confirmed_proof.category_id IS DISTINCT FROM r.category_id\n'
 '   OR confirmed_proof.operation<>r.operation OR confirmed_proof.product_id IS NOT NULL\n'
 '   OR confirmation_xmin IS DISTINCT FROM receipt_xmin\n'
 "   OR jsonb_typeof(confirmed_proof.snapshot->'payload') IS DISTINCT FROM 'object' THEN\n"
 "   RAISE EXCEPTION 'material requires its same-transaction consumed confirmation'\n"
 "    USING ERRCODE='23514';\n"
 '  END IF;\n'
 ' ELSE\n'
 '  IF r.confirmation_id IS NOT NULL THEN\n'
 "   RAISE EXCEPTION 'unconfirmed material cannot borrow a confirmation' USING ERRCODE='23514';\n"
 '  END IF;\n'
 ' END IF;\n'
 " IF r.operation='category.create' AND TG_TABLE_NAME IN\n"
 "  ('parameter_versions','category_knowledge_entries') THEN\n"
 '  SELECT * INTO STRICT creation_proof FROM category_creation_confirmations cp\n'
 '   WHERE cp.tenant_id=NEW.tenant_id AND cp.actor_id=r.actor_id\n'
 '    AND cp.reserved_category_id=NEW.category_id AND cp.consumed\n'
 '    AND cp.payload_digest=r.request_digest;\n'
 '  SELECT cp.xmin INTO STRICT confirmation_xmin FROM category_creation_confirmations cp\n'
 '   WHERE cp.tenant_id=NEW.tenant_id AND cp.id=creation_proof.id;\n'
 '  IF confirmation_xmin IS DISTINCT FROM receipt_xmin\n'
 '   OR (SELECT count(*) FROM action_receipts rr WHERE rr.tenant_id=NEW.tenant_id\n'
 "       AND rr.category_id=NEW.category_id AND rr.operation='category.create')<>1\n"
 "   OR creation_proof.snapshot->'payload'->>'prepared_by_run_id' IS NOT NULL\n"
 "   OR creation_proof.snapshot->'payload'->>'candidate_digest' IS NOT NULL\n"
 "   OR (creation_proof.snapshot->'payload'->>'deidentified_confirmed')::boolean\n"
 '      IS DISTINCT FROM true\n'
 "   OR r.subject_type<>'category' OR r.subject_id<>NEW.category_id\n"
 '   OR r.subject_revision<>1 OR NEW.version<>1\n'
 '   OR r.actor_id<>r.requester_id\n'
 '   OR NEW.origin IS DISTINCT FROM (CASE\n'
 "    WHEN creation_proof.snapshot->'payload'->>'seed_key' IS NULL THEN 'human' ELSE 'imported' "
 'END)\n'
 "   OR jsonb_typeof(r.result->'parameters') IS DISTINCT FROM 'array'\n"
 "   OR jsonb_typeof(r.result->'knowledge') IS DISTINCT FROM 'array'\n"
 "   OR jsonb_typeof(creation_proof.snapshot->'payload'->'groups'->'parameters')\n"
 "      IS DISTINCT FROM 'array'\n"
 "   OR jsonb_typeof(creation_proof.snapshot->'payload'->'groups'->'knowledge')\n"
 "      IS DISTINCT FROM 'array' THEN\n"
 "   RAISE EXCEPTION 'category material creation proof mismatch' USING ERRCODE='23514';\n"
 '  END IF;\n'
 "  IF jsonb_array_length(r.result->'parameters')<>\n"
 "      jsonb_array_length(creation_proof.snapshot->'payload'->'groups'->'parameters')\n"
 "   OR jsonb_array_length(r.result->'knowledge')<>\n"
 "      jsonb_array_length(creation_proof.snapshot->'payload'->'groups'->'knowledge')\n"
 "   OR jsonb_array_length(r.result->'parameters')<>(SELECT count(*) FROM parameter_versions v\n"
 '      WHERE v.tenant_id=NEW.tenant_id AND v.category_id=NEW.category_id AND v.receipt_id=r.id)\n'
 "   OR jsonb_array_length(r.result->'knowledge')<>(SELECT count(*) FROM "
 'category_knowledge_entries k\n'
 '      WHERE k.tenant_id=NEW.tenant_id AND k.category_id=NEW.category_id AND k.receipt_id=r.id) '
 'THEN\n'
 "   RAISE EXCEPTION 'category initial material manifest is incomplete' USING ERRCODE='23514';\n"
 '  END IF;\n'
 "  IF TG_TABLE_NAME='parameter_versions' THEN\n"
 '   SELECT (m.ordinality-1)::integer INTO STRICT position_index\n'
 "    FROM jsonb_array_elements(r.result->'parameters') WITH ORDINALITY m(item,ordinality)\n"
 "    WHERE m.item->>'parameter_id'=NEW.parameter_id::text\n"
 "     AND m.item->>'key'=NEW.key AND (m.item->>'version')::integer=NEW.version;\n"
 "   confirmed_item=creation_proof.snapshot->'payload'->'groups'->'parameters'->position_index;\n"
 '   IF '
 "(to_jsonb(NEW)-ARRAY['id','tenant_id','category_id','created_at','parameter_id','version',\n"
 "        'replaces_version','origin','writer_id','run_id','confirmed_by','receipt_id',\n"
 "        'prepared_candidate_id']) IS DISTINCT FROM confirmed_item THEN\n"
 "    RAISE EXCEPTION 'initial parameter differs from confirmed content' USING ERRCODE='23514';\n"
 '   END IF;\n'
 '  ELSE\n'
 '   SELECT (m.ordinality-1)::integer INTO STRICT position_index\n'
 "    FROM jsonb_array_elements(r.result->'knowledge') WITH ORDINALITY m(item,ordinality)\n"
 "    WHERE m.item->>'entry_id'=NEW.id::text AND m.item->>'lineage_id'=NEW.lineage_id::text\n"
 "     AND (m.item->>'version')::integer=NEW.version;\n"
 "   confirmed_item=creation_proof.snapshot->'payload'->'groups'->'knowledge'->position_index;\n"
 "   expected_content=confirmed_item->'content';\n"
 "   expected_refs=confirmed_item->'source_refs';\n"
 "   IF confirmed_item->>'kind'='voice' THEN\n"
 "    expected_refs=expected_refs||(expected_content->'representative_refs');\n"
 "    SELECT count(DISTINCT ROW(ref->>'id',ref->>'version',ref->>'line'))\n"
 '     INTO sample_count FROM jsonb_array_elements(expected_refs) ref;\n'
 "    expected_content=expected_content||jsonb_build_object('sample_size',sample_count);\n"
 "   ELSIF confirmed_item->>'kind'='competitor' THEN\n"
 "    SELECT expected_refs||coalesce(jsonb_agg(entry->'source_ref' ORDER BY ordinality), "
 "'[]'::jsonb)\n"
 '     INTO expected_refs FROM jsonb_array_elements(\n'
 '      '
 "(expected_content->'metrics')||(expected_content->'features')||(expected_content->'prices'))\n"
 '      WITH ORDINALITY refs(entry,ordinality)\n'
 "      WHERE jsonb_typeof(entry->'source_ref')='object';\n"
 '   END IF;\n'
 "   IF NEW.kind IS DISTINCT FROM confirmed_item->>'kind'\n"
 '    OR NEW.content IS DISTINCT FROM expected_content\n'
 "    OR to_jsonb(NEW.regions) IS DISTINCT FROM confirmed_item->'regions'\n"
 '    OR NEW.source_refs IS DISTINCT FROM expected_refs\n'
 "    OR NEW.action<>'add' OR NEW.withdraw_reason IS NOT NULL THEN\n"
 "    RAISE EXCEPTION 'initial knowledge differs from confirmed content' USING ERRCODE='23514';\n"
 '   END IF;\n'
 '  END IF;\n'
 ' END IF;\n'
 " IF TG_TABLE_NAME='promotion_proofs' THEN\n"
 "  IF NEW.id::text IS DISTINCT FROM r.result->>'promotion_proof_id'\n"
 "   OR confirmed_proof.subject_type<>'proposal'\n"
 '   OR confirmed_proof.subject_id<>NEW.source_proposal_id\n'
 '   OR confirmed_proof.revision<>NEW.source_proposal_revision\n'
 "   OR (confirmed_proof.snapshot->'payload'->>'source_proposal_id')::uuid\n"
 '      IS DISTINCT FROM NEW.source_proposal_id\n'
 "   OR (confirmed_proof.snapshot->'payload'->>'source_proposal_revision')::integer\n"
 '      IS DISTINCT FROM NEW.source_proposal_revision\n'
 "   OR confirmed_proof.snapshot->'payload'->'source_item_refs' IS DISTINCT FROM "
 'NEW.source_item_refs\n'
 "   OR (confirmed_proof.snapshot->'payload'->>'deidentified_confirmed')::boolean IS DISTINCT FROM "
 'true\n'
 "   OR r.operation<>'category.knowledge.promote' OR r.actor_id<>NEW.deidentified_by\n"
 '   OR r.actor_id<>r.requester_id OR NOT EXISTS(SELECT 1 FROM principals p\n'
 "    WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.deidentified_by AND p.kind='human')\n"
 '   OR NOT EXISTS(SELECT 1 FROM category_knowledge_entries k WHERE k.tenant_id=NEW.tenant_id\n'
 '    AND k.category_id=NEW.category_id AND k.id=NEW.knowledge_entry_id AND k.receipt_id=r.id\n'
 "    AND r.subject_type='category_knowledge' AND r.subject_id=k.lineage_id\n"
 '    AND r.subject_revision=k.version)\n'
 '   OR NOT EXISTS(SELECT 1 FROM proposal_revisions pv WHERE pv.tenant_id=NEW.tenant_id\n'
 '    AND pv.category_id=NEW.category_id AND pv.proposal_id=NEW.source_proposal_id\n'
 '    AND pv.revision=NEW.source_proposal_revision)\n'
 "   OR NOT coalesce((NEW.checks->>'refs_clean')::boolean,false)\n"
 "   OR NOT coalesce((NEW.checks->>'filenames_clean')::boolean,false)\n"
 "   OR NOT coalesce((NEW.checks->>'identities_clean')::boolean,false) THEN\n"
 "   RAISE EXCEPTION 'promotion proof does not bind the named receipt' USING ERRCODE='23514';\n"
 '  END IF;\n'
 '  RETURN NULL;\n'
 ' END IF;\n'
 " IF TG_TABLE_NAME='parameter_versions' THEN\n"
 "  expected_type='parameter'; identity=NEW.parameter_id;\n"
 "  IF r.operation NOT IN ('category.parameter.publish','category.create') THEN\n"
 "   RAISE EXCEPTION 'parameter receipt operation mismatch' USING ERRCODE='23514';\n"
 '  END IF;\n'
 '  SELECT max(version) INTO latest FROM parameter_versions WHERE tenant_id=NEW.tenant_id\n'
 '   AND parameter_id=NEW.parameter_id;\n'
 '  IF NOT EXISTS(SELECT 1 FROM parameter_current c WHERE c.tenant_id=NEW.tenant_id\n'
 '   AND c.category_id=NEW.category_id AND c.parameter_id=NEW.parameter_id\n'
 '   AND c.key=NEW.key AND c.current_version=latest)\n'
 '   OR (NEW.version=1 AND NEW.replaces_version IS NOT NULL)\n'
 '   OR (NEW.version>1 AND (NEW.replaces_version IS DISTINCT FROM NEW.version-1\n'
 '    OR NOT EXISTS(SELECT 1 FROM parameter_versions v WHERE v.tenant_id=NEW.tenant_id\n'
 '     AND v.category_id=NEW.category_id AND v.parameter_id=NEW.parameter_id\n'
 '     AND v.version=NEW.version-1 AND v.key=NEW.key))) THEN\n'
 "   RAISE EXCEPTION 'parameter version and current must commit together' USING ERRCODE='23514';\n"
 '  END IF;\n'
 ' ELSE\n'
 "  expected_type='category_knowledge'; identity=NEW.lineage_id;\n"
 "  IF r.operation NOT IN ('category.knowledge.add','category.knowledge.withdraw',\n"
 "   'category.knowledge.promote','category.create')\n"
 "   OR (NEW.action='withdraw') IS DISTINCT FROM (r.operation='category.knowledge.withdraw') THEN\n"
 "   RAISE EXCEPTION 'knowledge receipt operation mismatch' USING ERRCODE='23514';\n"
 '  END IF;\n'
 '  SELECT max(version) INTO latest FROM category_knowledge_entries WHERE tenant_id=NEW.tenant_id\n'
 '   AND lineage_id=NEW.lineage_id;\n'
 '  IF NOT EXISTS(SELECT 1 FROM category_knowledge_current c WHERE c.tenant_id=NEW.tenant_id\n'
 '   AND c.category_id=NEW.category_id AND c.lineage_id=NEW.lineage_id AND '
 'c.current_version=latest)\n'
 "   OR (NEW.version=1 AND NEW.action<>'add') THEN\n"
 "   RAISE EXCEPTION 'knowledge entry and current must commit together' USING ERRCODE='23514';\n"
 '  END IF;\n'
 '  IF NEW.version>1 THEN\n'
 '   SELECT * INTO STRICT prior FROM category_knowledge_entries WHERE tenant_id=NEW.tenant_id\n'
 '    AND category_id=NEW.category_id AND lineage_id=NEW.lineage_id AND version=NEW.version-1;\n'
 "   IF NEW.kind<>prior.kind OR NEW.action='add' THEN\n"
 "    RAISE EXCEPTION 'knowledge lineage mismatch' USING ERRCODE='23514';\n"
 '   END IF;\n'
 '  END IF;\n'
 "  IF r.operation='category.knowledge.promote' AND NOT EXISTS(SELECT 1 FROM promotion_proofs p\n"
 '   WHERE p.tenant_id=NEW.tenant_id AND p.knowledge_entry_id=NEW.id AND p.receipt_id=r.id) THEN\n'
 "   RAISE EXCEPTION 'promotion requires its private proof' USING ERRCODE='23514';\n"
 '  END IF;\n'
 ' END IF;\n'
 ' IF NOT ((r.subject_type=expected_type AND r.subject_id=identity AND '
 'r.subject_revision=NEW.version)\n'
 "  OR (r.operation='category.create' AND r.subject_type='category'\n"
 '   AND r.subject_id=NEW.category_id AND NEW.version=1)) THEN\n'
 "  RAISE EXCEPTION 'material receipt subject mismatch' USING ERRCODE='23514';\n"
 ' END IF;\n'
 '\n'
 ' IF confirmation_required THEN\n'
 "  confirmed_item=confirmed_proof.snapshot->'payload';\n"
 "  IF TG_TABLE_NAME='parameter_versions' THEN\n"
 '   IF '
 "(to_jsonb(NEW)-ARRAY['id','tenant_id','category_id','created_at','parameter_id','version',\n"
 "        'replaces_version','origin','writer_id','run_id','confirmed_by','receipt_id',\n"
 "        'prepared_candidate_id']) IS DISTINCT FROM\n"
 "       (confirmed_item-ARRAY['parameter_id','expected_current_version','prepared_by_run_id',\n"
 "                            'candidate_digest'])\n"
 "    OR (confirmed_item->>'expected_current_version')::integer IS DISTINCT FROM NEW.version-1\n"
 "    OR (NEW.version=1 AND confirmed_item->>'parameter_id' IS NOT NULL)\n"
 "    OR (NEW.version>1 AND (confirmed_item->>'parameter_id')::uuid\n"
 '        IS DISTINCT FROM NEW.parameter_id)\n'
 "    OR (NEW.version=1 AND (confirmed_proof.subject_type<>'category'\n"
 '         OR confirmed_proof.subject_id<>NEW.category_id))\n'
 "    OR (NEW.version>1 AND (confirmed_proof.subject_type<>'parameter'\n"
 '         OR confirmed_proof.subject_id<>NEW.parameter_id\n'
 '         OR confirmed_proof.revision<>NEW.version-1)) THEN\n'
 "    RAISE EXCEPTION 'published parameter differs from confirmation' USING ERRCODE='23514';\n"
 '   END IF;\n'
 "  ELSIF r.operation='category.knowledge.withdraw' THEN\n"
 "   IF (confirmed_item->>'lineage_id')::uuid IS DISTINCT FROM NEW.lineage_id\n"
 "    OR (confirmed_item->>'expected_version')::integer IS DISTINCT FROM NEW.version-1\n"
 "    OR confirmed_item->>'reason' IS DISTINCT FROM NEW.withdraw_reason\n"
 '    OR coalesce(length(NEW.withdraw_reason),0)=0\n'
 "    OR confirmed_proof.subject_type<>'category_knowledge'\n"
 '    OR confirmed_proof.subject_id<>NEW.lineage_id OR confirmed_proof.revision<>NEW.version-1\n'
 '    OR NEW.content IS DISTINCT FROM prior.content OR NEW.regions IS DISTINCT FROM prior.regions\n'
 '    OR NEW.source_refs IS DISTINCT FROM prior.source_refs THEN\n'
 "    RAISE EXCEPTION 'knowledge withdrawal differs from confirmation or prior version'\n"
 "     USING ERRCODE='23514';\n"
 '   END IF;\n'
 '  ELSE\n'
 "   expected_content=confirmed_item->'content';\n"
 "   expected_refs=coalesce(confirmed_item->'source_refs','[]'::jsonb);\n"
 "   IF confirmed_item->>'kind'='voice' THEN\n"
 "    expected_refs=expected_refs||(expected_content->'representative_refs');\n"
 "    SELECT count(DISTINCT ROW(ref->>'id',ref->>'version',ref->>'line'))\n"
 '     INTO sample_count FROM jsonb_array_elements(expected_refs) ref;\n'
 "    expected_content=expected_content||jsonb_build_object('sample_size',sample_count);\n"
 "   ELSIF confirmed_item->>'kind'='competitor' THEN\n"
 "    SELECT expected_refs||coalesce(jsonb_agg(entry->'source_ref' ORDER BY ordinality), "
 "'[]'::jsonb)\n"
 '     INTO expected_refs FROM jsonb_array_elements(\n'
 '      '
 "(expected_content->'metrics')||(expected_content->'features')||(expected_content->'prices'))\n"
 '      WITH ORDINALITY refs(entry,ordinality)\n'
 "      WHERE jsonb_typeof(entry->'source_ref')='object';\n"
 '   END IF;\n'
 "   IF r.operation='category.knowledge.promote' THEN\n"
 "    expected_refs='[]'::jsonb;\n"
 "    IF NEW.version<>1 OR NEW.action<>'add' OR confirmed_proof.subject_type<>'proposal'\n"
 '     OR confirmed_proof.subject_id IS DISTINCT FROM '
 "(confirmed_item->>'source_proposal_id')::uuid\n"
 '     OR confirmed_proof.revision IS DISTINCT FROM\n'
 "        (confirmed_item->>'source_proposal_revision')::integer\n"
 "     OR (confirmed_item->>'deidentified_confirmed')::boolean IS DISTINCT FROM true THEN\n"
 "     RAISE EXCEPTION 'promoted knowledge differs from confirmed source' USING ERRCODE='23514';\n"
 '    END IF;\n'
 '   ELSE\n'
 "    IF (NEW.version=1 AND (confirmed_item->>'supersedes' IS NOT NULL\n"
 "         OR confirmed_proof.subject_type<>'category'\n"
 '         OR confirmed_proof.subject_id<>NEW.category_id))\n'
 '     OR (NEW.version>1 AND (\n'
 "         (confirmed_item->'supersedes'->>'lineage_id')::uuid IS DISTINCT FROM NEW.lineage_id\n"
 "         OR (confirmed_item->'supersedes'->>'expected_version')::integer\n"
 '            IS DISTINCT FROM NEW.version-1\n'
 "         OR confirmed_proof.subject_type<>'category_knowledge'\n"
 '         OR confirmed_proof.subject_id<>NEW.lineage_id OR '
 'confirmed_proof.revision<>NEW.version-1)) THEN\n'
 "     RAISE EXCEPTION 'knowledge supersession differs from confirmation' USING ERRCODE='23514';\n"
 '    END IF;\n'
 '   END IF;\n'
 "   IF NEW.kind IS DISTINCT FROM confirmed_item->>'kind'\n"
 '    OR NEW.content IS DISTINCT FROM expected_content OR NEW.source_refs IS DISTINCT FROM '
 'expected_refs\n'
 "    OR to_jsonb(NEW.regions) IS DISTINCT FROM coalesce(confirmed_item->'regions','[]'::jsonb)\n"
 '    OR NEW.withdraw_reason IS NOT NULL THEN\n'
 "    RAISE EXCEPTION 'knowledge content differs from confirmation' USING ERRCODE='23514';\n"
 '   END IF;\n'
 '  END IF;\n'
 ' END IF;\n'
 " IF NEW.origin='human' OR (NEW.origin='imported' AND r.operation='category.create') THEN\n"
 '  IF NEW.writer_id<>r.actor_id OR r.actor_id<>r.requester_id\n'
 '   OR NEW.run_id IS NOT NULL OR NEW.confirmed_by IS NOT NULL\n'
 '   OR NEW.prepared_candidate_id IS NOT NULL OR r.agent_run_id IS NOT NULL\n'
 '   OR (confirmation_required AND (\n'
 "    confirmed_proof.snapshot->'payload'->>'prepared_by_run_id' IS NOT NULL\n"
 "    OR confirmed_proof.snapshot->'payload'->>'candidate_digest' IS NOT NULL))\n"
 '   OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=NEW.tenant_id\n'
 "    AND p.id=NEW.writer_id AND p.kind='human') THEN\n"
 "   RAISE EXCEPTION 'material human provenance mismatch' USING ERRCODE='23514';\n"
 '  END IF;\n'
 " ELSIF NEW.origin='ai_draft' THEN\n"
 '  SELECT * INTO STRICT ar FROM agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;\n'
 '  IF ar.category_id IS DISTINCT FROM NEW.category_id OR ar.writer_id<>NEW.writer_id\n'
 "   OR ar.requester_id<>r.requester_id OR ar.reverted_at IS NOT NULL OR ar.state='cancelled'\n"
 '   OR r.agent_run_id IS DISTINCT FROM ar.id OR ar.product_id IS NOT NULL\n'
 '   OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=NEW.tenant_id\n'
 "    AND p.id=NEW.writer_id AND p.kind='agent') THEN\n"
 "   RAISE EXCEPTION 'material AI provenance mismatch' USING ERRCODE='23514';\n"
 '  END IF;\n'
 "  IF r.operation='category.knowledge.add' AND ar.private_context THEN\n"
 "   RAISE EXCEPTION 'private run cannot add shared knowledge' USING ERRCODE='23514';\n"
 '  END IF;\n'
 '  IF NEW.confirmed_by IS NULL THEN\n'
 "   IF r.operation<>'category.knowledge.add' OR r.actor_id<>ar.writer_id\n"
 '    OR NEW.prepared_candidate_id IS NOT NULL\n'
 "    OR (NEW.version>1 AND (prior.origin<>'ai_draft' OR prior.confirmed_by IS NOT NULL))\n"
 '    OR NOT EXISTS(SELECT 1 FROM agent_tool_calls tc WHERE tc.tenant_id=NEW.tenant_id\n'
 "     AND tc.run_id=ar.id AND tc.receipt_id=r.id AND tc.state='completed'\n"
 "     AND tc.execution_binding->>'operation'=r.operation) THEN\n"
 "    RAISE EXCEPTION 'material T0 requires its trusted call' USING ERRCODE='23514';\n"
 '   END IF;\n'
 '  ELSE\n'
 '   SELECT * INTO STRICT pc FROM proposal_prepared_candidates WHERE tenant_id=NEW.tenant_id\n'
 '    AND id=NEW.prepared_candidate_id;\n'
 '   IF NEW.confirmed_by<>r.actor_id OR r.actor_id<>r.requester_id\n'
 '    OR pc.category_id<>NEW.category_id OR pc.run_id<>ar.id OR pc.writer_id<>ar.writer_id\n'
 '    OR pc.requester_id<>r.requester_id OR pc.operation<>r.operation\n'
 "    OR ((confirmed_proof.snapshot->'payload')-ARRAY['prepared_by_run_id','candidate_digest'])\n"
 '       IS DISTINCT FROM pc.payload\n'
 "    OR confirmed_proof.snapshot->'payload'->>'prepared_by_run_id' IS DISTINCT FROM ar.id::text\n"
 "    OR confirmed_proof.snapshot->'payload'->>'candidate_digest' IS DISTINCT FROM "
 'pc.candidate_digest\n'
 "    OR (pc.execution_binding->'model'->>'cancel_epoch')::integer IS DISTINCT FROM "
 'ar.cancel_epoch\n'
 '    OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=NEW.tenant_id\n'
 "     AND p.id=NEW.confirmed_by AND p.kind='human') THEN\n"
 "    RAISE EXCEPTION 'material candidate confirmation mismatch' USING ERRCODE='23514';\n"
 '   END IF;\n'
 '  END IF;\n'
 ' ELSE\n'
 "  RAISE EXCEPTION 'material import requires a registered import path' USING ERRCODE='23514';\n"
 ' END IF;\n'
 ' RETURN NULL;\n'
 'END $function$\n',
 'DROP FUNCTION public.kernel_category_candidate_guard()',
 'DROP FUNCTION public.kernel_category_creation_proven(uuid,uuid)',
 'DROP FUNCTION public.kernel_category_snapshot_read_proven(uuid,uuid,uuid,uuid)',
 'DROP FUNCTION public.kernel_category_candidate_normalize(jsonb,text)')
