"""Frozen unnumbered I14/I22 answer dependency footprint; predecessor s0_0841."""

SCHEMA_SQL = (
    (
        'CREATE OR REPLACE FUNCTION public.knowledge_answer_sources_known('
        'origin_id uuid, proof jsonb)\n RETURNS boolean\n LANGUAGE plpgsql\n '
        "SECURITY DEFINER\n SET search_path TO 'pg_catalog', 'public', 'pg_"
        "temp'\nAS $function$\n\nDECLARE valid boolean;\nBEGIN\n WITH RECURSIVE"
        '\n -- Only the actual linked conversation is eligible. Merely shar'
        'ing an owner or\n -- session is insufficient, and unrelated Runs a'
        're never scanned for UUIDs.\n origin AS MATERIALIZED (\n  SELECT r.'
        '* FROM public.agent_runs r WHERE r.id=origin_id\n   AND r.tenant_i'
        "d=nullif(current_setting('pdos.tenant_id',true),'')::uuid\n ), lin"
        'eage(id,path) AS (\n  SELECT id,ARRAY[id] FROM origin\n  UNION ALL\n'
        '  SELECT p.id,l.path||p.id FROM lineage l JOIN public.agent_runs '
        'child ON child.id=l.id\n   JOIN public.agent_runs p ON p.id=child.'
        'continued_from_id\n   JOIN origin o ON p.tenant_id=o.tenant_id AND'
        ' p.session_id=o.session_id\n    AND p.requester_id=o.requester_id\n'
        '   WHERE NOT p.id=ANY(l.path)\n ), retained_runs AS MATERIALIZED ('
        '\n  SELECT r.* FROM public.agent_runs r JOIN lineage l ON l.id=r.i'
        'd\n   WHERE r.reverted_at IS NULL\n ), sealed_reads AS MATERIALIZED'
        ' (\n  -- kernel_read_guard sealed these exact bindings at claim/se'
        'ttle; terminal\n  -- guards prohibit changing their results. Reche'
        'ck the retained identity and\n  -- completed model position, rathe'
        'r than trusting a read_kind tag or prose.\n  SELECT c.*,r.session_'
        'id,r.requester_id FROM retained_runs r\n   JOIN public.agent_tool_'
        'calls c ON c.tenant_id=r.tenant_id AND c.run_id=r.id\n   JOIN publ'
        'ic.agent_tool_calls m ON m.tenant_id=r.tenant_id AND m.run_id=r.i'
        "d\n    AND m.id::text=c.execution_binding->>'model_call_id'\n   WHE"
        "RE c.state='completed' AND c.error_code IS NULL AND c.receipt_id "
        "IS NULL\n    AND c.tool IN ('assistant.search','assistant.material"
        "s.read',\n      'assistant.citations.read','conversation.history')"
        "\n    AND m.tool='model' AND m.state='completed' AND m.error_code "
        "IS NULL\n    AND m.receipt_id IS NULL AND m.execution_binding->>'k"
        "ind'='model'\n    AND m.execution_binding->>'isolation'='main'\n   "
        " AND c.execution_binding=jsonb_build_object(\n      'kind','read',"
        "'read_kind','ordinary/v1','proof_version',1,'graph','xiaopai','st"
        "ep','tools',\n      'isolation','main','tenant_id',r.tenant_id,'ca"
        "tegory_id',r.category_id,\n      'run_id',r.id,'session_id',r.sess"
        "ion_id,'requester_id',r.requester_id,'writer_id',r.writer_id,\n   "
        "   'product_id',r.product_id,'proposal_id',r.proposal_id,\n      '"
        "cancel_epoch',r.cancel_epoch-CASE WHEN r.state='cancelled' THEN 1"
        " ELSE 0 END,\n      'private_context',r.private_context,\n      'da"
        "ta_categories',(SELECT coalesce(jsonb_agg(value ORDER BY value CO"
        'LLATE "C"),\'[]\'::jsonb)\n        FROM jsonb_array_elements_text(r.'
        "data_categories)),\n      'customer_identities',r.customer_identit"
        "ies,'tool',c.tool,'call_key',c.call_key,\n      'model_call_id',m."
        "id,'response_index',c.execution_binding->'response_index',\n      "
        "'model_version',m.execution_binding->'model_version',\n      'mode"
        "l_route_digest',m.execution_binding->'model_route_digest',\n      "
        "'tool_definitions_digest',m.execution_binding->'tool_definitions_"
        "digest',\n      'prompt_digest',m.execution_binding->'prompt_diges"
        "t')\n    AND c.execution_binding->'cancel_epoch'=m.execution_bindi"
        "ng->'cancel_epoch'\n    AND m.execution_binding->'model_version'=r"
        ".versions->'model_version'\n    AND m.execution_binding->'model_ro"
        "ute_digest'=r.versions->'model_route_digest'\n    AND m.execution_"
        "binding->'prompt_digest'=r.versions->'prompt_prefixes'->'main'\n  "
        "  AND (m.execution_binding->'tool_definitions_digest'=r.versions-"
        ">'tool_definitions'->'main'\n      OR coalesce(r.versions#>'{tool_"
        "disclosures,main,chain}','[]'::jsonb)\n       @>jsonb_build_array("
        "m.execution_binding->'tool_definitions_digest'))\n    AND c.call_k"
        "ey='agent:'||r.id::text||':model:'||m.id::text||':'\n      ||(c.ex"
        "ecution_binding->>'response_index')\n    AND m.result->'calls'->(c"
        ".execution_binding->>'response_index')::integer->>'name'=c.tool\n "
        '   AND c.input_digest=encode(sha256(convert_to(public.kernel_read'
        "_canonical_json(\n      jsonb_build_array(c.tool,m.result->'calls'"
        "->(c.execution_binding->>'response_index')::integer\n       ->'arg"
        "uments')),'UTF8')),'hex')\n ), disclosed_pages(value) AS (\n  SELEC"
        "T o.versions->'conversation_memory' FROM origin o\n  UNION ALL\n  S"
        'ELECT c.result FROM sealed_reads c JOIN origin o ON c.run_id=o.id'
        "\n   WHERE c.tool='conversation.history'\n ), carried_runs(id) AS ("
        '\n  SELECT id FROM origin\n  UNION\n  SELECT r.id FROM disclosed_pag'
        'es page\n   CROSS JOIN LATERAL jsonb_array_elements(coalesce(page.'
        "value->'turns','[]'::jsonb)) turn\n   JOIN retained_runs r ON r.id"
        "::text=turn->>'run_id'\n   WHERE turn->'historical_outcome' IS NOT"
        " NULL AND turn->'historical_outcome'<>'null'::jsonb\n    AND NOT E"
        "XISTS(SELECT 1 FROM origin o WHERE coalesce(\n      o.versions#>'{"
        "work_state,context_selection}',o.versions->'requested_context_sel"
        "ection',\n      'null'::jsonb)<>'null'::jsonb)\n  UNION\n  SELECT r."
        'id FROM origin o JOIN public.agent_work_states state\n   ON state.'
        'tenant_id=o.tenant_id AND state.session_id=o.session_id\n    AND s'
        "tate.revision::text=o.versions#>>'{work_state,revision}'\n   JOIN "
        "retained_runs r ON r.id::text=state.body#>>'{current_goal,run_id}"
        "'\n   WHERE (coalesce(jsonb_array_length(o.versions#>'{work_state,"
        "unfinished}'),0)>0\n    OR coalesce(jsonb_array_length(o.versions#"
        ">'{work_state,questions}'),0)>0)\n    AND coalesce(o.versions#>'{w"
        "ork_state,context_selection}',\n      o.versions->'requested_conte"
        "xt_selection','null'::jsonb)='null'::jsonb\n ), root_items AS MATE"
        'RIALIZED (\n  SELECT c.run_id,item FROM sealed_reads c\n   CROSS JO'
        "IN LATERAL jsonb_array_elements(coalesce(c.result->'items','[]'::"
        "jsonb)) item\n   WHERE c.tool IN ('assistant.search','assistant.ma"
        "terials.read')\n ), inherited_refs(run_id,ref) AS (\n  SELECT r.id,"
        'ref FROM retained_runs r JOIN carried_runs carried ON carried.id='
        'r.id\n   CROSS JOIN LATERAL jsonb_array_elements(coalesce(r.versio'
        "ns#>'{work_state,citations}','[]'::jsonb)) ref\n  UNION ALL\n  SELE"
        'CT c.run_id,ref FROM sealed_reads c JOIN carried_runs carried ON '
        'carried.id=c.run_id\n   CROSS JOIN LATERAL jsonb_array_elements(co'
        "alesce(c.result->'items','[]'::jsonb)) ref\n   WHERE c.tool='assis"
        "tant.citations.read'\n ), disclosed_sources(value) AS (\n  SELECT i"
        'tem FROM root_items root JOIN carried_runs carried ON carried.id='
        'root.run_id\n  UNION ALL\n  -- A preview/reissued CID supplies no c'
        'ontent identity itself: match it to the\n  -- original completed r'
        'oot read in this same linked conversation.\n  SELECT root.item FRO'
        'M inherited_refs inherited JOIN root_items root\n   ON root.run_id'
        "::text=inherited.ref->>'origin_run_id'\n    AND root.item->>'citat"
        "ion_id'=inherited.ref->>'origin_citation_id'\n ),\n initial(value) "
        'AS (\n  SELECT value FROM disclosed_sources\n  UNION ALL\n  SELECT v'
        'alue FROM public.agent_runs r,\n   LATERAL jsonb_array_elements(co'
        "alesce(r.result#>'{result,assistant,sources}','[]'::jsonb)) entry"
        '(value)\n   WHERE r.id=origin_id AND r.tenant_id=nullif(current_se'
        "tting('pdos.tenant_id',true),'')::uuid\n  UNION ALL\n  SELECT jsonb"
        "_build_object('source_type','artifact','source_id',a.id,'source_r"
        "evision',a.revision,\n   'content_hash',a.content_hash,'category_i"
        "d',a.category_id)\n   FROM public.agent_runs r CROSS JOIN LATERAL "
        'jsonb_array_elements(r.read_sources) ref(value)\n   JOIN public.ar'
        'tifact_versions a ON a.tenant_id=r.tenant_id AND (r.category_id I'
        'S NULL OR a.category_id=r.category_id)\n    AND a.id::text=ref.val'
        "ue->>'artifact_id' AND a.revision::text=ref.value->>'expected_rev"
        "ision'\n   WHERE r.id=origin_id AND r.tenant_id=nullif(current_set"
        "ting('pdos.tenant_id',true),'')::uuid\n ), closure(value,seen) AS "
        "(\n  SELECT value,ARRAY[value->>'source_id'] FROM initial\n  UNION "
        "ALL\n  SELECT child.value,parent.seen||(child.value->>'source_id')"
        ' FROM closure parent\n   JOIN public.knowledge_answer_reviews prio'
        "r ON prior.subject_id::text=parent.value->>'source_id'\n     AND p"
        "rior.tenant_id=nullif(current_setting('pdos.tenant_id',true),''):"
        ":uuid\n     AND parent.value->>'source_type'='knowledge'\n   CROSS "
        'JOIN LATERAL jsonb_array_elements(prior.source_proof) child(value'
        ")\n   WHERE NOT (child.value->>'source_id'=ANY(parent.seen))\n ) SE"
        'LECT NOT EXISTS(SELECT 1 FROM jsonb_array_elements(proof) p WHERE'
        " NOT EXISTS(\n  SELECT 1 FROM closure c WHERE c.value->>'source_ty"
        "pe'=p->>'source_type'\n   AND c.value->>'source_id'=p->>'source_id"
        "'\n   AND c.value->>'source_revision'=p->>'source_revision'\n   AND"
        " c.value->>'content_hash'=p->>'content_hash'\n   AND c.value->>'ca"
        "tegory_id'=p->>'category_id')) INTO valid;\n RETURN jsonb_typeof(p"
        "roof)='array' AND coalesce(valid,false);\nEXCEPTION WHEN data_exce"
        'ption THEN RETURN false;\nEND\n\n$function$\n'
    ),
)

DOWNGRADE_SQL = (
    (
        'CREATE OR REPLACE FUNCTION public.knowledge_answer_sources_known('
        'origin_id uuid, proof jsonb)\n RETURNS boolean\n LANGUAGE plpgsql\n '
        "SECURITY DEFINER\n SET search_path TO 'pg_catalog', 'public', 'pg_"
        "temp'\nAS $function$\n\nDECLARE valid boolean;\nBEGIN\n WITH RECURSIVE"
        ' initial(value) AS (\n  SELECT value FROM public.agent_runs r,\n   '
        "LATERAL jsonb_array_elements(coalesce(r.result#>'{result,assistan"
        "t,sources}','[]'::jsonb)) entry(value)\n   WHERE r.id=origin_id AN"
        "D r.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::"
        "uuid\n  UNION ALL\n  SELECT jsonb_build_object('source_type','artif"
        "act','source_id',a.id,'source_revision',a.revision,\n   'content_h"
        "ash',a.content_hash,'category_id',a.category_id)\n   FROM public.a"
        'gent_runs r CROSS JOIN LATERAL jsonb_array_elements(r.read_source'
        's) ref(value)\n   JOIN public.artifact_versions a ON a.tenant_id=r'
        '.tenant_id AND (r.category_id IS NULL OR a.category_id=r.category'
        "_id)\n    AND a.id::text=ref.value->>'artifact_id' AND a.revision:"
        ":text=ref.value->>'expected_revision'\n   WHERE r.id=origin_id AND"
        " r.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::u"
        "uid\n ), closure(value,seen) AS (\n  SELECT value,ARRAY[value->>'so"
        "urce_id'] FROM initial\n  UNION ALL\n  SELECT child.value,parent.se"
        "en||(child.value->>'source_id') FROM closure parent\n   JOIN publi"
        'c.knowledge_answer_reviews prior ON prior.subject_id::text=parent'
        ".value->>'source_id'\n     AND prior.tenant_id=nullif(current_sett"
        "ing('pdos.tenant_id',true),'')::uuid\n     AND parent.value->>'sou"
        "rce_type'='knowledge'\n   CROSS JOIN LATERAL jsonb_array_elements("
        "prior.source_proof) child(value)\n   WHERE NOT (child.value->>'sou"
        "rce_id'=ANY(parent.seen))\n ) SELECT NOT EXISTS(SELECT 1 FROM json"
        'b_array_elements(proof) p WHERE NOT EXISTS(\n  SELECT 1 FROM closu'
        "re c WHERE c.value->>'source_type'=p->>'source_type'\n   AND c.val"
        "ue->>'source_id'=p->>'source_id'\n   AND c.value->>'source_revisio"
        "n'=p->>'source_revision'\n   AND c.value->>'content_hash'=p->>'con"
        "tent_hash'\n   AND c.value->>'category_id'=p->>'category_id')) INT"
        "O valid;\n RETURN jsonb_typeof(proof)='array' AND coalesce(valid,f"
        'alse);\nEND\n\n$function$\n'
    ),
)

EMPTY_HISTORY_SQL = (
    (
        'LOCK TABLE public.agent_runs,public.agent_tool_calls,public.knowl'
        'edge_answer_reviews,public.knowledge_gap_submissions IN SHARE ROW'
        ' EXCLUSIVE MODE'
    ),
    (
        'DO $footprint_history$\n\nDECLARE valid boolean; saved record;\nBEGI'
        'N\n FOR saved IN\n  SELECT tenant_id,origin_run_id AS origin_id,sou'
        'rce_proof AS proof FROM public.knowledge_answer_reviews\n   WHERE '
        'origin_run_id IS NOT NULL\n  UNION ALL\n  SELECT tenant_id,run_id,s'
        "ource_proof FROM public.knowledge_gap_submissions WHERE kind='sha"
        "red_feedback'\n LOOP\n WITH RECURSIVE initial(value) AS (\n  SELECT "
        'value FROM public.agent_runs r,\n   LATERAL jsonb_array_elements(c'
        "oalesce(r.result#>'{result,assistant,sources}','[]'::jsonb)) entr"
        'y(value)\n   WHERE r.id=saved.origin_id AND r.tenant_id=saved.tena'
        "nt_id\n  UNION ALL\n  SELECT jsonb_build_object('source_type','arti"
        "fact','source_id',a.id,'source_revision',a.revision,\n   'content_"
        "hash',a.content_hash,'category_id',a.category_id)\n   FROM public."
        'agent_runs r CROSS JOIN LATERAL jsonb_array_elements(r.read_sourc'
        'es) ref(value)\n   JOIN public.artifact_versions a ON a.tenant_id='
        'r.tenant_id AND (r.category_id IS NULL OR a.category_id=r.categor'
        "y_id)\n    AND a.id::text=ref.value->>'artifact_id' AND a.revision"
        "::text=ref.value->>'expected_revision'\n   WHERE r.id=saved.origin"
        '_id AND r.tenant_id=saved.tenant_id\n ), closure(value,seen) AS (\n'
        "  SELECT value,ARRAY[value->>'source_id'] FROM initial\n  UNION AL"
        "L\n  SELECT child.value,parent.seen||(child.value->>'source_id') F"
        'ROM closure parent\n   JOIN public.knowledge_answer_reviews prior '
        "ON prior.subject_id::text=parent.value->>'source_id'\n     AND pri"
        "or.tenant_id=saved.tenant_id\n     AND parent.value->>'source_type"
        "'='knowledge'\n   CROSS JOIN LATERAL jsonb_array_elements(prior.so"
        "urce_proof) child(value)\n   WHERE NOT (child.value->>'source_id'="
        'ANY(parent.seen))\n ) SELECT NOT EXISTS(SELECT 1 FROM jsonb_array_'
        'elements(saved.proof) p WHERE NOT EXISTS(\n  SELECT 1 FROM closure'
        " c WHERE c.value->>'source_type'=p->>'source_type'\n   AND c.value"
        "->>'source_id'=p->>'source_id'\n   AND c.value->>'source_revision'"
        "=p->>'source_revision'\n   AND c.value->>'content_hash'=p->>'conte"
        "nt_hash'\n   AND c.value->>'category_id'=p->>'category_id')) INTO "
        "valid;\n IF NOT (jsonb_typeof(saved.proof)='array' AND coalesce(va"
        "lid,false)) THEN\n  RAISE EXCEPTION 'Full answer-read footprint hi"
        "story cannot be downgraded to citation-only provenance'\n   USING "
        "ERRCODE='23514';\n END IF;\n END LOOP;\nEND\n\n$footprint_history$"
    ),
)

PREVIOUS_FUNCTIONS = {'knowledge_answer_sources_known(uuid,jsonb)': DOWNGRADE_SQL[0]}
NATIVE_FUNCTIONS = {'knowledge_answer_sources_known(uuid,jsonb)': SCHEMA_SQL[0]}
