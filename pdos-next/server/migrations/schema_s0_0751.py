# ruff: noqa: E501
"""Exact signed G0 citations for cross-product DefinitionSource rows."""

G0_PRODUCT_SOURCE_PROVEN = """CREATE FUNCTION public.m3_g0_product_source_proven(t uuid,c uuid,p uuid,did uuid,sid uuid,
 ver integer,source_line integer,source_quote text,writing boolean)
RETURNS boolean LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path TO 'pg_catalog','public','pg_temp'
AS $function$
DECLARE definition definition_revisions; decision proposal_decisions; proposal proposals;
 submission proposal_submissions; receipt action_receipts; artifact artifact_versions;
 current_result boolean=false; header_xid xid; decision_xid xid;
BEGIN
 IF category_access(t,c) IS DISTINCT FROM true THEN RETURN false; END IF;
 SELECT * INTO definition FROM definition_revisions WHERE tenant_id=t AND category_id=c AND id=did AND product_id=p;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT * INTO decision FROM proposal_decisions WHERE tenant_id=t AND category_id=c
  AND created_definition_id=did AND created_product_id=p AND outcome='approved';
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT * INTO proposal FROM proposals WHERE tenant_id=t AND category_id=c AND id=decision.proposal_id;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT * INTO submission FROM proposal_submissions WHERE tenant_id=t AND category_id=c AND id=decision.submission_id;
 IF NOT FOUND THEN RETURN false; END IF;
 IF submission.proposal_id IS DISTINCT FROM proposal.id OR submission.reviewer_id IS DISTINCT FROM decision.decided_by
  OR proposal.current_submission_id IS DISTINCT FROM submission.id
  OR decision.review_digest IS DISTINCT FROM submission.document_digest
  OR definition.owner_id IS DISTINCT FROM proposal.owner_id OR definition.visibility IS DISTINCT FROM proposal.effective_visibility
  OR definition.revision IS DISTINCT FROM 1 OR definition.variant_id IS DISTINCT FROM decision.created_variant_id
  OR decision.owner_id IS DISTINCT FROM proposal.owner_id THEN RETURN false; END IF;
 -- Only the actual immutable signed direct citation can enter DefinitionSource.
 IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(submission.frozen_document->'source_refs','[]')) ref
  WHERE ref->>'type' IN ('artifact','original') AND (ref->>'id')::uuid=sid
   AND (ref->>'version')::integer=ver AND (ref->>'line')::integer=source_line
   AND ref->>'quote'=source_quote) THEN RETURN false; END IF;
 SELECT * INTO artifact FROM artifact_versions WHERE tenant_id=t AND category_id=c AND id=sid;
 IF NOT FOUND OR artifact.product_id IS NULL OR artifact.product_id=p
  OR public.m3_evidence_source_reader(t,c,'artifact',sid) IS DISTINCT FROM true THEN RETURN false; END IF;
 SELECT xmin INTO header_xid FROM definition_revisions WHERE tenant_id=t AND category_id=c AND id=did;
 SELECT xmin INTO decision_xid FROM proposal_decisions WHERE tenant_id=t AND category_id=c AND id=decision.id;
 current_result=header_xid IS NOT DISTINCT FROM decision_xid
  AND public.m3_result_access(t,c,'definition_revisions',did) IS TRUE;
 IF writing THEN
  -- The BEFORE INSERT runs before the receipt and final seal; the existing
  -- deferred G0 atom validates that whole result transaction at commit.
  RETURN current_result AND definition.sealed IS FALSE AND definition.status='draft'
   AND artifact.status='active' AND artifact.revision=ver;
 END IF;
 -- SELECT/INSERT RETURNING can run between final sealing and append_receipt.
 IF current_result THEN RETURN artifact.status='active' AND artifact.revision=ver; END IF;
 IF definition.sealed IS DISTINCT FROM true OR definition.status NOT IN ('draft','published')
  OR definition.g0_decision_id IS DISTINCT FROM decision.id
  OR definition.source_proposal_id IS DISTINCT FROM proposal.id
  OR definition.source_submission_id IS DISTINCT FROM submission.id
  OR definition.source_proposal_revision IS DISTINCT FROM submission.revision THEN RETURN false; END IF;
 SELECT * INTO receipt FROM action_receipts WHERE tenant_id=t AND category_id=c AND id=decision.receipt_id;
 IF NOT FOUND OR receipt.operation IS DISTINCT FROM 'proposal.g0.decide'
  OR receipt.subject_type IS DISTINCT FROM 'proposal' OR receipt.subject_id IS DISTINCT FROM proposal.id
  OR receipt.actor_id IS DISTINCT FROM decision.decided_by OR receipt.requester_id IS DISTINCT FROM decision.decided_by
  OR receipt.agent_run_id IS NOT NULL OR receipt.run_id IS NOT NULL OR receipt.product_id IS NOT NULL
  OR receipt.result->>'decision_id' IS DISTINCT FROM decision.id::text
  OR receipt.result->>'definition_id' IS DISTINCT FROM definition.id::text
  OR receipt.result->>'product_id' IS DISTINCT FROM p::text THEN RETURN false; END IF;
 RETURN true;
EXCEPTION WHEN invalid_text_representation OR invalid_parameter_value OR numeric_value_out_of_range THEN RETURN false;
END $function$
"""

SOURCE_CONSUMER = """CREATE OR REPLACE FUNCTION public.assert_category_source_consumer()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM public.artifact_versions a
  WHERE a.tenant_id=NEW.tenant_id AND a.category_id=NEW.category_id
    AND a.id=NEW.artifact_id AND (a.product_id IS NULL OR a.product_id=NEW.product_id))
 THEN
  IF TG_TABLE_NAME='definition_sources' AND TG_OP='INSERT' THEN
   IF public.m3_g0_product_source_proven(NEW.tenant_id,NEW.category_id,NEW.product_id,NEW.definition_id,
    NEW.artifact_id,NEW.source_revision,NEW.line,NEW.quote,true) THEN RETURN NEW; END IF;
  END IF;
  RAISE EXCEPTION 'source consumer scope mismatch' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $function$
"""

SOURCE_VISIBLE = """CREATE OR REPLACE FUNCTION public.definition_sources_visible(t uuid, c uuid, p uuid, d uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
 SELECT category_access(t,c,false) AND NOT EXISTS(
  SELECT 1 FROM definition_sources source
  WHERE source.tenant_id=t AND source.category_id=c AND source.product_id=p AND source.definition_id=d
   AND public.direct_source_set_visible(t,c,p,jsonb_build_array(jsonb_build_object('artifact_id',source.artifact_id))) IS DISTINCT FROM true
   AND public.m3_g0_product_source_proven(t,c,p,d,source.artifact_id,source.source_revision,source.line,source.quote,false) IS DISTINCT FROM true)
 -- INSERT RETURNING can evaluate STABLE read policies before this statement's
 -- new header is visible. Preserve its prior source policy for that window;
 -- every stored header still requires the full actual recursive audience graph.
 AND (NOT EXISTS(SELECT 1 FROM definition_revisions definition WHERE definition.tenant_id=t AND definition.category_id=c
   AND definition.product_id=p AND definition.id=d)
  OR EXISTS(SELECT 1 FROM definition_revisions definition WHERE definition.tenant_id=t AND definition.category_id=c
   AND definition.product_id=p AND definition.id=d AND m3_definition_roots_visible(t,c,d,definition.revision)))
$function$
"""

SOURCE_READ_POLICY = """ALTER POLICY m3_category_source_read ON public.definition_sources USING (
 ((category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1
   FROM definition_revisions d
  WHERE ((d.tenant_id = definition_sources.tenant_id) AND (d.id = definition_sources.definition_id) AND (d.product_id = definition_sources.product_id)))) AND (EXISTS ( SELECT 1
   FROM artifact_versions a
  WHERE ((a.tenant_id = definition_sources.tenant_id) AND (a.category_id = definition_sources.category_id) AND (a.id = definition_sources.artifact_id) AND ((a.product_id IS NULL) OR (a.product_id = definition_sources.product_id))))))) OR
 (category_access(tenant_id,category_id) AND
  definition_sources_visible(tenant_id,category_id,product_id,definition_id))
)"""

PREDECESSOR_SOURCE_CONSUMER = """CREATE OR REPLACE FUNCTION public.assert_category_source_consumer()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM public.artifact_versions a
  WHERE a.tenant_id=NEW.tenant_id AND a.category_id=NEW.category_id
    AND a.id=NEW.artifact_id AND (a.product_id IS NULL OR a.product_id=NEW.product_id))
 THEN RAISE EXCEPTION 'source consumer scope mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $function$
"""

PREDECESSOR_SOURCE_VISIBLE = """CREATE OR REPLACE FUNCTION public.definition_sources_visible(t uuid, c uuid, p uuid, d uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
 SELECT direct_source_set_visible(t,c,p,COALESCE(
   (SELECT jsonb_agg(jsonb_build_object('artifact_id',artifact_id))
    FROM definition_sources WHERE tenant_id=t AND category_id=c AND product_id=p
      AND definition_id=d), '[]'::jsonb))
 -- INSERT RETURNING can evaluate STABLE read policies before this statement's
 -- new header is visible. Preserve its prior source policy for that window;
 -- every stored header still requires the full actual recursive audience graph.
 AND (NOT EXISTS(SELECT 1 FROM definition_revisions definition WHERE definition.tenant_id=t AND definition.category_id=c
   AND definition.product_id=p AND definition.id=d)
  OR EXISTS(SELECT 1 FROM definition_revisions definition WHERE definition.tenant_id=t AND definition.category_id=c
   AND definition.product_id=p AND definition.id=d AND m3_definition_roots_visible(t,c,d,definition.revision)))
$function$
"""

PREDECESSOR_SOURCE_READ_POLICY = """ALTER POLICY m3_category_source_read ON public.definition_sources USING ((category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1
   FROM definition_revisions d
  WHERE ((d.tenant_id = definition_sources.tenant_id) AND (d.id = definition_sources.definition_id) AND (d.product_id = definition_sources.product_id)))) AND (EXISTS ( SELECT 1
   FROM artifact_versions a
  WHERE ((a.tenant_id = definition_sources.tenant_id) AND (a.category_id = definition_sources.category_id) AND (a.id = definition_sources.artifact_id) AND ((a.product_id IS NULL) OR (a.product_id = definition_sources.product_id)))))))"""

SCHEMA_SQL = (
    G0_PRODUCT_SOURCE_PROVEN,
    SOURCE_CONSUMER,
    SOURCE_VISIBLE,
    SOURCE_READ_POLICY,
    "REVOKE ALL ON FUNCTION public.m3_g0_product_source_proven(uuid,uuid,uuid,uuid,uuid,integer,integer,text,boolean) FROM PUBLIC,pdos_next_app,pdos_next_auth,pdos_next_dispatch,pdos_agent",
)

DOWNGRADE_SQL = (
    PREDECESSOR_SOURCE_READ_POLICY,
    PREDECESSOR_SOURCE_VISIBLE,
    PREDECESSOR_SOURCE_CONSUMER,
    "DROP FUNCTION public.m3_g0_product_source_proven(uuid,uuid,uuid,uuid,uuid,integer,integer,text,boolean)",
)
