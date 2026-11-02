# ruff: noqa: E501
"""Inherit only actual sealed signed G0 Product sources in downstream read sets.

The private proof retains current source audiences. Expected revisions match the
stored signed citation, while the existing historical-read behavior is retained:
current-source eligibility remains the responsibility of new-consumption guards.
CREATE OR REPLACE preserves the predecessor owner and exact runtime ACL.
"""

DIRECT_SOURCE_SET_VISIBLE = """CREATE OR REPLACE FUNCTION public.direct_source_set_visible(t uuid, c uuid, p uuid, refs jsonb)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
 SELECT category_access(t,c,false) AND jsonb_typeof(refs)='array' AND NOT EXISTS (
   SELECT 1 FROM jsonb_array_elements(refs) r
   LEFT JOIN artifact_versions a ON a.id=(r->>'artifact_id')::uuid
     AND a.tenant_id=t AND a.category_id=c AND (a.product_id IS NULL OR a.product_id=p OR EXISTS (
       SELECT 1 FROM public.definition_sources source
       JOIN public.definition_revisions definition ON definition.id=source.definition_id
         AND definition.tenant_id=source.tenant_id AND definition.category_id=source.category_id
         AND definition.product_id=source.product_id
       WHERE source.tenant_id=t AND source.category_id=c AND source.product_id=p
         AND source.artifact_id=a.id AND definition.sealed IS TRUE
         AND definition.g0_decision_id IS NOT NULL
         AND (NOT (r ? 'expected_revision') OR to_jsonb(source.source_revision)=r->'expected_revision')
         AND public.m3_g0_product_source_proven(t,c,p,definition.id,a.id,
           source.source_revision,source.line,source.quote,false) IS TRUE
     ))
   LEFT JOIN products m ON m.id=a.product_id AND m.tenant_id=t AND m.category_id=c
   LEFT JOIN uploaded_originals o ON o.id=a.original_id AND o.tenant_id=t AND o.category_id=c AND o.product_id IS NOT DISTINCT FROM a.product_id
   WHERE a.id IS NULL OR (a.product_id IS NOT NULL AND (m.id IS NULL
     OR NOT (m.visibility='category' OR m.owner_id=scope_requester() OR EXISTS (
       SELECT 1 FROM object_audiences aud
       WHERE aud.tenant_id=t AND aud.category_id=c AND aud.object_type='products'
         AND aud.subject_id=m.id AND aud.owner_id=m.owner_id AND aud.principal_id=scope_requester()
     ))))
     OR NOT (a.visibility='category' OR a.owner_id=scope_requester() OR EXISTS (
       SELECT 1 FROM object_audiences aud
       WHERE aud.tenant_id=t AND aud.category_id=c AND aud.object_type='artifact_versions'
         AND aud.subject_id=a.id AND aud.owner_id=a.owner_id AND aud.principal_id=scope_requester()
     ))
     OR (a.original_id IS NOT NULL AND (o.id IS NULL
       OR NOT (o.visibility='category' OR o.owner_id=scope_requester() OR EXISTS (
         SELECT 1 FROM object_audiences aud
         WHERE aud.tenant_id=t AND aud.category_id=c AND aud.object_type='uploaded_originals'
           AND aud.subject_id=o.id AND aud.owner_id=o.owner_id AND aud.principal_id=scope_requester()
       ))))
 )
$function$
"""

PREDECESSOR_DIRECT_SOURCE_SET_VISIBLE = """CREATE OR REPLACE FUNCTION public.direct_source_set_visible(t uuid, c uuid, p uuid, refs jsonb)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
 SELECT category_access(t,c,false) AND jsonb_typeof(refs)='array' AND NOT EXISTS (
   SELECT 1 FROM jsonb_array_elements(refs) r
   LEFT JOIN artifact_versions a ON a.id=(r->>'artifact_id')::uuid
     AND a.tenant_id=t AND a.category_id=c AND (a.product_id IS NULL OR a.product_id=p)
   LEFT JOIN products m ON m.id=a.product_id AND m.tenant_id=t AND m.category_id=c
   LEFT JOIN uploaded_originals o ON o.id=a.original_id AND o.tenant_id=t AND o.category_id=c AND o.product_id IS NOT DISTINCT FROM a.product_id
   WHERE a.id IS NULL OR (a.product_id IS NOT NULL AND (m.id IS NULL
     OR NOT (m.visibility='category' OR m.owner_id=scope_requester() OR EXISTS (
       SELECT 1 FROM object_audiences aud
       WHERE aud.tenant_id=t AND aud.category_id=c AND aud.object_type='products'
         AND aud.subject_id=m.id AND aud.owner_id=m.owner_id AND aud.principal_id=scope_requester()
     ))))
     OR NOT (a.visibility='category' OR a.owner_id=scope_requester() OR EXISTS (
       SELECT 1 FROM object_audiences aud
       WHERE aud.tenant_id=t AND aud.category_id=c AND aud.object_type='artifact_versions'
         AND aud.subject_id=a.id AND aud.owner_id=a.owner_id AND aud.principal_id=scope_requester()
     ))
     OR (a.original_id IS NOT NULL AND (o.id IS NULL
       OR NOT (o.visibility='category' OR o.owner_id=scope_requester() OR EXISTS (
         SELECT 1 FROM object_audiences aud
         WHERE aud.tenant_id=t AND aud.category_id=c AND aud.object_type='uploaded_originals'
           AND aud.subject_id=o.id AND aud.owner_id=o.owner_id AND aud.principal_id=scope_requester()
       ))))
 )
$function$
"""

SCHEMA_SQL = (DIRECT_SOURCE_SET_VISIBLE,)
DOWNGRADE_SQL = (PREDECESSOR_DIRECT_SOURCE_SET_VISIBLE,)
