# ruff: noqa: E501
"""Frozen signed Reference closure for nested M3 Claim consumption."""

REFERENCE_GRAPH = """CREATE FUNCTION public.m3_reference_graph(t uuid, c uuid, seeds jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE queue jsonb;
 refs jsonb='[]'; cursor_index integer=0; node jsonb; ref jsonb; path jsonb; token text; children jsonb;
BEGIN
 IF jsonb_typeof(seeds) IS DISTINCT FROM 'array' THEN RETURN NULL; END IF;
 SELECT coalesce(jsonb_agg(jsonb_build_object('ref',seed,'path','[]'::jsonb)),'[]')
  INTO queue FROM jsonb_array_elements(seeds) seed;
 WHILE cursor_index<jsonb_array_length(queue) LOOP
  node=queue->cursor_index; cursor_index=cursor_index+1; ref=node->'ref'; path=node->'path';
  IF jsonb_typeof(ref) IS DISTINCT FROM 'object'
   OR coalesce(ref->>'type','')<>ALL(ARRAY['artifact','original','snapshot','claim','knowledge','definition','parameter','human'])
   OR jsonb_typeof(ref->'id') IS DISTINCT FROM 'string'
   OR jsonb_typeof(ref->'version') IS DISTINCT FROM 'number'
   OR (ref->>'version')::integer<1 THEN RETURN NULL; END IF;
  token=(ref->>'type')||':'||(ref->>'id')||':'||(ref->>'version');
  IF token IS NULL OR path ? token THEN RETURN NULL; END IF;
  refs=refs||jsonb_build_array(ref); path=path||jsonb_build_array(token); children='[]';
  IF ref->>'type'='definition' THEN
   IF NOT EXISTS(SELECT 1 FROM definition_revisions d WHERE d.tenant_id=t AND d.category_id=c
    AND d.id=(ref->>'id')::uuid AND d.revision=(ref->>'version')::integer) THEN RETURN NULL; END IF;
   SELECT coalesce(jsonb_agg(source),'[]') INTO children FROM (
    SELECT jsonb_build_object('type','artifact','id',s.artifact_id,'version',s.source_revision,'line',s.line,'quote',s.quote) source
     FROM definition_sources s WHERE s.tenant_id=t AND s.category_id=c AND s.definition_id=(ref->>'id')::uuid
    UNION ALL SELECT item FROM definition_specs spec CROSS JOIN LATERAL jsonb_array_elements(spec.source_refs) item
     WHERE spec.tenant_id=t AND spec.category_id=c AND spec.definition_id=(ref->>'id')::uuid
    UNION ALL SELECT jsonb_build_object('type','definition','id',d.derived_from_definition_id,'version',d.derived_from_definition_revision)
     FROM definition_revisions d WHERE d.tenant_id=t AND d.category_id=c AND d.id=(ref->>'id')::uuid AND d.derived_from_definition_id IS NOT NULL
    UNION ALL SELECT jsonb_build_object('type','definition','id',parent.id,'version',parent.revision)
     FROM definition_revisions d JOIN definition_revisions parent ON parent.tenant_id=d.tenant_id AND parent.category_id=d.category_id AND parent.id=d.parent_definition_id
     WHERE d.tenant_id=t AND d.category_id=c AND d.id=(ref->>'id')::uuid
   ) edges;
  ELSIF ref->>'type'='knowledge' THEN
   IF NOT EXISTS(SELECT 1 FROM category_knowledge_entries knowledge
    WHERE knowledge.tenant_id=t AND knowledge.category_id=c AND knowledge.id=(ref->>'id')::uuid
     AND knowledge.version=(ref->>'version')::integer) THEN RETURN NULL; END IF;
   -- Mirror category_service._references, never arbitrary nested dictionaries.
   SELECT coalesce(jsonb_agg(edge),'[]') INTO children FROM category_knowledge_entries knowledge
    CROSS JOIN LATERAL (
     SELECT item AS edge FROM jsonb_array_elements(knowledge.source_refs) item
     UNION ALL SELECT item FROM jsonb_array_elements(CASE WHEN knowledge.kind='voice'
      THEN coalesce(knowledge.content->'representative_refs','[]') ELSE '[]'::jsonb END) item
     UNION ALL SELECT item->'source_ref' FROM jsonb_array_elements(CASE WHEN knowledge.kind='competitor'
      THEN coalesce(knowledge.content->'metrics','[]') || coalesce(knowledge.content->'features','[]')
       || coalesce(knowledge.content->'prices','[]') ELSE '[]'::jsonb END) item
      WHERE item->'source_ref' IS NOT NULL AND item->'source_ref'<>'null'::jsonb
    ) registered
    WHERE knowledge.tenant_id=t AND knowledge.category_id=c AND knowledge.id=(ref->>'id')::uuid
     AND knowledge.version=(ref->>'version')::integer;
  ELSIF ref->>'type'='claim' THEN
   SELECT coalesce(jsonb_agg(jsonb_build_object('type',claim.source_kind,'id',coalesce(claim.artifact_id,claim.snapshot_id),
    'version',claim.source_revision,'line',claim.line,'quote',claim.quote)),'[]') INTO children
    FROM claims claim WHERE claim.tenant_id=t AND claim.category_id=c AND claim.id=(ref->>'id')::uuid;
  END IF;
  SELECT queue||coalesce(jsonb_agg(jsonb_build_object('ref',child,'path',path)),'[]') INTO queue FROM jsonb_array_elements(children) child;
 END LOOP;
 RETURN (SELECT coalesce(jsonb_agg(DISTINCT item ORDER BY item),'[]') FROM jsonb_array_elements(refs) item);
EXCEPTION WHEN invalid_text_representation OR invalid_parameter_value OR numeric_value_out_of_range THEN RETURN NULL;
END $function$
"""

BASELINE_GRAPH = """CREATE OR REPLACE FUNCTION public.m3_baseline_reference_graph(t uuid, c uuid, did uuid, ver integer)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
BEGIN
 RETURN public.m3_reference_graph(t,c,jsonb_build_array(
  jsonb_build_object('type','definition','id',did,'version',ver)));
END $function$
"""

CONSUMPTION_ATOM = """CREATE OR REPLACE FUNCTION public.m3_evidence_consumption_atom()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE k claims; d proposal_decisions; def definition_revisions; r action_receipts; sub proposal_submissions; refs jsonb;
BEGIN
 -- Old S0 consumption records keep their product-scoped semantics; new M3 rows
 -- carry a real decision/definition and exact Claim version.
 IF NEW.decision_id IS NULL AND NEW.definition_id IS NULL THEN
  IF NEW.product_id IS NULL OR NEW.consumer_type IN ('proposal_decision','g0_decision','definition','definition_revision') THEN
   RAISE EXCEPTION 'named consumption needs actual decision' USING ERRCODE='23514'; END IF;
  RETURN NULL;
 END IF;
 SELECT * INTO STRICT k FROM claims WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.claim_id FOR UPDATE;
 SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;
 IF NEW.claim_version IS DISTINCT FROM k.revision OR k.status<>'active' OR r.category_id<>NEW.category_id
  OR r.operation<>'proposal.g0.decide' OR r.actor_id<>r.requester_id OR r.agent_run_id IS NOT NULL
  OR (SELECT xmin FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=r.id) IS DISTINCT FROM
     (SELECT xmin FROM claim_consumptions WHERE tenant_id=NEW.tenant_id AND id=NEW.id) THEN
  RAISE EXCEPTION 'signed claim consumption receipt mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.decision_id IS NOT NULL THEN
  SELECT * INTO STRICT d FROM proposal_decisions WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.decision_id;
 ELSE
  SELECT * INTO STRICT def FROM definition_revisions WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.definition_id;
  SELECT * INTO STRICT d FROM proposal_decisions WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=def.g0_decision_id;
 END IF;
 SELECT * INTO STRICT sub FROM proposal_submissions WHERE tenant_id=NEW.tenant_id AND id=d.submission_id;
 IF d.outcome IS DISTINCT FROM 'approved' OR d.receipt_id IS DISTINCT FROM r.id OR d.decided_by<>r.actor_id OR d.review_digest IS DISTINCT FROM sub.document_digest
  OR r.subject_type<>'proposal' OR r.subject_id<>d.proposal_id THEN
  RAISE EXCEPTION 'consumption signer mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.definition_id IS NOT NULL THEN
  SELECT * INTO STRICT def FROM definition_revisions WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.definition_id;
  IF NOT def.sealed OR def.g0_decision_id IS DISTINCT FROM d.id OR d.outcome<>'approved'
   OR def.product_id IS DISTINCT FROM NEW.product_id THEN
   RAISE EXCEPTION 'consumption definition mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF NEW.consumer_id NOT IN (d.id,coalesce(NEW.definition_id,d.id)) THEN
  RAISE EXCEPTION 'consumption target mismatch' USING ERRCODE='23514'; END IF;
 -- The queue is derived only from this already-verified immutable submission.
 -- Callers cannot supply seeds or substitute another candidate's source tree.
 SELECT public.m3_reference_graph(NEW.tenant_id,NEW.category_id,
  coalesce(jsonb_agg(ref),'[]')) INTO refs FROM (
  SELECT ref FROM jsonb_array_elements(coalesce(sub.frozen_document->'source_refs','[]'::jsonb)) ref
  UNION ALL SELECT ref FROM jsonb_array_elements(coalesce(sub.frozen_document->'context_refs','[]'::jsonb)) ref
  UNION ALL SELECT ref FROM jsonb_array_elements(coalesce(sub.frozen_document->'baseline_claim_refs','[]'::jsonb)) ref
  UNION ALL SELECT ref FROM jsonb_array_elements(coalesce(sub.frozen_document->'items','[]'::jsonb)) item
   CROSS JOIN LATERAL jsonb_array_elements(coalesce(item->'source_refs','[]'::jsonb)) ref
 ) signed;
 IF refs IS NULL OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(refs) ref
  WHERE ref->>'type'='claim' AND (ref->>'id')::uuid=k.id
   AND (ref->>'version')::integer=NEW.claim_version) THEN
  RAISE EXCEPTION 'claim absent from signed document' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $function$
"""

PREDECESSOR_BASELINE_GRAPH = """CREATE OR REPLACE FUNCTION public.m3_baseline_reference_graph(t uuid, c uuid, did uuid, ver integer)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE queue jsonb=jsonb_build_array(jsonb_build_object('ref',jsonb_build_object('type','definition','id',did,'version',ver),'path','[]'::jsonb));
 refs jsonb='[]'; cursor_index integer=0; node jsonb; ref jsonb; path jsonb; token text; children jsonb;
BEGIN
 WHILE cursor_index<jsonb_array_length(queue) LOOP
  node=queue->cursor_index; cursor_index=cursor_index+1; ref=node->'ref'; path=node->'path';
  token=(ref->>'type')||':'||(ref->>'id')||':'||(ref->>'version');
  IF token IS NULL OR path ? token THEN RETURN NULL; END IF;
  refs=refs||jsonb_build_array(ref); path=path||jsonb_build_array(token); children='[]';
  IF ref->>'type'='definition' THEN
   SELECT coalesce(jsonb_agg(source),'[]') INTO children FROM (
    SELECT jsonb_build_object('type','artifact','id',s.artifact_id,'version',s.source_revision,'line',s.line,'quote',s.quote) source
     FROM definition_sources s WHERE s.tenant_id=t AND s.category_id=c AND s.definition_id=(ref->>'id')::uuid
    UNION ALL SELECT item FROM definition_specs spec CROSS JOIN LATERAL jsonb_array_elements(spec.source_refs) item
     WHERE spec.tenant_id=t AND spec.category_id=c AND spec.definition_id=(ref->>'id')::uuid
    UNION ALL SELECT jsonb_build_object('type','definition','id',d.derived_from_definition_id,'version',d.derived_from_definition_revision)
     FROM definition_revisions d WHERE d.tenant_id=t AND d.category_id=c AND d.id=(ref->>'id')::uuid AND d.derived_from_definition_id IS NOT NULL
    UNION ALL SELECT jsonb_build_object('type','definition','id',parent.id,'version',parent.revision)
     FROM definition_revisions d JOIN definition_revisions parent ON parent.tenant_id=d.tenant_id AND parent.category_id=d.category_id AND parent.id=d.parent_definition_id
     WHERE d.tenant_id=t AND d.category_id=c AND d.id=(ref->>'id')::uuid
   ) edges;
  ELSIF ref->>'type'='knowledge' THEN
   SELECT coalesce(jsonb_agg(item),'[]') INTO children FROM category_knowledge_entries knowledge
    CROSS JOIN LATERAL jsonb_array_elements(knowledge.source_refs) item
    WHERE knowledge.tenant_id=t AND knowledge.category_id=c AND knowledge.id=(ref->>'id')::uuid;
  ELSIF ref->>'type'='claim' THEN
   SELECT coalesce(jsonb_agg(jsonb_build_object('type',claim.source_kind,'id',coalesce(claim.artifact_id,claim.snapshot_id),
    'version',claim.source_revision,'line',claim.line,'quote',claim.quote)),'[]') INTO children
    FROM claims claim WHERE claim.tenant_id=t AND claim.category_id=c AND claim.id=(ref->>'id')::uuid;
  END IF;
  SELECT queue||coalesce(jsonb_agg(jsonb_build_object('ref',child,'path',path)),'[]') INTO queue FROM jsonb_array_elements(children) child;
 END LOOP;
 RETURN (SELECT coalesce(jsonb_agg(DISTINCT item ORDER BY item),'[]') FROM jsonb_array_elements(refs) item);
EXCEPTION WHEN invalid_text_representation OR invalid_parameter_value THEN RETURN NULL;
END $function$
"""

PREDECESSOR_CONSUMPTION_ATOM = """CREATE OR REPLACE FUNCTION public.m3_evidence_consumption_atom()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE k claims; d proposal_decisions; def definition_revisions; r action_receipts; sub proposal_submissions; refs jsonb;
BEGIN
 -- Old S0 consumption records keep their product-scoped semantics; new M3 rows
 -- carry a real decision/definition and exact Claim version.
 IF NEW.decision_id IS NULL AND NEW.definition_id IS NULL THEN
  IF NEW.product_id IS NULL OR NEW.consumer_type IN ('proposal_decision','g0_decision','definition','definition_revision') THEN
   RAISE EXCEPTION 'named consumption needs actual decision' USING ERRCODE='23514'; END IF;
  RETURN NULL;
 END IF;
 SELECT * INTO STRICT k FROM claims WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.claim_id FOR UPDATE;
 SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;
 IF NEW.claim_version IS DISTINCT FROM k.revision OR k.status<>'active' OR r.category_id<>NEW.category_id
  OR r.operation<>'proposal.g0.decide' OR r.actor_id<>r.requester_id OR r.agent_run_id IS NOT NULL
  OR (SELECT xmin FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=r.id) IS DISTINCT FROM
     (SELECT xmin FROM claim_consumptions WHERE tenant_id=NEW.tenant_id AND id=NEW.id) THEN
  RAISE EXCEPTION 'signed claim consumption receipt mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.decision_id IS NOT NULL THEN
  SELECT * INTO STRICT d FROM proposal_decisions WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.decision_id;
 ELSE
  SELECT * INTO STRICT def FROM definition_revisions WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.definition_id;
  SELECT * INTO STRICT d FROM proposal_decisions WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=def.g0_decision_id;
 END IF;
 SELECT * INTO STRICT sub FROM proposal_submissions WHERE tenant_id=NEW.tenant_id AND id=d.submission_id;
 IF d.outcome IS DISTINCT FROM 'approved' OR d.receipt_id IS DISTINCT FROM r.id OR d.decided_by<>r.actor_id OR d.review_digest IS DISTINCT FROM sub.document_digest
  OR r.subject_type<>'proposal' OR r.subject_id<>d.proposal_id THEN
  RAISE EXCEPTION 'consumption signer mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.definition_id IS NOT NULL THEN
  SELECT * INTO STRICT def FROM definition_revisions WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.definition_id;
  IF NOT def.sealed OR def.g0_decision_id IS DISTINCT FROM d.id OR d.outcome<>'approved'
   OR def.product_id IS DISTINCT FROM NEW.product_id THEN
   RAISE EXCEPTION 'consumption definition mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF NEW.consumer_id NOT IN (d.id,coalesce(NEW.definition_id,d.id)) THEN
  RAISE EXCEPTION 'consumption target mismatch' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT 1 FROM (
  SELECT ref FROM jsonb_array_elements(coalesce(sub.frozen_document->'source_refs','[]'::jsonb)) ref
  UNION ALL SELECT ref FROM jsonb_array_elements(coalesce(sub.frozen_document->'context_refs','[]'::jsonb)) ref
  UNION ALL SELECT ref FROM jsonb_array_elements(coalesce(sub.frozen_document->'items','[]'::jsonb)) item
   CROSS JOIN LATERAL jsonb_array_elements(coalesce(item->'source_refs','[]'::jsonb)) ref
 ) x WHERE ref->>'type'='claim' AND (ref->>'id')::uuid=k.id AND (ref->>'version')::integer=NEW.claim_version) THEN
  RAISE EXCEPTION 'claim absent from signed document' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $function$
"""

SCHEMA_SQL = (
    REFERENCE_GRAPH,
    BASELINE_GRAPH,
    CONSUMPTION_ATOM,
    "REVOKE ALL ON FUNCTION public.m3_reference_graph(uuid,uuid,jsonb) FROM PUBLIC,pdos_next_app,pdos_next_auth,pdos_next_dispatch,pdos_agent",
)

DOWNGRADE_SQL = (
    PREDECESSOR_CONSUMPTION_ATOM,
    PREDECESSOR_BASELINE_GRAPH,
    "DROP FUNCTION public.m3_reference_graph(uuid,uuid,jsonb)",
)
