CREATE OR REPLACE FUNCTION public.kernel_source_reference_gate()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE r agent_runs; prior agent_runs; ref jsonb; a artifact_versions;
 links uuid[]='{}'; native jsonb; reads jsonb;
BEGIN
 IF TG_OP='DELETE' THEN r=OLD; ELSE r=NEW; END IF;
 native=coalesce(r.versions#>'{project_current_context,source_proof}','[]'::jsonb);
 IF TG_OP='UPDATE' THEN
  prior=OLD;
  IF ROW(r.tenant_id,r.category_id,r.product_id,r.read_sources,
     r.versions->'project_current_context') IS DISTINCT FROM
     ROW(prior.tenant_id,prior.category_id,prior.product_id,prior.read_sources,
     prior.versions->'project_current_context')
  THEN RAISE EXCEPTION 'Run source scope immutable' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF jsonb_typeof(native) IS DISTINCT FROM 'array'
 THEN RAISE EXCEPTION 'Native project footprint must be an array' USING ERRCODE='23514'; END IF;
 IF jsonb_typeof(r.read_sources) IS DISTINCT FROM 'array'
 THEN RAISE EXCEPTION 'Run source set must be an array' USING ERRCODE='23514'; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(native) LOOP
  IF jsonb_typeof(ref) IS DISTINCT FROM 'object'
   OR NOT(ref ?& ARRAY['artifact_id','expected_revision','product_id','content_hash'])
   OR ref->>'content_hash' IS NULL OR ref->>'content_hash' !~ '^[a-f0-9]{64}$' THEN
   RAISE EXCEPTION 'Native project source requires fixed metadata' USING ERRCODE='23514';
  END IF;
 END LOOP;
 reads=r.read_sources||native;
 IF jsonb_array_length(native)>0 AND (r.project_id IS NULL OR r.product_id IS NULL
  OR r.versions#>>'{project_current_context,kind}' IS DISTINCT FROM 'project-current-facts/v1'
  OR r.versions#>>'{project_current_context,tenant_id}' IS DISTINCT FROM r.tenant_id::text
  OR r.versions#>>'{project_current_context,category_id}' IS DISTINCT FROM r.category_id::text
  OR r.versions#>>'{project_current_context,product_id}' IS DISTINCT FROM r.product_id::text
  OR r.versions#>>'{project_current_context,project_id}' IS DISTINCT FROM r.project_id::text
  OR r.versions#>>'{project_current_context,requester_id}' IS DISTINCT FROM r.requester_id::text)
 THEN RAISE EXCEPTION 'Native project footprint requires its actual Run' USING ERRCODE='23514';
 END IF;
 IF r.category_id IS NULL THEN
  IF jsonb_array_length(reads)<>0
  THEN RAISE EXCEPTION 'Personal Run cannot consume business sources' USING ERRCODE='23514'; END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
 END IF;
 PERFORM 1 FROM public.categories WHERE id=r.category_id AND tenant_id=r.tenant_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Run source category unavailable' USING ERRCODE='23514'; END IF;
 IF r.product_id IS NOT NULL THEN
  PERFORM 1 FROM public.products WHERE id=r.product_id AND tenant_id=r.tenant_id
   AND category_id=r.category_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Run source model unavailable' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 IF NOT public.kernel_read_set_visible(r.tenant_id,r.category_id,reads)
 THEN RAISE EXCEPTION 'Run sources currently unreadable' USING ERRCODE='23514'; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(reads) LOOP
  SELECT * INTO a FROM public.artifact_versions WHERE tenant_id=r.tenant_id
   AND category_id=r.category_id AND id=(ref->>'artifact_id')::uuid
   AND revision=(ref->>'expected_revision')::integer AND status='active'
   AND (r.product_id IS NULL OR product_id IS NULL OR product_id=r.product_id)
   AND product_id IS NOT DISTINCT FROM (ref->>'product_id')::uuid;
  IF NOT FOUND THEN RAISE EXCEPTION 'Run requires exact actual source' USING ERRCODE='23514'; END IF;
  IF ref ? 'content_hash' AND a.content_hash IS DISTINCT FROM ref->>'content_hash'
  THEN RAISE EXCEPTION 'Native project source hash changed' USING ERRCODE='23514'; END IF;
  links=array_append(links,a.id);
  IF a.original_id IS NOT NULL THEN links=array_append(links,a.original_id); END IF;
 END LOOP;
 IF EXISTS(SELECT 1 FROM public.lifecycle_objects o
  WHERE o.tenant_id=r.tenant_id AND o.category_id=r.category_id AND o.id=ANY(links)
   AND (o.state->'value'->>'pending_intent_id' IS NOT NULL
    OR o.state->'value'->>'disposition' IN ('quarantined','unknown','purged')))
 THEN RAISE EXCEPTION 'Pending original prohibits Run source binding'
  USING ERRCODE='23514',CONSTRAINT='category_source_reference_fence'; END IF;
 RETURN NEW;
END $function$
