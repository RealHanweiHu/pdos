# ruff: noqa: E501
"""Frozen category adoption and the predecessor JSON precedence repair."""

SCHEMA_SQL = ('CREATE OR REPLACE FUNCTION public.kernel_category_creation_proven(t uuid, cid uuid)\n'
 ' RETURNS boolean\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
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
 "  OR ((input->'groups')-ARRAY['knowledge','parameters','snapshot_refs'])<>'{}'::jsonb\n"
 "  OR ((payload->'groups')-ARRAY['knowledge','parameters','snapshot_refs'])<>'{}'::jsonb\n"
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
 'END $function$\n',
 'CREATE FUNCTION public.kernel_category_adoption_valid(t uuid, iid uuid) RETURNS boolean\n'
 'LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS '
 '$function$\n'
 'DECLARE answer agent_run_inputs; run agent_runs; conversation agent_sessions;\n'
 ' receipt action_receipts; category categories; candidate agent_run_events; adopted '
 'agent_run_events;\n'
 ' expected jsonb; ix xid; rx xid; ex xid;\n'
 'BEGIN\n'
 ' SELECT * INTO answer FROM agent_run_inputs WHERE tenant_id=t AND id=iid;\n'
 ' SELECT * INTO run FROM agent_runs WHERE tenant_id=t AND id=answer.run_id;\n'
 ' SELECT * INTO conversation FROM agent_sessions WHERE tenant_id=t AND id=run.session_id;\n'
 ' IF answer.id IS NULL OR run.id IS NULL OR conversation.id IS NULL\n'
 '  OR answer.requester_id IS DISTINCT FROM run.requester_id OR conversation.owner_id IS DISTINCT '
 'FROM run.requester_id\n'
 '  OR conversation.category_id IS DISTINCT FROM run.category_id OR conversation.product_id IS '
 'DISTINCT FROM run.product_id\n'
 '  OR conversation.proposal_id IS DISTINCT FROM run.proposal_id\n'
 '  OR run.category_id IS NOT NULL OR run.product_id IS NOT NULL OR run.proposal_id IS NOT NULL\n'
 "  OR run.private_context OR run.customer_identities IS DISTINCT FROM '[]'::jsonb\n"
 "  OR run.read_sources IS DISTINCT FROM '[]'::jsonb\n"
 "  OR coalesce(run.data_categories ?| ARRAY['customer','customer_original'],true)\n"
 '  OR run.reverted_at IS NOT NULL OR run.state NOT IN '
 "('queued','running','waiting_input','completed','partial')\n"
 '  OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=t AND p.id=run.requester_id AND '
 "p.kind='human' AND p.active)\n"
 '  OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=t AND p.id=run.writer_id AND '
 "p.kind='agent' AND p.active)\n"
 '  THEN RETURN false; END IF;\n'
 ' -- Cast only closed server references. Malformed or missing references fail closed.\n'
 ' SELECT * INTO receipt FROM action_receipts WHERE tenant_id=t AND '
 "id=(answer.answers->>'receipt_id')::uuid;\n"
 ' SELECT * INTO category FROM categories WHERE tenant_id=t AND id=receipt.category_id;\n'
 ' SELECT * INTO candidate FROM agent_run_events WHERE tenant_id=t AND run_id=run.id\n'
 "  AND id=(answer.answers->>'candidate_event_id')::uuid;\n"
 ' IF receipt.id IS NULL OR category.id IS NULL OR candidate.id IS NULL\n'
 "  OR receipt.operation IS DISTINCT FROM 'category.create' OR receipt.subject_type IS DISTINCT "
 "FROM 'category'\n"
 '  OR receipt.subject_id IS DISTINCT FROM category.id OR receipt.subject_revision IS DISTINCT '
 'FROM 1\n'
 '  OR receipt.actor_id IS DISTINCT FROM run.requester_id OR receipt.requester_id IS DISTINCT FROM '
 'run.requester_id\n'
 '  OR receipt.product_id IS NOT NULL OR receipt.run_id IS NOT NULL OR receipt.agent_run_id IS NOT '
 'NULL\n'
 "  OR receipt.confirmation_id IS NOT NULL OR receipt.result->'proof_version' IS DISTINCT FROM "
 "'1'::jsonb\n"
 "  OR receipt.result->>'origin' IS DISTINCT FROM 'ai_draft'\n"
 "  OR receipt.result->>'category_id' IS DISTINCT FROM category.id::text\n"
 "  OR receipt.result->>'prepared_by_run_id' IS DISTINCT FROM run.id::text\n"
 "  OR receipt.result->>'registered_by_run_id' IS DISTINCT FROM run.id::text\n"
 "  OR receipt.result->>'category_candidate_event_id' IS DISTINCT FROM candidate.id::text\n"
 "  OR receipt.result->>'candidate_digest' IS DISTINCT FROM candidate.body->>'candidate_digest'\n"
 "  OR receipt.result->>'adoption_input_ref' IS DISTINCT FROM answer.id::text\n"
 '  OR category.created_by_run_id IS DISTINCT FROM run.id OR category.owner_id IS DISTINCT FROM '
 'run.requester_id\n'
 "  OR candidate.body->>'type' IS DISTINCT FROM 'category_candidate'\n"
 "  OR candidate.body->>'session_id' IS DISTINCT FROM run.session_id::text\n"
 "  OR candidate.body->'cancel_epoch' IS DISTINCT FROM to_jsonb(run.cancel_epoch)\n"
 "  OR NOT coalesce(candidate.body->>'candidate_digest' ~ '^[a-f0-9]{64}$',false) THEN RETURN "
 'false; END IF;\n'
 ' '
 "expected=jsonb_build_object('type','category_adoption','proof_version',1,'candidate_event_id',candidate.id,\n"
 '  '
 "'candidate_digest',candidate.body->'candidate_digest','receipt_id',receipt.id,'category_id',category.id,\n"
 "  'run_id',run.id,'cancel_epoch',run.cancel_epoch);\n"
 ' IF answer.answers IS DISTINCT FROM expected\n'
 "  OR answer.idempotency_key IS DISTINCT FROM 'category-adoption:'||candidate.id::text\n"
 '  OR answer.payload_digest IS DISTINCT FROM '
 "encode(sha256(convert_to(kernel_read_canonical_json(expected),'UTF8')),'hex')\n"
 '  OR (SELECT count(*) FROM agent_run_inputs a WHERE a.tenant_id=t AND a.run_id=run.id\n'
 "    AND (a.answers->>'receipt_id'=receipt.id::text OR "
 'a.idempotency_key=answer.idempotency_key))<>1\n'
 '  OR (SELECT count(*) FROM agent_run_events e WHERE e.tenant_id=t AND e.run_id=run.id\n'
 "    AND e.body->>'type'='category_adopted' AND (e.body->>'input_ref'=answer.id::text\n"
 "     OR e.body->>'receipt_id'=receipt.id::text OR "
 "e.body->>'candidate_event_id'=candidate.id::text))<>1\n"
 '  THEN RETURN false; END IF;\n'
 ' SELECT * INTO adopted FROM agent_run_events WHERE tenant_id=t AND run_id=run.id\n'
 "  AND body->>'type'='category_adopted' AND body->>'input_ref'=answer.id::text;\n"
 ' IF adopted.id IS NULL OR adopted.sequence<=candidate.sequence\n'
 '  OR adopted.body IS DISTINCT FROM '
 "expected||jsonb_build_object('type','category_adopted','input_ref',answer.id)\n"
 '  THEN RETURN false; END IF;\n'
 ' -- These three rows are append-only; their transaction identities remain stable\n'
 ' -- after delivery. Outbox xmin is deliberately excluded because its lease changes.\n'
 ' SELECT xmin INTO ix FROM agent_run_inputs WHERE tenant_id=t AND id=answer.id;\n'
 ' SELECT xmin INTO rx FROM action_receipts WHERE tenant_id=t AND id=receipt.id;\n'
 ' SELECT xmin INTO ex FROM agent_run_events WHERE tenant_id=t AND id=adopted.id;\n'
 ' RETURN ix IS NOT DISTINCT FROM rx AND ex IS NOT DISTINCT FROM rx;\n'
 'EXCEPTION WHEN data_exception THEN RETURN false;\n'
 'END $function$',
 'CREATE FUNCTION public.kernel_category_adoption_assert(t uuid, iid uuid) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $function$\n'
 'DECLARE answer agent_run_inputs; receipt action_receipts; event outbox_events; rx xid; ox xid;\n'
 'BEGIN\n'
 ' IF kernel_category_adoption_valid(t,iid) IS DISTINCT FROM true THEN\n'
 "  RAISE EXCEPTION 'Category adoption requires its exact input, event and creation receipt' USING "
 "ERRCODE='23514'; END IF;\n"
 ' SELECT * INTO STRICT answer FROM agent_run_inputs WHERE tenant_id=t AND id=iid;\n'
 ' SELECT * INTO STRICT receipt FROM action_receipts WHERE tenant_id=t AND '
 "id=(answer.answers->>'receipt_id')::uuid;\n"
 " IF t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid\n"
 '  OR answer.requester_id IS DISTINCT FROM scope_actor() OR answer.requester_id IS DISTINCT FROM '
 'scope_requester()\n'
 '  OR kernel_category_creation_proven(t,receipt.category_id) IS DISTINCT FROM true THEN\n'
 "  RAISE EXCEPTION 'Category adoption must consume the actual named personal-Run candidate' USING "
 "ERRCODE='23514'; END IF;\n"
 ' SELECT xmin INTO rx FROM action_receipts WHERE tenant_id=t AND id=receipt.id;\n'
 ' -- A legitimate command uses a savepoint, whose row xmin is a subtransaction\n'
 ' -- ID. Fresh INSERT triggers plus all four matching xmin values bind the atom\n'
 ' -- without incorrectly comparing those IDs to the top-level transaction ID.\n'
 ' IF (SELECT count(*) FROM outbox_events o WHERE o.tenant_id=t AND o.receipt_id=receipt.id AND '
 "o.type='category.created')<>1 THEN\n"
 "  RAISE EXCEPTION 'Category adoption and delivery must commit with creation' USING "
 "ERRCODE='23514'; END IF;\n"
 ' SELECT * INTO STRICT event FROM outbox_events WHERE tenant_id=t AND receipt_id=receipt.id AND '
 "type='category.created';\n"
 ' SELECT xmin INTO ox FROM outbox_events WHERE tenant_id=t AND id=event.id;\n'
 ' IF ox IS DISTINCT FROM rx OR event.category_id IS DISTINCT FROM receipt.category_id\n'
 '  OR event.subject_id IS DISTINCT FROM receipt.subject_id OR event.subject_revision IS DISTINCT '
 'FROM receipt.subject_revision\n'
 '  OR event.actor_id IS DISTINCT FROM receipt.actor_id OR event.correlation_id IS DISTINCT FROM '
 'receipt.command_id\n'
 '  OR event.schema_version IS DISTINCT FROM 1 THEN\n'
 "  RAISE EXCEPTION 'Category adoption delivery envelope differs from creation' USING "
 "ERRCODE='23514'; END IF;\n"
 'END $function$',
 'CREATE FUNCTION public.kernel_input_insert_guard() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $function$\n'
 'DECLARE run agent_runs; conversation agent_sessions;\n'
 'BEGIN\n'
 ' SELECT * INTO run FROM agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id FOR SHARE;\n'
 ' SELECT * INTO conversation FROM agent_sessions WHERE tenant_id=NEW.tenant_id AND '
 'id=run.session_id;\n'
 ' IF run.id IS NULL OR conversation.id IS NULL\n'
 "  OR NEW.tenant_id IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid\n"
 '  OR NEW.requester_id IS DISTINCT FROM run.requester_id OR NEW.requester_id IS DISTINCT FROM '
 'scope_actor()\n'
 '  OR NEW.requester_id IS DISTINCT FROM scope_requester() OR conversation.owner_id IS DISTINCT '
 'FROM run.requester_id\n'
 '  OR conversation.category_id IS DISTINCT FROM run.category_id OR conversation.product_id IS '
 'DISTINCT FROM run.product_id\n'
 '  OR conversation.proposal_id IS DISTINCT FROM run.proposal_id OR run.reverted_at IS NOT NULL\n'
 '  OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=NEW.tenant_id AND '
 "p.id=NEW.requester_id AND p.kind='human' AND p.active)\n"
 "  OR jsonb_typeof(NEW.answers) IS DISTINCT FROM 'object' THEN\n"
 "  RAISE EXCEPTION 'Run input requires its current Human, Run and Session' USING ERRCODE='23514'; "
 'END IF;\n'
 " IF NEW.answers->>'type'='category_adoption' THEN\n"
 "  IF run.state NOT IN ('queued','running','waiting_input','completed','partial') THEN\n"
 "   RAISE EXCEPTION 'Stopped Run cannot adopt a category' USING ERRCODE='23514'; END IF;\n"
 ' ELSE\n'
 "  IF NEW.answers->>'type'='category_adopted' OR NEW.idempotency_key LIKE 'category-adoption:%'\n"
 "   OR run.state<>'waiting_input' THEN\n"
 "   RAISE EXCEPTION 'Ordinary answers require a waiting Run and cannot impersonate adoption' "
 "USING ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 ' RETURN NEW;\n'
 'END $function$',
 'CREATE FUNCTION public.kernel_category_adoption_guard() RETURNS trigger\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $function$\n'
 'DECLARE iid uuid; receipt action_receipts; answer agent_run_inputs;\n'
 'BEGIN\n'
 " IF TG_TABLE_NAME='agent_run_inputs' THEN\n"
 "  IF NEW.answers->>'type' IS DISTINCT FROM 'category_adoption' THEN RETURN NULL; END IF;\n"
 '  iid=NEW.id;\n'
 " ELSIF TG_TABLE_NAME='agent_run_events' THEN\n"
 "  IF NEW.body->>'type'='category_adoption' THEN\n"
 "   RAISE EXCEPTION 'Category adoption is a committed input, not an unbound event' USING "
 "ERRCODE='23514'; END IF;\n"
 "  IF NEW.body->>'type' IS DISTINCT FROM 'category_adopted' THEN RETURN NULL; END IF;\n"
 "  iid=(NEW.body->>'input_ref')::uuid;\n"
 '  SELECT * INTO answer FROM agent_run_inputs WHERE tenant_id=NEW.tenant_id AND id=iid;\n'
 '  IF answer.id IS NULL OR NEW.run_id IS DISTINCT FROM answer.run_id\n'
 '   OR NEW.body IS DISTINCT FROM '
 "answer.answers||jsonb_build_object('type','category_adopted','input_ref',answer.id) THEN\n"
 "   RAISE EXCEPTION 'Adoption event must reference its own Run input exactly' USING "
 "ERRCODE='23514'; END IF;\n"
 " ELSIF TG_TABLE_NAME='action_receipts' THEN\n"
 "  IF NEW.operation<>'category.create' THEN RETURN NULL; END IF;\n"
 '  receipt=NEW;\n'
 " ELSIF TG_TABLE_NAME='outbox_events' THEN\n"
 "  IF NEW.type<>'category.created' THEN RETURN NULL; END IF;\n"
 '  SELECT * INTO STRICT receipt FROM action_receipts WHERE tenant_id=NEW.tenant_id AND '
 'id=NEW.receipt_id;\n'
 " ELSE RAISE EXCEPTION 'Unknown category adoption atom' USING ERRCODE='23514';\n"
 ' END IF;\n'
 ' IF receipt.id IS NOT NULL THEN\n'
 "  IF receipt.result->>'origin' IS DISTINCT FROM 'ai_draft' AND "
 "receipt.result->>'prepared_by_run_id' IS NULL\n"
 '   AND NOT EXISTS(SELECT 1 FROM categories c WHERE c.tenant_id=receipt.tenant_id AND '
 'c.id=receipt.category_id AND c.created_by_run_id IS NOT NULL)\n'
 '   THEN RETURN NULL; END IF;\n'
 "  iid=(receipt.result->>'adoption_input_ref')::uuid;\n"
 ' END IF;\n'
 ' PERFORM kernel_category_adoption_assert(NEW.tenant_id,iid);\n'
 ' RETURN NULL;\n'
 'END $function$',
 'CREATE FUNCTION public.kernel_category_adoption_dispatch(outbox_id uuid)\n'
 'RETURNS TABLE(tenant_id uuid,run_id uuid,input_ref uuid)\n'
 'LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS '
 '$function$\n'
 'DECLARE t uuid; event outbox_events; receipt action_receipts; answer agent_run_inputs;\n'
 'BEGIN\n'
 " t=nullif(current_setting('pdos.tenant_id',true),'')::uuid;\n"
 " IF session_user<>'pdos_next_dispatch' OR t IS NULL THEN\n"
 "  RAISE EXCEPTION 'Dispatcher tenant scope required' USING ERRCODE='42501'; END IF;\n"
 ' SELECT o.* INTO event FROM outbox_events o WHERE o.tenant_id=t AND o.id=outbox_id AND '
 "o.type='category.created';\n"
 ' IF event.id IS NULL THEN RETURN; END IF;\n'
 ' SELECT a.* INTO receipt FROM action_receipts a WHERE a.tenant_id=t AND a.id=event.receipt_id;\n'
 ' SELECT a.* INTO answer FROM agent_run_inputs a WHERE a.tenant_id=t AND '
 "a.id::text=receipt.result->>'adoption_input_ref';\n"
 ' IF answer.id IS NULL OR event.category_id IS DISTINCT FROM receipt.category_id\n'
 '  OR event.subject_id IS DISTINCT FROM receipt.subject_id OR event.subject_revision IS DISTINCT '
 'FROM receipt.subject_revision\n'
 '  OR event.actor_id IS DISTINCT FROM receipt.actor_id OR event.correlation_id IS DISTINCT FROM '
 'receipt.command_id\n'
 '  OR event.schema_version IS DISTINCT FROM 1 OR kernel_category_adoption_valid(t,answer.id) IS '
 'DISTINCT FROM true\n'
 '  OR NOT EXISTS(SELECT 1 FROM agent_runs r WHERE r.tenant_id=t AND r.id=answer.run_id\n'
 "    AND r.state IN ('queued','running','waiting_input') AND r.reverted_at IS NULL)\n"
 '  OR (SELECT count(*) FROM outbox_events o WHERE o.tenant_id=t AND o.receipt_id=receipt.id AND '
 "o.type='category.created')<>1\n"
 '  THEN RETURN; END IF;\n'
 ' -- Metadata only; adopted terminal candidates remain historical facts. A\n'
 ' -- queued/running/waiting Run still returns its reference for retriable delivery.\n'
 ' RETURN QUERY SELECT t,answer.run_id,answer.id;\n'
 'END $function$',
 'REVOKE ALL ON FUNCTION public.kernel_category_adoption_valid(uuid,uuid) FROM '
 'PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.kernel_category_adoption_assert(uuid,uuid) FROM '
 'PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.kernel_input_insert_guard() FROM '
 'PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.kernel_category_adoption_guard() FROM '
 'PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.kernel_category_adoption_dispatch(uuid) FROM '
 'PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch',
 'GRANT EXECUTE ON FUNCTION public.kernel_category_adoption_dispatch(uuid) TO pdos_next_dispatch',
 'CREATE TRIGGER kernel_input_insert BEFORE INSERT ON public.agent_run_inputs FOR EACH ROW EXECUTE '
 'FUNCTION public.kernel_input_insert_guard()',
 'CREATE CONSTRAINT TRIGGER kernel_category_adoption AFTER INSERT ON public.agent_run_inputs '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION '
 'public.kernel_category_adoption_guard()',
 'CREATE CONSTRAINT TRIGGER kernel_category_adoption AFTER INSERT ON public.agent_run_events '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION '
 'public.kernel_category_adoption_guard()',
 'CREATE CONSTRAINT TRIGGER kernel_category_adoption AFTER INSERT ON public.action_receipts '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION '
 'public.kernel_category_adoption_guard()',
 'CREATE CONSTRAINT TRIGGER kernel_category_adoption AFTER INSERT ON public.outbox_events '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION '
 'public.kernel_category_adoption_guard()')

DOWNGRADE_SQL = ('DROP TRIGGER kernel_category_adoption ON public.outbox_events',
 'DROP TRIGGER kernel_category_adoption ON public.action_receipts',
 'DROP TRIGGER kernel_category_adoption ON public.agent_run_events',
 'DROP TRIGGER kernel_category_adoption ON public.agent_run_inputs',
 'DROP TRIGGER kernel_input_insert ON public.agent_run_inputs',
 'DROP FUNCTION public.kernel_category_adoption_dispatch(uuid)',
 'DROP FUNCTION public.kernel_category_adoption_guard()',
 'DROP FUNCTION public.kernel_input_insert_guard()',
 'DROP FUNCTION public.kernel_category_adoption_assert(uuid,uuid)',
 'DROP FUNCTION public.kernel_category_adoption_valid(uuid,uuid)',
 'CREATE OR REPLACE FUNCTION public.kernel_category_creation_proven(t uuid, cid uuid)\n'
 ' RETURNS boolean\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
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
 'END $function$\n')
