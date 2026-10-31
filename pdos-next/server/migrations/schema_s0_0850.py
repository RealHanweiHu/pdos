"""Native project footprint retains originals independently from explicit material bindings."""

PREVIOUS_FUNCTIONS = {
    'kernel_lifecycle_links(text,jsonb)': (
        'CREATE OR REPLACE FUNCTION public.kernel_lifecycle_links(table_name text, pa'
        'yload jsonb)\n RETURNS uuid[]\n LANGUAGE plpgsql\n IMMUTABLE\n SET search_pa'
        "th TO 'pg_catalog', 'public'\nAS $function$\nDECLARE refs uuid[];\nBEGIN\n I"
        "F table_name<>'agent_runs' THEN RETURN public.lifecycle_payload_links(payloa"
        "d); END IF;\n SELECT COALESCE(array_agg((r->>'artifact_id')::uuid),'{}') INT"
        "O refs\n FROM jsonb_array_elements(payload->'read_sources') r;\n RETURN refs"
        ';\nEND $function$\n'
    ),
    'kernel_source_reference_gate()': (
        'CREATE OR REPLACE FUNCTION public.kernel_source_reference_gate()\n RETURNS t'
        "rigger\n LANGUAGE plpgsql\n SECURITY DEFINER\n SET search_path TO 'pg_catalo"
        "g', 'public', 'pg_temp'\nAS $function$\nDECLARE r agent_runs; prior agent_ru"
        "ns; ref jsonb; a artifact_versions; links uuid[]='{}';\nBEGIN\n IF TG_OP='DE"
        "LETE' THEN r=OLD; ELSE r=NEW; END IF;\n IF TG_OP='UPDATE' THEN\n  prior=OLD;"
        '\n  IF ROW(r.tenant_id,r.category_id,r.product_id,r.read_sources) IS DISTINC'
        'T FROM\n     ROW(prior.tenant_id,prior.category_id,prior.product_id,prior.re'
        "ad_sources)\n  THEN RAISE EXCEPTION 'Run source scope immutable' USING ERRCO"
        "DE='23514'; END IF;\n  RETURN NEW;\n END IF;\n IF jsonb_typeof(r.read_source"
        "s) IS DISTINCT FROM 'array'\n THEN RAISE EXCEPTION 'Run source set must be a"
        "n array' USING ERRCODE='23514'; END IF;\n IF r.category_id IS NULL THEN\n  I"
        "F jsonb_array_length(r.read_sources)<>0\n  THEN RAISE EXCEPTION 'Personal Ru"
        "n cannot consume business sources' USING ERRCODE='23514'; END IF;\n  IF TG_O"
        "P='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n END IF;\n PERFORM 1 F"
        'ROM public.categories WHERE id=r.category_id AND tenant_id=r.tenant_id FOR U'
        "PDATE;\n IF NOT FOUND THEN RAISE EXCEPTION 'Run source category unavailable'"
        " USING ERRCODE='23514'; END IF;\n IF r.product_id IS NOT NULL THEN\n  PERFOR"
        'M 1 FROM public.products WHERE id=r.product_id AND tenant_id=r.tenant_id\n  '
        ' AND category_id=r.category_id FOR UPDATE;\n  IF NOT FOUND THEN RAISE EXCEPT'
        "ION 'Run source model unavailable' USING ERRCODE='23514'; END IF;\n END IF;"
        "\n IF TG_OP='DELETE' THEN RETURN OLD; END IF;\n IF NOT public.kernel_read_se"
        "t_visible(r.tenant_id,r.category_id,r.read_sources)\n THEN RAISE EXCEPTION '"
        "Run sources currently unreadable' USING ERRCODE='23514'; END IF;\n FOR ref I"
        'N SELECT value FROM jsonb_array_elements(r.read_sources) LOOP\n  SELECT * IN'
        'TO a FROM public.artifact_versions WHERE tenant_id=r.tenant_id\n   AND categ'
        "ory_id=r.category_id AND id=(ref->>'artifact_id')::uuid\n   AND revision=(re"
        "f->>'expected_revision')::integer AND status='active'\n   AND (r.product_id "
        'IS NULL OR product_id IS NULL OR product_id=r.product_id)\n   AND product_id'
        " IS NOT DISTINCT FROM (ref->>'product_id')::uuid;\n  IF NOT FOUND THEN RAISE"
        " EXCEPTION 'Run requires exact actual source' USING ERRCODE='23514'; END IF;"
        '\n  links=array_append(links,a.id);\n  IF a.original_id IS NOT NULL THEN lin'
        'ks=array_append(links,a.original_id); END IF;\n END LOOP;\n IF EXISTS(SELECT'
        ' 1 FROM public.lifecycle_objects o\n  WHERE o.tenant_id=r.tenant_id AND o.ca'
        "tegory_id=r.category_id AND o.id=ANY(links)\n   AND (o.state->'value'->>'pen"
        "ding_intent_id' IS NOT NULL\n    OR o.state->'value'->>'disposition' IN ('qu"
        "arantined','unknown','purged')))\n THEN RAISE EXCEPTION 'Pending original pr"
        "ohibits Run source binding'\n  USING ERRCODE='23514',CONSTRAINT='category_so"
        "urce_reference_fence'; END IF;\n RETURN NEW;\nEND $function$\n"
    ),
    'kernel_source_reference_clock()': (
        'CREATE OR REPLACE FUNCTION public.kernel_source_reference_clock()\n RETURNS '
        "trigger\n LANGUAGE plpgsql\n SECURITY DEFINER\n SET search_path TO 'pg_catal"
        "og', 'public', 'pg_temp'\nAS $function$\nDECLARE r agent_runs;\nBEGIN\n IF T"
        "G_OP='DELETE' THEN r=OLD; ELSE r=NEW; END IF;\n IF r.category_id IS NOT NULL"
        ' AND jsonb_array_length(r.read_sources)>0 THEN\n  UPDATE public.categories S'
        'ET lifecycle_epoch=lifecycle_epoch+1\n   WHERE tenant_id=r.tenant_id AND id='
        'r.category_id;\n  IF r.product_id IS NOT NULL THEN\n   UPDATE public.product'
        's SET lifecycle_epoch=lifecycle_epoch+1\n    WHERE tenant_id=r.tenant_id AND'
        " id=r.product_id;\n  END IF;\n END IF;\n IF TG_OP='DELETE' THEN RETURN OLD; "
        'ELSE RETURN NEW; END IF;\nEND $function$\n'
    ),
}

NATIVE_FUNCTIONS = {
    'kernel_lifecycle_links(text,jsonb)': (
        'CREATE OR REPLACE FUNCTION public.kernel_lifecycle_links(table_name text, pa'
        'yload jsonb)\n RETURNS uuid[]\n LANGUAGE plpgsql\n IMMUTABLE\n SET search_pa'
        "th TO 'pg_catalog', 'public'\nAS $function$\nDECLARE refs uuid[];\nBEGIN\n I"
        "F table_name<>'agent_runs' THEN RETURN public.lifecycle_payload_links(payloa"
        "d); END IF;\n SELECT COALESCE(array_agg(DISTINCT (r->>'artifact_id')::uuid),"
        "'{}') INTO refs\n FROM jsonb_array_elements(coalesce(payload->'read_sources'"
        ",'[]'::jsonb)\n  ||coalesce(payload#>'{versions,project_current_context,sour"
        "ce_proof}','[]'::jsonb)) r;\n RETURN refs;\nEND $function$\n"
    ),
    'kernel_source_reference_gate()': (
        'CREATE OR REPLACE FUNCTION public.kernel_source_reference_gate()\n RETURNS t'
        "rigger\n LANGUAGE plpgsql\n SECURITY DEFINER\n SET search_path TO 'pg_catalo"
        "g', 'public', 'pg_temp'\nAS $function$\nDECLARE r agent_runs; prior agent_ru"
        "ns; ref jsonb; a artifact_versions;\n links uuid[]='{}'; native jsonb; reads"
        " jsonb;\nBEGIN\n IF TG_OP='DELETE' THEN r=OLD; ELSE r=NEW; END IF;\n native="
        "coalesce(r.versions#>'{project_current_context,source_proof}','[]'::jsonb);"
        "\n IF TG_OP='UPDATE' THEN\n  prior=OLD;\n  IF ROW(r.tenant_id,r.category_id,"
        "r.product_id,r.read_sources,\n     r.versions->'project_current_context') IS"
        ' DISTINCT FROM\n     ROW(prior.tenant_id,prior.category_id,prior.product_id,'
        "prior.read_sources,\n     prior.versions->'project_current_context')\n  THEN"
        " RAISE EXCEPTION 'Run source scope immutable' USING ERRCODE='23514'; END IF;"
        "\n  RETURN NEW;\n END IF;\n IF jsonb_typeof(native) IS DISTINCT FROM 'array'"
        "\n THEN RAISE EXCEPTION 'Native project footprint must be an array' USING ER"
        "RCODE='23514'; END IF;\n IF jsonb_typeof(r.read_sources) IS DISTINCT FROM 'a"
        "rray'\n THEN RAISE EXCEPTION 'Run source set must be an array' USING ERRCODE"
        "='23514'; END IF;\n FOR ref IN SELECT value FROM jsonb_array_elements(native"
        ") LOOP\n  IF jsonb_typeof(ref) IS DISTINCT FROM 'object'\n   OR NOT(ref ?& A"
        "RRAY['artifact_id','expected_revision','product_id','content_hash'])\n   OR "
        "ref->>'content_hash' IS NULL OR ref->>'content_hash' !~ '^[a-f0-9]{64}$' THE"
        "N\n   RAISE EXCEPTION 'Native project source requires fixed metadata' USING "
        "ERRCODE='23514';\n  END IF;\n END LOOP;\n reads=r.read_sources||native;\n IF"
        ' jsonb_array_length(native)>0 AND (r.project_id IS NULL OR r.product_id IS N'
        "ULL\n  OR r.versions#>>'{project_current_context,kind}' IS DISTINCT FROM 'pr"
        "oject-current-facts/v1'\n  OR r.versions#>>'{project_current_context,tenant_"
        "id}' IS DISTINCT FROM r.tenant_id::text\n  OR r.versions#>>'{project_current"
        "_context,category_id}' IS DISTINCT FROM r.category_id::text\n  OR r.versions"
        "#>>'{project_current_context,product_id}' IS DISTINCT FROM r.product_id::tex"
        "t\n  OR r.versions#>>'{project_current_context,project_id}' IS DISTINCT FROM"
        " r.project_id::text\n  OR r.versions#>>'{project_current_context,requester_i"
        "d}' IS DISTINCT FROM r.requester_id::text)\n THEN RAISE EXCEPTION 'Native pr"
        "oject footprint requires its actual Run' USING ERRCODE='23514';\n END IF;\n "
        'IF r.category_id IS NULL THEN\n  IF jsonb_array_length(reads)<>0\n  THEN RAI'
        "SE EXCEPTION 'Personal Run cannot consume business sources' USING ERRCODE='2"
        "3514'; END IF;\n  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF"
        ';\n END IF;\n PERFORM 1 FROM public.categories WHERE id=r.category_id AND te'
        "nant_id=r.tenant_id FOR UPDATE;\n IF NOT FOUND THEN RAISE EXCEPTION 'Run sou"
        "rce category unavailable' USING ERRCODE='23514'; END IF;\n IF r.product_id I"
        'S NOT NULL THEN\n  PERFORM 1 FROM public.products WHERE id=r.product_id AND '
        'tenant_id=r.tenant_id\n   AND category_id=r.category_id FOR UPDATE;\n  IF NO'
        "T FOUND THEN RAISE EXCEPTION 'Run source model unavailable' USING ERRCODE='2"
        "3514'; END IF;\n END IF;\n IF TG_OP='DELETE' THEN RETURN OLD; END IF;\n IF N"
        'OT public.kernel_read_set_visible(r.tenant_id,r.category_id,reads)\n THEN RA'
        "ISE EXCEPTION 'Run sources currently unreadable' USING ERRCODE='23514'; END "
        'IF;\n FOR ref IN SELECT value FROM jsonb_array_elements(reads) LOOP\n  SELEC'
        'T * INTO a FROM public.artifact_versions WHERE tenant_id=r.tenant_id\n   AND'
        " category_id=r.category_id AND id=(ref->>'artifact_id')::uuid\n   AND revisi"
        "on=(ref->>'expected_revision')::integer AND status='active'\n   AND (r.produ"
        'ct_id IS NULL OR product_id IS NULL OR product_id=r.product_id)\n   AND prod'
        "uct_id IS NOT DISTINCT FROM (ref->>'product_id')::uuid;\n  IF NOT FOUND THEN"
        " RAISE EXCEPTION 'Run requires exact actual source' USING ERRCODE='23514'; E"
        "ND IF;\n  IF ref ? 'content_hash' AND a.content_hash IS DISTINCT FROM ref->>"
        "'content_hash'\n  THEN RAISE EXCEPTION 'Native project source hash changed' "
        "USING ERRCODE='23514'; END IF;\n  links=array_append(links,a.id);\n  IF a.or"
        'iginal_id IS NOT NULL THEN links=array_append(links,a.original_id); END IF;'
        '\n END LOOP;\n IF EXISTS(SELECT 1 FROM public.lifecycle_objects o\n  WHERE o'
        '.tenant_id=r.tenant_id AND o.category_id=r.category_id AND o.id=ANY(links)\n'
        "   AND (o.state->'value'->>'pending_intent_id' IS NOT NULL\n    OR o.state->"
        "'value'->>'disposition' IN ('quarantined','unknown','purged')))\n THEN RAISE"
        " EXCEPTION 'Pending original prohibits Run source binding'\n  USING ERRCODE="
        "'23514',CONSTRAINT='category_source_reference_fence'; END IF;\n RETURN NEW;"
        '\nEND $function$\n'
    ),
    'kernel_source_reference_clock()': (
        'CREATE OR REPLACE FUNCTION public.kernel_source_reference_clock()\n RETURNS '
        "trigger\n LANGUAGE plpgsql\n SECURITY DEFINER\n SET search_path TO 'pg_catal"
        "og', 'public', 'pg_temp'\nAS $function$\nDECLARE r agent_runs;\nBEGIN\n IF T"
        "G_OP='DELETE' THEN r=OLD; ELSE r=NEW; END IF;\n IF r.category_id IS NOT NULL"
        " AND jsonb_array_length(r.read_sources\n  ||coalesce(r.versions#>'{project_c"
        "urrent_context,source_proof}','[]'::jsonb))>0 THEN\n  UPDATE public.categori"
        'es SET lifecycle_epoch=lifecycle_epoch+1\n   WHERE tenant_id=r.tenant_id AND'
        ' id=r.category_id;\n  IF r.product_id IS NOT NULL THEN\n   UPDATE public.pro'
        'ducts SET lifecycle_epoch=lifecycle_epoch+1\n    WHERE tenant_id=r.tenant_id'
        " AND id=r.product_id;\n  END IF;\n END IF;\n IF TG_OP='DELETE' THEN RETURN O"
        'LD; ELSE RETURN NEW; END IF;\nEND $function$\n'
    ),
}

SCHEMA_SQL = tuple(NATIVE_FUNCTIONS.values())
DOWNGRADE_SQL = tuple(PREVIOUS_FUNCTIONS.values())
EMPTY_HISTORY_SQL = (
    (
        'LOCK TABLE public.agent_runs IN SHARE ROW EXCLUSIVE MODE'
    ),
    (
        'DO $native_history$\nBEGIN\n IF EXISTS(SELECT 1 FROM public.agent_runs r\n  '
        "CROSS JOIN LATERAL jsonb_array_elements(\n   coalesce(r.versions#>'{project_"
        "current_context,source_proof}','[]'::jsonb)) native\n  WHERE NOT EXISTS(SELE"
        'CT 1 FROM jsonb_array_elements(r.read_sources) explicit\n   WHERE explicit->'
        ">'artifact_id'=native->>'artifact_id'\n    AND explicit->>'expected_revision"
        "'=native->>'expected_revision'\n    AND explicit->>'product_id' IS NOT DISTI"
        "NCT FROM native->>'product_id')) THEN\n  RAISE EXCEPTION 'Independent native"
        " project source history requires its retention closure'\n   USING ERRCODE='2"
        "3514',CONSTRAINT='native_project_source_history_retained';\n END IF;\nEND $n"
        'ative_history$;\n'
    ),
)

PREVIOUS_POLICY_USING = (
    'kernel_read_set_visible(tenant_id, category_id, read_sources)'
)

NATIVE_POLICY_USING = (
    'kernel_read_set_visible(tenant_id, category_id, (read_sources || COALESC'
    "E((versions #> '{project_current_context,source_proof}'::text[]), '[]'::"
    'jsonb)))'
)

POLICY_UP_SQL = (
    'ALTER POLICY kernel_source_audience ON public.agent_runs USING (kernel_r'
    'ead_set_visible(tenant_id, category_id, (read_sources || COALESCE((versi'
    "ons #> '{project_current_context,source_proof}'::text[]), '[]'::jsonb)))"
    ')'
)

POLICY_DOWN_SQL = (
    'ALTER POLICY kernel_source_audience ON public.agent_runs USING (kernel_r'
    'ead_set_visible(tenant_id, category_id, read_sources))'
)
