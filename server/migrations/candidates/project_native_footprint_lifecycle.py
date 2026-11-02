"""Unnumbered native project footprint retention candidate; root pins actual catalog DDL.

No new roles, grants, policies, tables or m3 graph/type mappings. Existing owners
and ACLs are preserved by CREATE OR REPLACE. Previous prosrc is exact source SQL;
root must verify it and freeze actual pg_get_functiondef before a numbered wrapper.
"""

PREVIOUS_SOURCE_DDL = {
    'kernel_lifecycle_links(text,jsonb)': (
        'CREATE FUNCTION kernel_lifecycle_links(table_name text,payload jsonb) RETURNS uuid[]\nLANG'
        'UAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public AS $$\nDECLARE refs uuid[];\nBEGI'
        "N\n IF table_name<>'agent_runs' THEN RETURN public.lifecycle_payload_links(payload); END I"
        "F;\n SELECT COALESCE(array_agg((r->>'artifact_id')::uuid),'{}') INTO refs\n FROM jsonb_arr"
        "ay_elements(payload->'read_sources') r;\n RETURN refs;\nEND $$;\n"
    ),
    'kernel_source_reference_gate()': (
        'CREATE OR REPLACE FUNCTION public.kernel_source_reference_gate()\n RETURNS trigger\n LANGU'
        "AGE plpgsql\n SECURITY DEFINER\n SET search_path TO 'pg_catalog', 'public', 'pg_temp'\nAS "
        '$function$\nDECLARE r agent_runs; prior agent_runs; ref jsonb; a artifact_versions; links '
        "uuid[]='{}';\nBEGIN\n IF TG_OP='DELETE' THEN r=OLD; ELSE r=NEW; END IF;\n IF TG_OP='UPDATE"
        "' THEN\n  prior=OLD;\n  IF ROW(r.tenant_id,r.category_id,r.product_id,r.read_sources) IS D"
        'ISTINCT FROM\n     ROW(prior.tenant_id,prior.category_id,prior.product_id,prior.read_sourc'
        "es)\n  THEN RAISE EXCEPTION 'Run source scope immutable' USING ERRCODE='23514'; END IF;\n "
        " RETURN NEW;\n END IF;\n IF jsonb_typeof(r.read_sources) IS DISTINCT FROM 'array'\n THEN R"
        "AISE EXCEPTION 'Run source set must be an array' USING ERRCODE='23514'; END IF;\n IF r.cat"
        'egory_id IS NULL THEN\n  IF jsonb_array_length(r.read_sources)<>0\n  THEN RAISE EXCEPTION '
        "'Personal Run cannot consume business sources' USING ERRCODE='23514'; END IF;\n  IF TG_OP="
        "'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n END IF;\n PERFORM 1 FROM public.categ"
        'ories WHERE id=r.category_id AND tenant_id=r.tenant_id FOR UPDATE;\n IF NOT FOUND THEN RAI'
        "SE EXCEPTION 'Run source category unavailable' USING ERRCODE='23514'; END IF;\n IF r.produ"
        'ct_id IS NOT NULL THEN\n  PERFORM 1 FROM public.products WHERE id=r.product_id AND tenant_'
        'id=r.tenant_id\n   AND category_id=r.category_id FOR UPDATE;\n  IF NOT FOUND THEN RAISE EX'
        "CEPTION 'Run source model unavailable' USING ERRCODE='23514'; END IF;\n END IF;\n IF TG_OP"
        "='DELETE' THEN RETURN OLD; END IF;\n IF NOT public.kernel_read_set_visible(r.tenant_id,r.c"
        "ategory_id,r.read_sources)\n THEN RAISE EXCEPTION 'Run sources currently unreadable' USING"
        " ERRCODE='23514'; END IF;\n FOR ref IN SELECT value FROM jsonb_array_elements(r.read_sourc"
        'es) LOOP\n  SELECT * INTO a FROM public.artifact_versions WHERE tenant_id=r.tenant_id\n   '
        "AND category_id=r.category_id AND id=(ref->>'artifact_id')::uuid\n   AND revision=(ref->>'"
        "expected_revision')::integer AND status='active'\n   AND (r.product_id IS NULL OR product_"
        "id IS NULL OR product_id=r.product_id)\n   AND product_id IS NOT DISTINCT FROM (ref->>'pro"
        "duct_id')::uuid;\n  IF NOT FOUND THEN RAISE EXCEPTION 'Run requires exact actual source' U"
        "SING ERRCODE='23514'; END IF;\n  links=array_append(links,a.id);\n  IF a.original_id IS NO"
        'T NULL THEN links=array_append(links,a.original_id); END IF;\n END LOOP;\n IF EXISTS(SELEC'
        'T 1 FROM public.lifecycle_objects o\n  WHERE o.tenant_id=r.tenant_id AND o.category_id=r.c'
        "ategory_id AND o.id=ANY(links)\n   AND (o.state->'value'->>'pending_intent_id' IS NOT NULL"
        "\n    OR o.state->'value'->>'disposition' IN ('quarantined','unknown','purged')))\n THEN R"
        "AISE EXCEPTION 'Pending original prohibits Run source binding'\n  USING ERRCODE='23514',CO"
        "NSTRAINT='category_source_reference_fence'; END IF;\n RETURN NEW;\nEND $function$\n"
    ),
    'kernel_source_reference_clock()': (
        'CREATE FUNCTION kernel_source_reference_clock() RETURNS trigger\nLANGUAGE plpgsql SECURITY'
        ' DEFINER SET search_path=pg_catalog,public AS $$\nDECLARE r agent_runs;\nBEGIN\n IF TG_OP='
        "'DELETE' THEN r=OLD; ELSE r=NEW; END IF;\n IF r.category_id IS NOT NULL AND jsonb_array_le"
        'ngth(r.read_sources)>0 THEN\n  UPDATE public.categories SET lifecycle_epoch=lifecycle_epoc'
        'h+1\n   WHERE tenant_id=r.tenant_id AND id=r.category_id;\n  IF r.product_id IS NOT NULL T'
        'HEN\n   UPDATE public.products SET lifecycle_epoch=lifecycle_epoch+1\n    WHERE tenant_id='
        "r.tenant_id AND id=r.product_id;\n  END IF;\n END IF;\n IF TG_OP='DELETE' THEN RETURN OLD;"
        ' ELSE RETURN NEW; END IF;\nEND $$;\n'
    ),
}

PREVIOUS_PROSRC = {
    'kernel_lifecycle_links(text,jsonb)': (
        "\nDECLARE refs uuid[];\nBEGIN\n IF table_name<>'agent_runs' THEN RETURN public.lifecycle_p"
        "ayload_links(payload); END IF;\n SELECT COALESCE(array_agg((r->>'artifact_id')::uuid),'{}'"
        ") INTO refs\n FROM jsonb_array_elements(payload->'read_sources') r;\n RETURN refs;\nEND "
    ),
    'kernel_source_reference_gate()': (
        "\nDECLARE r agent_runs; prior agent_runs; ref jsonb; a artifact_versions; links uuid[]='{}"
        "';\nBEGIN\n IF TG_OP='DELETE' THEN r=OLD; ELSE r=NEW; END IF;\n IF TG_OP='UPDATE' THEN\n  "
        'prior=OLD;\n  IF ROW(r.tenant_id,r.category_id,r.product_id,r.read_sources) IS DISTINCT FR'
        'OM\n     ROW(prior.tenant_id,prior.category_id,prior.product_id,prior.read_sources)\n  THE'
        "N RAISE EXCEPTION 'Run source scope immutable' USING ERRCODE='23514'; END IF;\n  RETURN NE"
        "W;\n END IF;\n IF jsonb_typeof(r.read_sources) IS DISTINCT FROM 'array'\n THEN RAISE EXCEP"
        "TION 'Run source set must be an array' USING ERRCODE='23514'; END IF;\n IF r.category_id I"
        "S NULL THEN\n  IF jsonb_array_length(r.read_sources)<>0\n  THEN RAISE EXCEPTION 'Personal "
        "Run cannot consume business sources' USING ERRCODE='23514'; END IF;\n  IF TG_OP='DELETE' T"
        'HEN RETURN OLD; ELSE RETURN NEW; END IF;\n END IF;\n PERFORM 1 FROM public.categories WHER'
        'E id=r.category_id AND tenant_id=r.tenant_id FOR UPDATE;\n IF NOT FOUND THEN RAISE EXCEPTI'
        "ON 'Run source category unavailable' USING ERRCODE='23514'; END IF;\n IF r.product_id IS N"
        'OT NULL THEN\n  PERFORM 1 FROM public.products WHERE id=r.product_id AND tenant_id=r.tenan'
        "t_id\n   AND category_id=r.category_id FOR UPDATE;\n  IF NOT FOUND THEN RAISE EXCEPTION 'R"
        "un source model unavailable' USING ERRCODE='23514'; END IF;\n END IF;\n IF TG_OP='DELETE' "
        'THEN RETURN OLD; END IF;\n IF NOT public.kernel_read_set_visible(r.tenant_id,r.category_id'
        ",r.read_sources)\n THEN RAISE EXCEPTION 'Run sources currently unreadable' USING ERRCODE='"
        "23514'; END IF;\n FOR ref IN SELECT value FROM jsonb_array_elements(r.read_sources) LOOP\n"
        '  SELECT * INTO a FROM public.artifact_versions WHERE tenant_id=r.tenant_id\n   AND catego'
        "ry_id=r.category_id AND id=(ref->>'artifact_id')::uuid\n   AND revision=(ref->>'expected_r"
        "evision')::integer AND status='active'\n   AND (r.product_id IS NULL OR product_id IS NULL"
        " OR product_id=r.product_id)\n   AND product_id IS NOT DISTINCT FROM (ref->>'product_id'):"
        ":uuid;\n  IF NOT FOUND THEN RAISE EXCEPTION 'Run requires exact actual source' USING ERRCO"
        "DE='23514'; END IF;\n  links=array_append(links,a.id);\n  IF a.original_id IS NOT NULL THE"
        'N links=array_append(links,a.original_id); END IF;\n END LOOP;\n IF EXISTS(SELECT 1 FROM p'
        'ublic.lifecycle_objects o\n  WHERE o.tenant_id=r.tenant_id AND o.category_id=r.category_id'
        " AND o.id=ANY(links)\n   AND (o.state->'value'->>'pending_intent_id' IS NOT NULL\n    OR o"
        ".state->'value'->>'disposition' IN ('quarantined','unknown','purged')))\n THEN RAISE EXCEP"
        "TION 'Pending original prohibits Run source binding'\n  USING ERRCODE='23514',CONSTRAINT='"
        "category_source_reference_fence'; END IF;\n RETURN NEW;\nEND "
    ),
    'kernel_source_reference_clock()': (
        "\nDECLARE r agent_runs;\nBEGIN\n IF TG_OP='DELETE' THEN r=OLD; ELSE r=NEW; END IF;\n IF r."
        'category_id IS NOT NULL AND jsonb_array_length(r.read_sources)>0 THEN\n  UPDATE public.cat'
        'egories SET lifecycle_epoch=lifecycle_epoch+1\n   WHERE tenant_id=r.tenant_id AND id=r.cat'
        'egory_id;\n  IF r.product_id IS NOT NULL THEN\n   UPDATE public.products SET lifecycle_epo'
        'ch=lifecycle_epoch+1\n    WHERE tenant_id=r.tenant_id AND id=r.product_id;\n  END IF;\n EN'
        "D IF;\n IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\nEND "
    ),
}

NATIVE_FUNCTIONS = {
    'kernel_lifecycle_links(text,jsonb)': (
        'CREATE OR REPLACE FUNCTION public.kernel_lifecycle_links(table_name text,payload jsonb)\nR'
        'ETURNS uuid[] LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public AS $function$\n'
        "DECLARE refs uuid[];\nBEGIN\n IF table_name<>'agent_runs' THEN RETURN public.lifecycle_pay"
        "load_links(payload); END IF;\n SELECT COALESCE(array_agg(DISTINCT (r->>'artifact_id')::uui"
        "d),'{}') INTO refs\n FROM jsonb_array_elements(coalesce(payload->'read_sources','[]'::json"
        "b)\n  ||coalesce(payload#>'{versions,project_current_context,source_proof}','[]'::jsonb)) "
        'r;\n RETURN refs;\nEND $function$;\n'
    ),
    'kernel_source_reference_gate()': (
        'CREATE OR REPLACE FUNCTION public.kernel_source_reference_gate()\n RETURNS trigger\n LANGU'
        "AGE plpgsql\n SECURITY DEFINER\n SET search_path TO 'pg_catalog', 'public', 'pg_temp'\nAS "
        '$function$\nDECLARE r agent_runs; prior agent_runs; ref jsonb; a artifact_versions;\n link'
        "s uuid[]='{}'; native jsonb; reads jsonb;\nBEGIN\n IF TG_OP='DELETE' THEN r=OLD; ELSE r=NE"
        "W; END IF;\n native=coalesce(r.versions#>'{project_current_context,source_proof}','[]'::js"
        "onb);\n IF TG_OP='UPDATE' THEN\n  prior=OLD;\n  IF ROW(r.tenant_id,r.category_id,r.product"
        "_id,r.read_sources,\n     r.versions->'project_current_context') IS DISTINCT FROM\n     RO"
        'W(prior.tenant_id,prior.category_id,prior.product_id,prior.read_sources,\n     prior.versi'
        "ons->'project_current_context')\n  THEN RAISE EXCEPTION 'Run source scope immutable' USING"
        " ERRCODE='23514'; END IF;\n  RETURN NEW;\n END IF;\n IF jsonb_typeof(native) IS DISTINCT F"
        "ROM 'array'\n THEN RAISE EXCEPTION 'Native project footprint must be an array' USING ERRCO"
        "DE='23514'; END IF;\n IF jsonb_typeof(r.read_sources) IS DISTINCT FROM 'array'\n THEN RAIS"
        "E EXCEPTION 'Run source set must be an array' USING ERRCODE='23514'; END IF;\n FOR ref IN "
        'SELECT value FROM jsonb_array_elements(native) LOOP\n  IF jsonb_typeof(ref) IS DISTINCT FR'
        "OM 'object'\n   OR NOT(ref ?& ARRAY['artifact_id','expected_revision','product_id','conten"
        "t_hash'])\n   OR ref->>'content_hash' IS NULL OR ref->>'content_hash' !~ '^[a-f0-9]{64}$' "
        "THEN\n   RAISE EXCEPTION 'Native project source requires fixed metadata' USING ERRCODE='23"
        "514';\n  END IF;\n END LOOP;\n reads=r.read_sources||native;\n IF jsonb_array_length(nativ"
        "e)>0 AND (r.project_id IS NULL OR r.product_id IS NULL\n  OR r.versions#>>'{project_curren"
        "t_context,kind}' IS DISTINCT FROM 'project-current-facts/v1'\n  OR r.versions#>>'{project_"
        "current_context,tenant_id}' IS DISTINCT FROM r.tenant_id::text\n  OR r.versions#>>'{projec"
        "t_current_context,category_id}' IS DISTINCT FROM r.category_id::text\n  OR r.versions#>>'{"
        "project_current_context,product_id}' IS DISTINCT FROM r.product_id::text\n  OR r.versions#"
        ">>'{project_current_context,project_id}' IS DISTINCT FROM r.project_id::text\n  OR r.versi"
        "ons#>>'{project_current_context,requester_id}' IS DISTINCT FROM r.requester_id::text)\n TH"
        "EN RAISE EXCEPTION 'Native project footprint requires its actual Run' USING ERRCODE='23514"
        "';\n END IF;\n IF r.category_id IS NULL THEN\n  IF jsonb_array_length(reads)<>0\n  THEN RA"
        "ISE EXCEPTION 'Personal Run cannot consume business sources' USING ERRCODE='23514'; END IF"
        ";\n  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n END IF;\n PERFORM 1 FRO"
        'M public.categories WHERE id=r.category_id AND tenant_id=r.tenant_id FOR UPDATE;\n IF NOT '
        "FOUND THEN RAISE EXCEPTION 'Run source category unavailable' USING ERRCODE='23514'; END IF"
        ';\n IF r.product_id IS NOT NULL THEN\n  PERFORM 1 FROM public.products WHERE id=r.product_'
        'id AND tenant_id=r.tenant_id\n   AND category_id=r.category_id FOR UPDATE;\n  IF NOT FOUND'
        " THEN RAISE EXCEPTION 'Run source model unavailable' USING ERRCODE='23514'; END IF;\n END "
        "IF;\n IF TG_OP='DELETE' THEN RETURN OLD; END IF;\n IF NOT public.kernel_read_set_visible(r"
        ".tenant_id,r.category_id,reads)\n THEN RAISE EXCEPTION 'Run sources currently unreadable' "
        "USING ERRCODE='23514'; END IF;\n FOR ref IN SELECT value FROM jsonb_array_elements(reads) "
        'LOOP\n  SELECT * INTO a FROM public.artifact_versions WHERE tenant_id=r.tenant_id\n   AND '
        "category_id=r.category_id AND id=(ref->>'artifact_id')::uuid\n   AND revision=(ref->>'expe"
        "cted_revision')::integer AND status='active'\n   AND (r.product_id IS NULL OR product_id I"
        "S NULL OR product_id=r.product_id)\n   AND product_id IS NOT DISTINCT FROM (ref->>'product"
        "_id')::uuid;\n  IF NOT FOUND THEN RAISE EXCEPTION 'Run requires exact actual source' USING"
        " ERRCODE='23514'; END IF;\n  IF ref ? 'content_hash' AND a.content_hash IS DISTINCT FROM r"
        "ef->>'content_hash'\n  THEN RAISE EXCEPTION 'Native project source hash changed' USING ERR"
        "CODE='23514'; END IF;\n  links=array_append(links,a.id);\n  IF a.original_id IS NOT NULL T"
        'HEN links=array_append(links,a.original_id); END IF;\n END LOOP;\n IF EXISTS(SELECT 1 FROM'
        ' public.lifecycle_objects o\n  WHERE o.tenant_id=r.tenant_id AND o.category_id=r.category_'
        "id AND o.id=ANY(links)\n   AND (o.state->'value'->>'pending_intent_id' IS NOT NULL\n    OR"
        " o.state->'value'->>'disposition' IN ('quarantined','unknown','purged')))\n THEN RAISE EXC"
        "EPTION 'Pending original prohibits Run source binding'\n  USING ERRCODE='23514',CONSTRAINT"
        "='category_source_reference_fence'; END IF;\n RETURN NEW;\nEND $function$\n"
    ),
    'kernel_source_reference_clock()': (
        'CREATE OR REPLACE FUNCTION public.kernel_source_reference_clock() RETURNS trigger\nLANGUAG'
        'E plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$\nDECLARE r agent_runs;'
        "\nBEGIN\n IF TG_OP='DELETE' THEN r=OLD; ELSE r=NEW; END IF;\n IF r.category_id IS NOT NULL"
        " AND jsonb_array_length(r.read_sources\n  ||coalesce(r.versions#>'{project_current_context"
        ",source_proof}','[]'::jsonb))>0 THEN\n  UPDATE public.categories SET lifecycle_epoch=lifec"
        'ycle_epoch+1\n   WHERE tenant_id=r.tenant_id AND id=r.category_id;\n  IF r.product_id IS N'
        'OT NULL THEN\n   UPDATE public.products SET lifecycle_epoch=lifecycle_epoch+1\n    WHERE t'
        "enant_id=r.tenant_id AND id=r.product_id;\n  END IF;\n END IF;\n IF TG_OP='DELETE' THEN RE"
        'TURN OLD; ELSE RETURN NEW; END IF;\nEND $$;\n'
    ),
}

DOWN_HISTORY_GUARD = (
    'DO $native_history$\nBEGIN\n IF EXISTS(SELECT 1 FROM public.agent_runs r\n  CROSS JOIN LAT'
    "ERAL jsonb_array_elements(\n   coalesce(r.versions#>'{project_current_context,source_proof"
    "}','[]'::jsonb)) native\n  WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements(r.read_sour"
    "ces) explicit\n   WHERE explicit->>'artifact_id'=native->>'artifact_id'\n    AND explicit-"
    ">>'expected_revision'=native->>'expected_revision'\n    AND explicit->>'product_id' IS NOT"
    " DISTINCT FROM native->>'product_id')) THEN\n  RAISE EXCEPTION 'Independent native project"
    " source history requires its retention closure'\n   USING ERRCODE='23514',CONSTRAINT='nati"
    "ve_project_source_history_retained';\n END IF;\nEND $native_history$;\n"
)

SCHEMA_SQL = tuple(NATIVE_FUNCTIONS.values())
# Original 0718 source says CREATE FUNCTION; restoration must replace in place.
RESTORE_SQL = tuple(sql.replace("CREATE FUNCTION kernel_",
                                "CREATE OR REPLACE FUNCTION public.kernel_")
                    for sql in PREVIOUS_SOURCE_DDL.values())
DOWNGRADE_SQL = (DOWN_HISTORY_GUARD, *RESTORE_SQL)
