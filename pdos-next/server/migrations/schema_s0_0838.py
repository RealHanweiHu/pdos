"""Frozen independent query fee binding and source-model proof (P30)."""

SCHEMA_SQL = (
    (
        '-- Unnumbered; apply after actual background embedding head. Ordinary '
        'schema owner.\nALTER TABLE public.agent_tool_calls DROP CONSTRAINT kern'
        'el_execution_binding_shape;\nALTER TABLE public.agent_tool_calls ADD CO'
        'NSTRAINT kernel_execution_binding_shape\n CHECK (COALESCE(\n  jsonb_type'
        "of(execution_binding)='object'\n  AND execution_binding->>'kind' IN ('u"
        "nbound','read','model','domain_t0','embedding_query')\n  AND (execution"
        "_binding->>'kind' NOT IN ('model','domain_t0') OR (\n    execution_bind"
        "ing ?& ARRAY['model_version','model_route_digest',\n      'tool_definit"
        "ions_digest','cancel_epoch']\n    AND jsonb_typeof(execution_binding->'"
        "model_version')='string'\n    AND length(execution_binding->>'model_ver"
        "sion') BETWEEN 1 AND 160\n    AND execution_binding->>'model_route_dige"
        "st' ~ '^[a-f0-9]{64}$'\n    AND execution_binding->>'tool_definitions_d"
        "igest' ~ '^[a-f0-9]{64}$'\n    AND jsonb_typeof(execution_binding->'can"
        "cel_epoch')='number'\n    AND execution_binding->>'cancel_epoch' ~ '^[0"
        "-9]+$'\n  ))\n  AND (execution_binding->>'kind'<>'model' OR (\n    execut"
        "ion_binding ?& ARRAY['prompt_digest','loaded_skills','isolation']\n    "
        "AND execution_binding->>'prompt_digest' ~ '^[a-f0-9]{64}$'\n    AND jso"
        "nb_typeof(execution_binding->'loaded_skills')='array'\n    AND executio"
        "n_binding->>'isolation' IN\n      ('main','research','extract','mcp','a"
        "ssistant_extract','assistant_compare')\n    AND tool='model'\n  ))\n  AND"
        " (execution_binding->>'kind'<>'domain_t0' OR (\n    execution_binding ?"
        "& ARRAY['operation','skill','model_call_id',\n      'response_index','c"
        "ommand_digest']\n    AND jsonb_typeof(execution_binding->'operation')='"
        "string'\n    AND length(execution_binding->>'operation') BETWEEN 1 AND "
        "160\n    AND execution_binding->>'command_digest' ~ '^[a-f0-9]{64}$'\n  "
        "  AND jsonb_typeof(execution_binding->'response_index')='number'\n    A"
        "ND execution_binding->>'response_index' ~ '^[0-9]+$'\n    AND execution"
        "_binding->>'model_call_id'\n      ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f"
        "0-9]{12}$'\n    AND jsonb_typeof(execution_binding->'skill')='object'\n "
        "   AND (execution_binding->'skill') ?& ARRAY['key','version','digest',"
        "'load_event_id']\n    AND jsonb_typeof(execution_binding->'skill'->'key"
        "')='string'\n    AND length(execution_binding->'skill'->>'key') BETWEEN"
        " 1 AND 160\n    AND jsonb_typeof(execution_binding->'skill'->'version')"
        "='string'\n    AND length(execution_binding->'skill'->>'version') BETWE"
        "EN 1 AND 160\n    AND execution_binding->'skill'->>'digest' ~ '^[a-f0-9"
        "]{64}$'\n    AND execution_binding->'skill'->>'load_event_id'\n      ~ '"
        "^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'\n    AND tool<>'model'\n   "
        " AND (state<>'completed' OR (receipt_id IS NOT NULL AND result IS NOT "
        'NULL))\n  )), false));\n-- Unnumbered, after the first embedding/profile'
        ' migration. No new callable tool.\nCREATE FUNCTION public.kernel_embedd'
        'ing_query_guard() RETURNS trigger\nLANGUAGE plpgsql SECURITY DEFINER SE'
        'T search_path=pg_catalog,public,pg_temp AS $$\nDECLARE\n b jsonb=NEW.exe'
        'cution_binding; r public.agent_runs; p public.agent_tool_calls;\n m pub'
        'lic.agent_tool_calls; profile public.enterprise_embedding_profiles;\n e'
        'xpected jsonb; request jsonb; selected jsonb; query_value jsonb;\nBEGIN'
        "\n IF b->>'kind' IS DISTINCT FROM 'embedding_query' THEN\n  IF NEW.tool="
        "'embedding.query.internal' THEN\n   RAISE EXCEPTION 'Internal query ide"
        "ntity requires its exact independent binding';\n  END IF;\n  RETURN NEW;"
        '\n END IF;\n -- Existing cancellation/technical release remains possible'
        " after ACL removal.\n IF TG_OP='UPDATE' AND NEW.state IN ('failed','unk"
        "nown')\n    AND NEW.execution_binding IS NOT DISTINCT FROM OLD.executio"
        'n_binding THEN RETURN NEW; END IF;\n -- kernel_record_cost performs thi'
        's content-free metadata update before native\n -- technical release, in'
        "cluding after current source access has been withdrawn.\n IF TG_OP='UPD"
        "ATE' AND OLD.state='started' AND NEW.state='started'\n   AND NEW.execut"
        'ion_binding IS NOT DISTINCT FROM OLD.execution_binding\n   AND (to_json'
        "b(NEW)-ARRAY['actual_input_tokens','actual_output_tokens',\n     'cost_"
        "charged_micro_usd','cost_state']) IS NOT DISTINCT FROM\n     (to_jsonb("
        "OLD)-ARRAY['actual_input_tokens','actual_output_tokens',\n     'cost_ch"
        "arged_micro_usd','cost_state'])\n THEN RETURN NEW; END IF;\n IF NOT coal"
        "esce(b->>'parent_read_call_id' ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-"
        "9]{12}$'\n    AND b->>'profile_version_id' ~ '^[a-f0-9]{8}(-[a-f0-9]{4}"
        "){3}-[a-f0-9]{12}$',false)\n THEN RAISE EXCEPTION 'Query embedding requ"
        "ires exact parent/profile identity'; END IF;\n SELECT * INTO r FROM pub"
        'lic.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id FOR SHA'
        'RE;\n SELECT * INTO p FROM public.agent_tool_calls WHERE tenant_id=NEW.'
        "tenant_id AND run_id=NEW.run_id\n   AND id=(b->>'parent_read_call_id'):"
        ':uuid;\n IF r.id IS NULL OR p.id IS NULL OR p.id=NEW.id\n  OR r.tenant_i'
        "d IS DISTINCT FROM NULLIF(current_setting('pdos.tenant_id',true),'')::"
        'uuid\n  OR r.writer_id IS DISTINCT FROM scope_actor() OR r.requester_id'
        " IS DISTINCT FROM scope_requester()\n  OR r.state NOT IN ('queued','run"
        "ning','waiting_input') OR r.reverted_at IS NOT NULL\n  OR NOT EXISTS(SE"
        'LECT 1 FROM principals WHERE tenant_id=r.tenant_id AND id=r.writer_id\n'
        "    AND active AND kind='agent')\n  OR NOT EXISTS(SELECT 1 FROM princip"
        'als WHERE tenant_id=r.tenant_id AND id=r.requester_id\n    AND active A'
        "ND kind='human')\n  OR (r.category_id IS NOT NULL AND category_access(r"
        ".tenant_id,r.category_id) IS DISTINCT FROM true)\n  OR p.tool<>'assista"
        "nt.search' OR p.state NOT IN ('started','completed')\n  OR p.execution_"
        "binding->>'kind'<>'read' OR p.execution_binding->>'read_kind'<>'ordina"
        "ry/v1'\n  OR p.execution_binding->>'isolation'<>'main' OR p.receipt_id "
        "IS NOT NULL OR p.error_code IS NOT NULL\n  OR p.execution_binding->'can"
        "cel_epoch' IS DISTINCT FROM to_jsonb(r.cancel_epoch)\n  OR NEW.tool<>'e"
        "mbedding.query.internal' OR NEW.receipt_id IS NOT NULL\n THEN RAISE EXC"
        "EPTION 'Query embedding requires current actual main search READ'; END"
        ' IF;\n SELECT * INTO m FROM public.agent_tool_calls WHERE tenant_id=r.t'
        "enant_id AND run_id=r.id\n   AND id=(p.execution_binding->>'model_call_"
        "id')::uuid;\n IF m.id IS NULL OR m.tool<>'model' OR m.state<>'completed"
        "' OR m.error_code IS NOT NULL\n  OR m.receipt_id IS NOT NULL OR m.execu"
        "tion_binding->>'kind'<>'model'\n  OR m.execution_binding->>'isolation'<"
        ">'main'\n  OR m.execution_binding->'cancel_epoch' IS DISTINCT FROM to_j"
        "sonb(r.cancel_epoch)\n  OR m.execution_binding->'model_version' IS DIST"
        "INCT FROM r.versions->'model_version'\n  OR m.execution_binding->'model"
        "_route_digest' IS DISTINCT FROM r.versions->'model_route_digest'\n  OR "
        "m.execution_binding->'tool_definitions_digest' IS DISTINCT FROM\n     r"
        ".versions->'tool_definitions'->'main'\n  OR m.execution_binding->'promp"
        "t_digest' IS DISTINCT FROM r.versions->'prompt_prefixes'->'main'\n THEN"
        " RAISE EXCEPTION 'Query embedding requires the completed source model'"
        "; END IF;\n request=m.result->'calls'->((p.execution_binding->>'respons"
        "e_index')::integer);\n query_value=request->'arguments'->'query';\n IF r"
        "equest->>'name' IS DISTINCT FROM 'assistant.search'\n  OR jsonb_typeof("
        "query_value) IS DISTINCT FROM 'string'\n  OR length(query_value#>>'{}')"
        ' NOT BETWEEN 1 AND 20000\n  OR p.input_digest IS DISTINCT FROM encode(s'
        "ha256(convert_to(\n    kernel_read_canonical_json(jsonb_build_array('as"
        "sistant.search',request->'arguments')),'UTF8')),'hex')\n THEN RAISE EXC"
        "EPTION 'Query text requires the exact actual model search input'; END "
        "IF;\n selected=r.versions->'embedding_query_profile';\n SELECT * INTO pr"
        'ofile FROM public.enterprise_embedding_profiles\n   WHERE tenant_id=r.t'
        "enant_id AND id=(b->>'profile_version_id')::uuid;\n IF profile.id IS NU"
        'LL OR NOT profile.enabled OR NOT EXISTS(\n    SELECT 1 FROM public.ente'
        'rprise_embedding_profile_heads h WHERE h.tenant_id=profile.tenant_id\n '
        '     AND h.profile_id=profile.profile_id AND h.revision=profile.revisi'
        "on AND h.enabled)\n  OR selected->>'profile_version_id' IS DISTINCT FRO"
        "M profile.id::text\n  OR selected->>'binding_digest' IS DISTINCT FROM p"
        "rofile.binding_digest\n  OR selected->'dimensions' IS DISTINCT FROM pro"
        "file.metadata_json->'dimensions'\n  OR NOT coalesce(selected->>'scan_st"
        "rategy' IN ('exact','iterative'),false)\n  OR selected IS DISTINCT FROM"
        " jsonb_build_object('profile_version_id',profile.id,\n    'binding_dige"
        "st',profile.binding_digest,'dimensions',profile.metadata_json->'dimens"
        "ions',\n    'scan_strategy',selected->'scan_strategy')\n  OR r.versions-"
        ">>'embedding_query_profile_digest' IS DISTINCT FROM encode(sha256(conv"
        "ert_to(\n    kernel_read_canonical_json(selected),'UTF8')),'hex')\n THEN"
        " RAISE EXCEPTION 'Query embedding requires the exact frozen active ind"
        "ependent profile'; END IF;\n expected=jsonb_build_object('kind','embedd"
        "ing_query','proof_version',1,\n   'parent_read_call_id',p.id,'parent_in"
        "put_digest',p.input_digest,\n   'profile_version_id',profile.id,'profil"
        "e_digest',profile.binding_digest,\n   'query_digest',encode(sha256(conv"
        "ert_to(query_value#>>'{}','UTF8')),'hex'),\n   'cancel_epoch',r.cancel_"
        'epoch);\n IF b IS DISTINCT FROM expected\n  OR NEW.call_key IS DISTINCT '
        "FROM 'embedding-query:'||r.id::text||':'||p.id::text\n  OR NEW.input_di"
        'gest IS DISTINCT FROM encode(sha256(convert_to(kernel_read_canonical_j'
        "son(\n    jsonb_build_array('embedding.query.internal',jsonb_build_obje"
        "ct(\n      'parent_read_call_id',p.id,'profile_version_id',profile.id,'"
        "query',query_value))),'UTF8')),'hex')\n  OR NEW.output_token_reservatio"
        "n<>0 OR NEW.cost_pricing='{}'::jsonb\n  -- Enabled profile metadata alr"
        'eady rejects userinfo/query/fragment and fixes\n  -- http(s) endpoint s'
        'yntax. Retain its actual host, including local IPv6.\n  OR NEW.cost_pri'
        "cing->>'provider' IS DISTINCT FROM lower(btrim(regexp_replace(\n    spl"
        "it_part(regexp_replace(profile.metadata_json->>'base_url','^https?://'"
        ",'','i'),\n      '/',1), ':[0-9]+$',''), '[]'))\n  OR NEW.cost_pricing->"
        ">'model' IS DISTINCT FROM profile.metadata_json->>'model'\n  OR NEW.cos"
        "t_pricing->>'configuration_version' IS DISTINCT FROM profile.metadata_"
        "json->>'model_version'\n THEN RAISE EXCEPTION 'Independent query execut"
        "ion/budget binding mismatch'; END IF;\n IF NEW.state='completed' AND (N"
        "EW.error_code IS NOT NULL\n    OR NEW.cost_state<>'actual' OR jsonb_typ"
        "eof(NEW.result) IS DISTINCT FROM 'object'\n    OR jsonb_typeof(NEW.resu"
        "lt->'vector') IS DISTINCT FROM 'array'\n    OR jsonb_array_length(NEW.r"
        "esult->'vector')<>(profile.metadata_json->>'dimensions')::integer\n    "
        "OR NEW.result->>'query_digest' IS DISTINCT FROM b->>'query_digest')\n T"
        "HEN RAISE EXCEPTION 'Completed query embedding requires a bound verifi"
        "ed private vector'; END IF;\n IF NEW.state='completed' THEN\n  IF (NEW.r"
        "esult - ARRAY['vector','query_digest'])<>'{}'::jsonb\n    OR EXISTS(SEL"
        "ECT 1 FROM jsonb_array_elements(NEW.result->'vector') value\n          "
        "    WHERE jsonb_typeof(value) IS DISTINCT FROM 'number')\n    OR abs(ve"
        "ctor_norm((NEW.result->>'vector')::vector)-1)>0.00001\n  THEN RAISE EXC"
        "EPTION 'Private query vector requires exact finite normalized values';"
        ' END IF;\n END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER kernel_embedding'
        '_query_guard BEFORE INSERT OR UPDATE ON public.agent_tool_calls\n FOR E'
        'ACH ROW EXECUTE FUNCTION public.kernel_embedding_query_guard();\nREVOKE'
        ' ALL ON FUNCTION public.kernel_embedding_query_guard()\n FROM PUBLIC,pd'
        'os_agent,pdos_next_auth,pdos_next_dispatch;\n'
    ),
)

DOWNGRADE_SQL = (
    (
        '-- After privileged nonempty-history preflight succeeds; ordinary sche'
        'ma owner.\nDROP TRIGGER kernel_embedding_query_guard ON public.agent_to'
        'ol_calls;\nDROP FUNCTION public.kernel_embedding_query_guard();\nALTER T'
        'ABLE public.agent_tool_calls DROP CONSTRAINT kernel_execution_binding_'
        'shape;\nALTER TABLE public.agent_tool_calls ADD CONSTRAINT kernel_execu'
        'tion_binding_shape\n CHECK (COALESCE(\n  jsonb_typeof(execution_binding)'
        "='object'\n  AND execution_binding->>'kind' IN ('unbound','read','model"
        "','domain_t0')\n  AND (execution_binding->>'kind' NOT IN ('model','doma"
        "in_t0') OR (\n    execution_binding ?& ARRAY['model_version','model_rou"
        "te_digest',\n      'tool_definitions_digest','cancel_epoch']\n    AND js"
        "onb_typeof(execution_binding->'model_version')='string'\n    AND length"
        "(execution_binding->>'model_version') BETWEEN 1 AND 160\n    AND execut"
        "ion_binding->>'model_route_digest' ~ '^[a-f0-9]{64}$'\n    AND executio"
        "n_binding->>'tool_definitions_digest' ~ '^[a-f0-9]{64}$'\n    AND jsonb"
        "_typeof(execution_binding->'cancel_epoch')='number'\n    AND execution_"
        "binding->>'cancel_epoch' ~ '^[0-9]+$'\n  ))\n  AND (execution_binding->>"
        "'kind'<>'model' OR (\n    execution_binding ?& ARRAY['prompt_digest','l"
        "oaded_skills','isolation']\n    AND execution_binding->>'prompt_digest'"
        " ~ '^[a-f0-9]{64}$'\n    AND jsonb_typeof(execution_binding->'loaded_sk"
        "ills')='array'\n    AND execution_binding->>'isolation' IN\n      ('main"
        "','research','extract','mcp','assistant_extract','assistant_compare')\n"
        "    AND tool='model'\n  ))\n  AND (execution_binding->>'kind'<>'domain_t"
        "0' OR (\n    execution_binding ?& ARRAY['operation','skill','model_call"
        "_id',\n      'response_index','command_digest']\n    AND jsonb_typeof(ex"
        "ecution_binding->'operation')='string'\n    AND length(execution_bindin"
        "g->>'operation') BETWEEN 1 AND 160\n    AND execution_binding->>'comman"
        "d_digest' ~ '^[a-f0-9]{64}$'\n    AND jsonb_typeof(execution_binding->'"
        "response_index')='number'\n    AND execution_binding->>'response_index'"
        " ~ '^[0-9]+$'\n    AND execution_binding->>'model_call_id'\n      ~ '^[a"
        "-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'\n    AND jsonb_typeof(executi"
        "on_binding->'skill')='object'\n    AND (execution_binding->'skill') ?& "
        "ARRAY['key','version','digest','load_event_id']\n    AND jsonb_typeof(e"
        "xecution_binding->'skill'->'key')='string'\n    AND length(execution_bi"
        "nding->'skill'->>'key') BETWEEN 1 AND 160\n    AND jsonb_typeof(executi"
        "on_binding->'skill'->'version')='string'\n    AND length(execution_bind"
        "ing->'skill'->>'version') BETWEEN 1 AND 160\n    AND execution_binding-"
        ">'skill'->>'digest' ~ '^[a-f0-9]{64}$'\n    AND execution_binding->'ski"
        "ll'->>'load_event_id'\n      ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{"
        "12}$'\n    AND tool<>'model'\n    AND (state<>'completed' OR (receipt_id"
        ' IS NOT NULL AND result IS NOT NULL))\n  )), false));\n'
    ),
)

EMPTY_HISTORY_SQL = (
    (
        '-- MUST run as the existing privileged migration identity BEFORE SET R'
        'OLE ordinary owner.\n-- FORCE RLS could hide other-tenant call rows fro'
        'm an ordinary owner preflight.\nDO $$ BEGIN\n IF EXISTS(SELECT 1 FROM pu'
        "blic.agent_tool_calls WHERE tool='embedding.query.internal'\n    OR exe"
        "cution_binding->>'kind'='embedding_query') THEN\n  RAISE EXCEPTION 'Que"
        "ry embedding history must not be discarded by downgrade';\n END IF;\nEND"
        ' $$;\n'
    ),
)

