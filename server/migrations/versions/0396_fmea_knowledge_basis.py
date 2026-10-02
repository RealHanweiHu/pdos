"""Bind design-rule knowledge to published FMEA and its live evidence dependencies."""

from importlib import import_module

from alembic import op

revision = "0396_fmea_knowledge_basis"
down_revision = "0395_xiaopai_delegations"
branch_labels = None
depends_on = None

previous = import_module("migrations.versions.0353_quality_learning")

FUNCTIONS = r"""
CREATE FUNCTION cehub_memory.fmea_knowledge_source(t uuid,p uuid,k text,identity text)
RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path=pg_catalog SET timezone='UTC' AS $$
DECLARE relation text; result jsonb; root jsonb; review jsonb; ref jsonb; evidence jsonb;
BEGIN
 relation := CASE k
  WHEN 'specification' THEN 'cehub_product.specifications'
  WHEN 'bom_item' THEN 'cehub_product.development_bom_items'
  WHEN 'test_case' THEN 'cehub_quality.test_cases'
  WHEN 'test_run' THEN 'cehub_quality.test_runs'
  WHEN 'issue' THEN 'cehub_project.issues'
  WHEN 'ncr' THEN 'cehub_quality.nonconformance_reports'
  WHEN 'capa_action' THEN 'cehub_quality.capa_actions'
  WHEN 'document' THEN 'cehub_project.documents'
  WHEN 'decision' THEN 'cehub_project.decisions' END;
 IF k='requirement' THEN
  SELECT to_jsonb(r) INTO result FROM cehub_project.requirements r
   WHERE r.tenant_id=t AND r.id::text=identity AND EXISTS(
    SELECT 1 FROM cehub_product.specifications s
    WHERE s.tenant_id=t AND s.project_id=p AND s.requirement_id=r.id);
 ELSIF k='evidence_snapshot' THEN
  SELECT to_jsonb(e) INTO result FROM cehub_evidence.evidence_snapshots e
   WHERE e.tenant_id=t AND e.id::text=identity AND e.superseded_by_id IS NULL
    AND e.conflicts_with_id IS NULL
    AND (e.freshness_expires_at IS NULL OR e.freshness_expires_at>CURRENT_TIMESTAMP)
    AND (e.source_id IS NULL OR EXISTS(SELECT 1 FROM cehub_evidence.research_sources s
     WHERE s.tenant_id=t AND s.id=e.source_id AND s.status='active'))
    AND EXISTS(SELECT 1 FROM cehub_evidence.evidence_contents ec
     WHERE ec.tenant_id=t AND ec.content_digest=e.content_digest);
 ELSIF k='event' THEN
  SELECT to_jsonb(e) INTO result FROM cehub_event.events e
   WHERE e.tenant_id=t AND e.project_id=p AND e.event_id=identity ORDER BY e.id LIMIT 1;
 ELSIF relation IS NOT NULL THEN
  EXECUTE 'SELECT to_jsonb(r) FROM ' || relation ||
   ' r WHERE r.tenant_id=$1 AND r.project_id=$2 AND r.id::text=$3'
   INTO result USING t,p,identity;
 ELSE RETURN NULL;
 END IF;
 IF result IS NULL THEN RETURN NULL; END IF;
 IF k='issue' AND result->>'withdrawn_at' IS NOT NULL THEN RETURN NULL; END IF;
 IF k='test_run' AND (result->>'draft_state'<>'confirmed'
   OR result->>'status' NOT IN ('passed','failed','aborted')) THEN RETURN NULL; END IF;
 IF k='capa_action' THEN
  evidence := cehub_memory.fmea_knowledge_source(t,p,'ncr',result->>'ncr_id');
  IF evidence IS NULL THEN RETURN NULL; END IF;
  result := result || jsonb_build_object('ncr',evidence);
 END IF;
 IF k='ncr' THEN
  SELECT to_jsonb(r) INTO root FROM cehub_quality.root_cause_analyses r
   WHERE r.tenant_id=t AND r.project_id=p AND r.ncr_id::text=identity AND r.status='approved'
   ORDER BY r.version DESC LIMIT 1;
  SELECT to_jsonb(r) INTO review FROM cehub_quality.effectiveness_reviews r
   WHERE r.tenant_id=t AND r.project_id=p AND r.ncr_id::text=identity
   ORDER BY r.review_number DESC LIMIT 1;
  result := result || jsonb_build_object(
   'approved_root_cause',root,'latest_effectiveness_review',review);
 END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(
   coalesce(result->'evidence_refs','[]'::jsonb) || coalesce(root->'evidence_refs','[]'::jsonb)
   || coalesce(review->'evidence_refs','[]'::jsonb)) LOOP
  -- Quality evidence cannot recursively name another NCR or action.
  IF ref->>'kind' NOT IN ('document','test_run','event','decision','evidence_snapshot')
   THEN RETURN NULL; END IF;
  evidence := cehub_memory.fmea_knowledge_source(t,p,ref->>'kind',ref->>'reference');
  IF evidence IS NULL THEN RETURN NULL; END IF;
  result := jsonb_set(result,'{resolved_evidence}',
    coalesce(result->'resolved_evidence','[]'::jsonb) || jsonb_build_array(evidence));
 END LOOP;
 RETURN result;
END $$;

CREATE FUNCTION cehub_memory.fmea_knowledge_basis(t uuid,p uuid,v uuid) RETURNS text
LANGUAGE plpgsql STABLE SET search_path=pg_catalog SET timezone='UTC' AS $$
DECLARE refs jsonb; ref jsonb; value jsonb; basis jsonb := '[]'::jsonb;
BEGIN
 SELECT sources INTO refs FROM cehub_quality.fmea_versions
  WHERE tenant_id=t AND project_id=p AND id=v;
 IF refs IS NULL OR jsonb_array_length(refs)=0 THEN RETURN NULL; END IF;
 FOR ref IN SELECT r FROM jsonb_array_elements(refs) r ORDER BY r->>'kind',r->>'id' LOOP
  value := cehub_memory.fmea_knowledge_source(t,p,ref->>'kind',ref->>'id');
  IF value IS NULL THEN RETURN NULL; END IF;
  basis := basis || jsonb_build_array(jsonb_build_object(
   'kind',ref->>'kind','id',ref->>'id','value',value));
 END LOOP;
 RETURN md5(basis::text);
END $$;
"""

BRANCH = """
    WHEN r.ref->>'kind'='fmea_publication' THEN coalesce((SELECT CASE
     WHEN r.ref->>'basis' IS NULL THEN 'needs_review'
     WHEN v.version::text IS DISTINCT FROM r.ref->>'version'
      OR EXISTS(SELECT 1 FROM cehub_quality.fmea_publications later
       JOIN cehub_quality.fmea_versions lv
        ON lv.id=later.version_id AND lv.tenant_id=later.tenant_id
       WHERE later.tenant_id=m.tenant_id AND later.project_id=m.project_id
        AND later.entry_id=pub.entry_id AND lv.version>v.version)
      OR cehub_memory.fmea_knowledge_basis(m.tenant_id,m.project_id,v.id)
         IS DISTINCT FROM r.ref->>'basis' THEN 'stale'
     ELSE 'current' END
     FROM cehub_quality.fmea_publications pub
     JOIN cehub_quality.fmea_versions v ON v.id=pub.version_id AND v.tenant_id=pub.tenant_id
     WHERE pub.tenant_id=m.tenant_id AND pub.project_id=m.project_id
      AND pub.id::text=r.ref->>'reference'),'unavailable')
"""
VIEW = previous.NEW_VIEW.replace(
    "    WHEN r.ref->>'kind'='root_cause'", BRANCH + "    WHEN r.ref->>'kind'='root_cause'", 1
)


def upgrade() -> None:
    op.execute(FUNCTIONS)
    op.execute(VIEW)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS(
     SELECT 1 FROM cehub_memory.memories m,jsonb_array_elements(m.source_refs) r
     WHERE r->>'kind'='fmea_publication') THEN
     RAISE EXCEPTION 'Retain FMEA knowledge source history'; END IF; END $$;""")
    op.execute(previous.NEW_VIEW)
    op.execute("DROP FUNCTION cehub_memory.fmea_knowledge_basis(uuid,uuid,uuid)")
    op.execute("DROP FUNCTION cehub_memory.fmea_knowledge_source(uuid,uuid,text,text)")
