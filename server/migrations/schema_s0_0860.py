"""P91 personal Run sources: read-set visibility, source gate and lifecycle clock.

A personal Run (category_id NULL) may pin registered sources only when its Human
requester, acting for self, can read each exact active version now in that
source's own category; one receipt row per source records category and data
class. Everything else about the category gate is unchanged. Sequenced after
s0_0859 at the 11-08 integration; the SQL below is as written on s0_0855.
"""

# ruff: noqa: E501 -- Reviewed applied SQL literals remain byte-identical.

PREVIOUS_FUNCTIONS = {
    'kernel_read_set_visible(uuid,uuid,jsonb)': (
        'CREATE OR REPLACE FUNCTION public.kernel_read_set_visible(t uuid, c uuid, refs jsonb)\n'
        ' RETURNS boolean\n'
        ' LANGUAGE sql\n'
        ' STABLE SECURITY DEFINER\n'
        " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
        'AS $function$\n'
        "      SELECT jsonb_typeof(refs)='array' AND NOT EXISTS (\n"
        '        SELECT 1 FROM jsonb_array_elements(refs) r WHERE\n'
        "        NOT COALESCE(direct_source_set_visible(t,c,(r->>'product_id')::uuid,\n"
        '          jsonb_build_array(r)),false)) $function$\n'
    ),
    'kernel_source_reference_gate()': (
        'CREATE OR REPLACE FUNCTION public.kernel_source_reference_gate()\n'
        ' RETURNS trigger\n'
        ' LANGUAGE plpgsql\n'
        ' SECURITY DEFINER\n'
        " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
        'AS $function$\n'
        'DECLARE r agent_runs; prior agent_runs; ref jsonb; a artifact_versions;\n'
        " links uuid[]='{}'; native jsonb; reads jsonb;\n"
        'BEGIN\n'
        " IF TG_OP='DELETE' THEN r=OLD; ELSE r=NEW; END IF;\n"
        " native=coalesce(r.versions#>'{project_current_context,source_proof}','[]'::jsonb);\n"
        " IF TG_OP='UPDATE' THEN\n"
        '  prior=OLD;\n'
        '  IF ROW(r.tenant_id,r.category_id,r.product_id,r.read_sources,\n'
        "     r.versions->'project_current_context') IS DISTINCT FROM\n"
        '     ROW(prior.tenant_id,prior.category_id,prior.product_id,prior.read_sources,\n'
        "     prior.versions->'project_current_context')\n"
        "  THEN RAISE EXCEPTION 'Run source scope immutable' USING ERRCODE='23514'; END IF;\n"
        '  RETURN NEW;\n'
        ' END IF;\n'
        " IF jsonb_typeof(native) IS DISTINCT FROM 'array'\n"
        " THEN RAISE EXCEPTION 'Native project footprint must be an array' USING ERRCODE='23514'; END IF;\n"
        " IF jsonb_typeof(r.read_sources) IS DISTINCT FROM 'array'\n"
        " THEN RAISE EXCEPTION 'Run source set must be an array' USING ERRCODE='23514'; END IF;\n"
        ' FOR ref IN SELECT value FROM jsonb_array_elements(native) LOOP\n'
        "  IF jsonb_typeof(ref) IS DISTINCT FROM 'object'\n"
        "   OR NOT(ref ?& ARRAY['artifact_id','expected_revision','product_id','content_hash'])\n"
        "   OR ref->>'content_hash' IS NULL OR ref->>'content_hash' !~ '^[a-f0-9]{64}$' THEN\n"
        "   RAISE EXCEPTION 'Native project source requires fixed metadata' USING ERRCODE='23514';\n"
        '  END IF;\n'
        ' END LOOP;\n'
        ' reads=r.read_sources||native;\n'
        ' IF jsonb_array_length(native)>0 AND (r.project_id IS NULL OR r.product_id IS NULL\n'
        "  OR (r.versions#>>'{project_current_context,kind}' IS DISTINCT FROM 'project-current-facts/v1'\n"
        "   AND r.versions#>>'{project_current_context,kind}' IS DISTINCT FROM 'project-current-facts/v2')\n"
        "  OR r.versions#>>'{project_current_context,tenant_id}' IS DISTINCT FROM r.tenant_id::text\n"
        "  OR r.versions#>>'{project_current_context,category_id}' IS DISTINCT FROM r.category_id::text\n"
        "  OR r.versions#>>'{project_current_context,product_id}' IS DISTINCT FROM r.product_id::text\n"
        "  OR r.versions#>>'{project_current_context,project_id}' IS DISTINCT FROM r.project_id::text\n"
        "  OR r.versions#>>'{project_current_context,requester_id}' IS DISTINCT FROM r.requester_id::text)\n"
        " THEN RAISE EXCEPTION 'Native project footprint requires its actual Run' USING ERRCODE='23514';\n"
        ' END IF;\n'
        ' IF r.category_id IS NULL THEN\n'
        '  IF jsonb_array_length(reads)<>0\n'
        "  THEN RAISE EXCEPTION 'Personal Run cannot consume business sources' USING ERRCODE='23514'; END IF;\n"
        "  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n"
        ' END IF;\n'
        ' PERFORM 1 FROM public.categories WHERE id=r.category_id AND tenant_id=r.tenant_id FOR UPDATE;\n'
        " IF NOT FOUND THEN RAISE EXCEPTION 'Run source category unavailable' USING ERRCODE='23514'; END IF;\n"
        ' IF r.product_id IS NOT NULL THEN\n'
        '  PERFORM 1 FROM public.products WHERE id=r.product_id AND tenant_id=r.tenant_id\n'
        '   AND category_id=r.category_id FOR UPDATE;\n'
        "  IF NOT FOUND THEN RAISE EXCEPTION 'Run source model unavailable' USING ERRCODE='23514'; END IF;\n"
        ' END IF;\n'
        " IF TG_OP='DELETE' THEN RETURN OLD; END IF;\n"
        ' IF NOT public.kernel_read_set_visible(r.tenant_id,r.category_id,reads)\n'
        " THEN RAISE EXCEPTION 'Run sources currently unreadable' USING ERRCODE='23514'; END IF;\n"
        ' FOR ref IN SELECT value FROM jsonb_array_elements(reads) LOOP\n'
        '  SELECT * INTO a FROM public.artifact_versions WHERE tenant_id=r.tenant_id\n'
        "   AND category_id=r.category_id AND id=(ref->>'artifact_id')::uuid\n"
        "   AND revision=(ref->>'expected_revision')::integer AND status='active'\n"
        '   AND (r.product_id IS NULL OR product_id IS NULL OR product_id=r.product_id)\n'
        "   AND product_id IS NOT DISTINCT FROM (ref->>'product_id')::uuid;\n"
        "  IF NOT FOUND THEN RAISE EXCEPTION 'Run requires exact actual source' USING ERRCODE='23514'; END IF;\n"
        "  IF ref ? 'content_hash' AND a.content_hash IS DISTINCT FROM ref->>'content_hash'\n"
        "  THEN RAISE EXCEPTION 'Native project source hash changed' USING ERRCODE='23514'; END IF;\n"
        '  links=array_append(links,a.id);\n'
        '  IF a.original_id IS NOT NULL THEN links=array_append(links,a.original_id); END IF;\n'
        ' END LOOP;\n'
        ' IF EXISTS(SELECT 1 FROM public.lifecycle_objects o\n'
        '  WHERE o.tenant_id=r.tenant_id AND o.category_id=r.category_id AND o.id=ANY(links)\n'
        "   AND (o.state->'value'->>'pending_intent_id' IS NOT NULL\n"
        "    OR o.state->'value'->>'disposition' IN ('quarantined','unknown','purged')))\n"
        " THEN RAISE EXCEPTION 'Pending original prohibits Run source binding'\n"
        "  USING ERRCODE='23514',CONSTRAINT='category_source_reference_fence'; END IF;\n"
        ' RETURN NEW;\n'
        'END $function$\n'
    ),
    'kernel_source_reference_clock()': (
        'CREATE OR REPLACE FUNCTION public.kernel_source_reference_clock()\n'
        ' RETURNS trigger\n'
        ' LANGUAGE plpgsql\n'
        ' SECURITY DEFINER\n'
        " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
        'AS $function$\n'
        'DECLARE r agent_runs;\n'
        'BEGIN\n'
        " IF TG_OP='DELETE' THEN r=OLD; ELSE r=NEW; END IF;\n"
        ' IF r.category_id IS NOT NULL AND jsonb_array_length(r.read_sources\n'
        "  ||coalesce(r.versions#>'{project_current_context,source_proof}','[]'::jsonb))>0 THEN\n"
        '  UPDATE public.categories SET lifecycle_epoch=lifecycle_epoch+1\n'
        '   WHERE tenant_id=r.tenant_id AND id=r.category_id;\n'
        '  IF r.product_id IS NOT NULL THEN\n'
        '   UPDATE public.products SET lifecycle_epoch=lifecycle_epoch+1\n'
        '    WHERE tenant_id=r.tenant_id AND id=r.product_id;\n'
        '  END IF;\n'
        ' END IF;\n'
        " IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n"
        'END $function$\n'
    ),
}

PERSONAL_FUNCTIONS = {
    'kernel_read_set_visible(uuid,uuid,jsonb)': (
        'CREATE OR REPLACE FUNCTION public.kernel_read_set_visible(t uuid, c uuid, refs jsonb)\n'
        ' RETURNS boolean\n'
        ' LANGUAGE sql\n'
        ' STABLE SECURITY DEFINER\n'
        " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
        'AS $function$\n'
        "      SELECT jsonb_typeof(refs)='array' AND NOT EXISTS (\n"
        '        SELECT 1 FROM jsonb_array_elements(refs) r WHERE\n'
        '        NOT COALESCE(direct_source_set_visible(t,COALESCE(c,(SELECT a.category_id\n'
        '          FROM public.artifact_versions a WHERE a.tenant_id=t\n'
        "           AND a.id=(r->>'artifact_id')::uuid)),(r->>'product_id')::uuid,\n"
        '          jsonb_build_array(r)),false)) $function$\n'
    ),
    'kernel_source_reference_gate()': (
        'CREATE OR REPLACE FUNCTION public.kernel_source_reference_gate()\n'
        ' RETURNS trigger\n'
        ' LANGUAGE plpgsql\n'
        ' SECURITY DEFINER\n'
        " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
        'AS $function$\n'
        'DECLARE r agent_runs; prior agent_runs; ref jsonb; a artifact_versions;\n'
        " links uuid[]='{}'; native jsonb; reads jsonb; personal jsonb; entry jsonb;\n"
        'BEGIN\n'
        " IF TG_OP='DELETE' THEN r=OLD; ELSE r=NEW; END IF;\n"
        " native=coalesce(r.versions#>'{project_current_context,source_proof}','[]'::jsonb);\n"
        " IF TG_OP='UPDATE' THEN\n"
        '  prior=OLD;\n'
        '  IF ROW(r.tenant_id,r.category_id,r.product_id,r.read_sources,\n'
        "     r.versions->'project_current_context',r.versions->'personal_sources') IS DISTINCT FROM\n"
        '     ROW(prior.tenant_id,prior.category_id,prior.product_id,prior.read_sources,\n'
        "     prior.versions->'project_current_context',prior.versions->'personal_sources')\n"
        "  THEN RAISE EXCEPTION 'Run source scope immutable' USING ERRCODE='23514'; END IF;\n"
        '  RETURN NEW;\n'
        ' END IF;\n'
        " IF jsonb_typeof(native) IS DISTINCT FROM 'array'\n"
        " THEN RAISE EXCEPTION 'Native project footprint must be an array' USING ERRCODE='23514'; END IF;\n"
        " IF jsonb_typeof(r.read_sources) IS DISTINCT FROM 'array'\n"
        " THEN RAISE EXCEPTION 'Run source set must be an array' USING ERRCODE='23514'; END IF;\n"
        ' FOR ref IN SELECT value FROM jsonb_array_elements(native) LOOP\n'
        "  IF jsonb_typeof(ref) IS DISTINCT FROM 'object'\n"
        "   OR NOT(ref ?& ARRAY['artifact_id','expected_revision','product_id','content_hash'])\n"
        "   OR ref->>'content_hash' IS NULL OR ref->>'content_hash' !~ '^[a-f0-9]{64}$' THEN\n"
        "   RAISE EXCEPTION 'Native project source requires fixed metadata' USING ERRCODE='23514';\n"
        '  END IF;\n'
        ' END LOOP;\n'
        ' reads=r.read_sources||native;\n'
        ' IF jsonb_array_length(native)>0 AND (r.project_id IS NULL OR r.product_id IS NULL\n'
        "  OR (r.versions#>>'{project_current_context,kind}' IS DISTINCT FROM 'project-current-facts/v1'\n"
        "   AND r.versions#>>'{project_current_context,kind}' IS DISTINCT FROM 'project-current-facts/v2')\n"
        "  OR r.versions#>>'{project_current_context,tenant_id}' IS DISTINCT FROM r.tenant_id::text\n"
        "  OR r.versions#>>'{project_current_context,category_id}' IS DISTINCT FROM r.category_id::text\n"
        "  OR r.versions#>>'{project_current_context,product_id}' IS DISTINCT FROM r.product_id::text\n"
        "  OR r.versions#>>'{project_current_context,project_id}' IS DISTINCT FROM r.project_id::text\n"
        "  OR r.versions#>>'{project_current_context,requester_id}' IS DISTINCT FROM r.requester_id::text)\n"
        " THEN RAISE EXCEPTION 'Native project footprint requires its actual Run' USING ERRCODE='23514';\n"
        ' END IF;\n'
        " personal=r.versions->'personal_sources';\n"
        ' IF r.category_id IS NOT NULL AND personal IS NOT NULL\n'
        " THEN RAISE EXCEPTION 'Category Run cannot carry personal source receipts' USING ERRCODE='23514'; END IF;\n"
        ' IF r.category_id IS NULL THEN\n'
        '  -- P91: a personal Run pins only sources its Human requester can read now,\n'
        "  -- each checked in that source's own category. Native footprints stay project-only.\n"
        '  IF jsonb_array_length(native)<>0\n'
        '   OR (jsonb_array_length(r.read_sources)=0) IS DISTINCT FROM (personal IS NULL)\n'
        "  THEN RAISE EXCEPTION 'Personal Run cannot consume business sources' USING ERRCODE='23514'; END IF;\n"
        "  IF TG_OP='DELETE' THEN RETURN OLD; END IF;\n"
        '  IF personal IS NULL THEN RETURN NEW; END IF;\n'
        '  IF r.product_id IS NOT NULL OR r.proposal_id IS NOT NULL OR r.project_id IS NOT NULL\n'
        '   OR public.scope_actor() IS DISTINCT FROM r.requester_id\n'
        '   OR public.scope_requester() IS DISTINCT FROM r.requester_id\n'
        '   OR NOT EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=r.tenant_id\n'
        "    AND p.id=r.requester_id AND p.kind='human' AND p.active)\n"
        "  THEN RAISE EXCEPTION 'Personal Run sources require the Human requester'\n"
        "   USING ERRCODE='23514',CONSTRAINT='personal_run_source_requester'; END IF;\n"
        "  IF jsonb_typeof(personal) IS DISTINCT FROM 'array'\n"
        '   OR jsonb_array_length(personal)<>jsonb_array_length(r.read_sources)\n'
        "   OR (SELECT count(DISTINCT value->>'artifact_id') FROM jsonb_array_elements(personal))\n"
        '    <>jsonb_array_length(personal)\n'
        "  THEN RAISE EXCEPTION 'Personal Run sources require one category receipt each'\n"
        "   USING ERRCODE='23514'; END IF;\n"
        '  FOR ref IN SELECT value FROM jsonb_array_elements(r.read_sources) LOOP\n'
        '   SELECT value INTO entry FROM jsonb_array_elements(personal)\n'
        "    WHERE value->>'artifact_id'=ref->>'artifact_id';\n"
        "   IF entry IS NULL OR (entry-'category_id'-'data_category') IS DISTINCT FROM ref\n"
        "   THEN RAISE EXCEPTION 'Personal Run source receipt mismatch' USING ERRCODE='23514'; END IF;\n"
        '   SELECT * INTO a FROM public.artifact_versions WHERE tenant_id=r.tenant_id\n'
        "    AND category_id=(entry->>'category_id')::uuid AND id=(ref->>'artifact_id')::uuid\n"
        "    AND revision=(ref->>'expected_revision')::integer AND status='active'\n"
        "    AND product_id IS NOT DISTINCT FROM (ref->>'product_id')::uuid;\n"
        "   IF NOT FOUND THEN RAISE EXCEPTION 'Run requires exact actual source' USING ERRCODE='23514'; END IF;\n"
        "   IF entry->>'data_category' IS DISTINCT FROM\n"
        "     (CASE WHEN a.original_id IS NULL THEN 'internal' ELSE 'customer_original' END)\n"
        "    OR (a.original_id IS NOT NULL AND NOT r.data_categories ? 'customer_original')\n"
        "   THEN RAISE EXCEPTION 'Personal Run source data category mismatch' USING ERRCODE='23514'; END IF;\n"
        '   IF NOT EXISTS(SELECT 1 FROM public.grants g WHERE g.tenant_id=r.tenant_id\n'
        '     AND g.category_id=a.category_id AND g.principal_id=r.requester_id\n'
        '     AND (g.expires_at IS NULL OR g.expires_at>statement_timestamp()))\n'
        '    OR NOT public.direct_source_set_visible(r.tenant_id,a.category_id,a.product_id,\n'
        '     jsonb_build_array(ref))\n'
        "   THEN RAISE EXCEPTION 'Run sources currently unreadable' USING ERRCODE='23514'; END IF;\n"
        '   IF EXISTS(SELECT 1 FROM public.lifecycle_objects o\n'
        '    WHERE o.tenant_id=r.tenant_id AND o.category_id=a.category_id\n'
        '     AND o.id IN (a.id,a.original_id)\n'
        "     AND (o.state->'value'->>'pending_intent_id' IS NOT NULL\n"
        "      OR o.state->'value'->>'disposition' IN ('quarantined','unknown','purged')))\n"
        "   THEN RAISE EXCEPTION 'Pending original prohibits Run source binding'\n"
        "    USING ERRCODE='23514',CONSTRAINT='category_source_reference_fence'; END IF;\n"
        '  END LOOP;\n'
        '  RETURN NEW;\n'
        ' END IF;\n'
        ' PERFORM 1 FROM public.categories WHERE id=r.category_id AND tenant_id=r.tenant_id FOR UPDATE;\n'
        " IF NOT FOUND THEN RAISE EXCEPTION 'Run source category unavailable' USING ERRCODE='23514'; END IF;\n"
        ' IF r.product_id IS NOT NULL THEN\n'
        '  PERFORM 1 FROM public.products WHERE id=r.product_id AND tenant_id=r.tenant_id\n'
        '   AND category_id=r.category_id FOR UPDATE;\n'
        "  IF NOT FOUND THEN RAISE EXCEPTION 'Run source model unavailable' USING ERRCODE='23514'; END IF;\n"
        ' END IF;\n'
        " IF TG_OP='DELETE' THEN RETURN OLD; END IF;\n"
        ' IF NOT public.kernel_read_set_visible(r.tenant_id,r.category_id,reads)\n'
        " THEN RAISE EXCEPTION 'Run sources currently unreadable' USING ERRCODE='23514'; END IF;\n"
        ' FOR ref IN SELECT value FROM jsonb_array_elements(reads) LOOP\n'
        '  SELECT * INTO a FROM public.artifact_versions WHERE tenant_id=r.tenant_id\n'
        "   AND category_id=r.category_id AND id=(ref->>'artifact_id')::uuid\n"
        "   AND revision=(ref->>'expected_revision')::integer AND status='active'\n"
        '   AND (r.product_id IS NULL OR product_id IS NULL OR product_id=r.product_id)\n'
        "   AND product_id IS NOT DISTINCT FROM (ref->>'product_id')::uuid;\n"
        "  IF NOT FOUND THEN RAISE EXCEPTION 'Run requires exact actual source' USING ERRCODE='23514'; END IF;\n"
        "  IF ref ? 'content_hash' AND a.content_hash IS DISTINCT FROM ref->>'content_hash'\n"
        "  THEN RAISE EXCEPTION 'Native project source hash changed' USING ERRCODE='23514'; END IF;\n"
        '  links=array_append(links,a.id);\n'
        '  IF a.original_id IS NOT NULL THEN links=array_append(links,a.original_id); END IF;\n'
        ' END LOOP;\n'
        ' IF EXISTS(SELECT 1 FROM public.lifecycle_objects o\n'
        '  WHERE o.tenant_id=r.tenant_id AND o.category_id=r.category_id AND o.id=ANY(links)\n'
        "   AND (o.state->'value'->>'pending_intent_id' IS NOT NULL\n"
        "    OR o.state->'value'->>'disposition' IN ('quarantined','unknown','purged')))\n"
        " THEN RAISE EXCEPTION 'Pending original prohibits Run source binding'\n"
        "  USING ERRCODE='23514',CONSTRAINT='category_source_reference_fence'; END IF;\n"
        ' RETURN NEW;\n'
        'END $function$\n'
    ),
    'kernel_source_reference_clock()': (
        'CREATE OR REPLACE FUNCTION public.kernel_source_reference_clock()\n'
        ' RETURNS trigger\n'
        ' LANGUAGE plpgsql\n'
        ' SECURITY DEFINER\n'
        " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
        'AS $function$\n'
        'DECLARE r agent_runs;\n'
        'BEGIN\n'
        " IF TG_OP='DELETE' THEN r=OLD; ELSE r=NEW; END IF;\n"
        ' IF r.category_id IS NOT NULL AND jsonb_array_length(r.read_sources\n'
        "  ||coalesce(r.versions#>'{project_current_context,source_proof}','[]'::jsonb))>0 THEN\n"
        '  UPDATE public.categories SET lifecycle_epoch=lifecycle_epoch+1\n'
        '   WHERE tenant_id=r.tenant_id AND id=r.category_id;\n'
        '  IF r.product_id IS NOT NULL THEN\n'
        '   UPDATE public.products SET lifecycle_epoch=lifecycle_epoch+1\n'
        '    WHERE tenant_id=r.tenant_id AND id=r.product_id;\n'
        '  END IF;\n'
        ' END IF;\n'
        " -- P91: a personal Run's pinned sources advance each source scope's lifecycle clock.\n"
        ' IF r.category_id IS NULL AND jsonb_array_length(r.read_sources)>0 THEN\n'
        '  UPDATE public.categories SET lifecycle_epoch=lifecycle_epoch+1\n'
        "   WHERE tenant_id=r.tenant_id AND id IN (SELECT (value->>'category_id')::uuid\n"
        "    FROM jsonb_array_elements(coalesce(r.versions->'personal_sources','[]'::jsonb)));\n"
        '  UPDATE public.products SET lifecycle_epoch=lifecycle_epoch+1\n'
        "   WHERE tenant_id=r.tenant_id AND id IN (SELECT (value->>'product_id')::uuid\n"
        "    FROM jsonb_array_elements(coalesce(r.versions->'personal_sources','[]'::jsonb)));\n"
        ' END IF;\n'
        " IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n"
        'END $function$\n'
    ),
}

SCHEMA_SQL = tuple(PERSONAL_FUNCTIONS.values())
DOWNGRADE_SQL = tuple(PREVIOUS_FUNCTIONS.values())
EMPTY_HISTORY_SQL = (
    "LOCK TABLE public.agent_runs IN SHARE ROW EXCLUSIVE MODE",
    (
        "DO $personal_history$\nBEGIN\n IF EXISTS(SELECT 1 FROM public.agent_runs r\n"
        "  WHERE r.category_id IS NULL AND jsonb_array_length(r.read_sources)>0) THEN\n"
        "  RAISE EXCEPTION 'Personal Run source history requires its retention closure'\n"
        "   USING ERRCODE='23514',CONSTRAINT='personal_run_source_history_retained';\n"
        " END IF;\nEND $personal_history$;\n"
    ),
)
