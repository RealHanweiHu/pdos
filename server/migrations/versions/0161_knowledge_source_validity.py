"""Recheck knowledge source freshness across human and agent retrieval."""

from alembic import op

revision = "0161_knowledge_source_validity"
down_revision = "0160_knowledge_corrections"
branch_labels = None
depends_on = None

ASSESSMENTS = r"""
CREATE VIEW cehub_memory.memory_source_assessments AS
WITH checks AS (
 SELECT m.tenant_id,m.project_id,m.id AS memory_id,m.status,
  coalesce(jsonb_agg(jsonb_build_object('kind',r.ref->>'kind','reference',r.ref->>'reference',
   'state', CASE
    WHEN r.ref IS NULL THEN 'manual'
    WHEN r.ref->>'kind'='event' THEN CASE WHEN EXISTS(
     SELECT 1 FROM cehub_event.events e WHERE e.tenant_id=m.tenant_id
      AND e.project_id=m.project_id AND e.event_id=r.ref->>'reference'
    ) THEN 'historical' ELSE 'unavailable' END
    WHEN r.ref->>'kind'='issue' THEN CASE WHEN EXISTS(
     SELECT 1 FROM cehub_project.issues i WHERE i.tenant_id=m.tenant_id
      AND i.project_id=m.project_id AND i.id::text=r.ref->>'reference' AND i.status='closed'
    ) THEN 'current' ELSE 'stale' END
    WHEN r.ref->>'kind'='ncr' THEN CASE WHEN EXISTS(
     SELECT 1 FROM cehub_quality.nonconformance_reports n WHERE n.tenant_id=m.tenant_id
      AND n.project_id=m.project_id AND n.id::text=r.ref->>'reference' AND n.status='closed'
    ) THEN 'current' ELSE 'stale' END
    WHEN r.ref->>'kind'='closure_evidence' THEN 'historical'
    WHEN r.ref->>'kind'='memory_correction' THEN CASE WHEN EXISTS(
     SELECT 1 FROM cehub_memory.knowledge_corrections c WHERE c.tenant_id=m.tenant_id
      AND c.project_id=m.project_id AND c.id::text=r.ref->>'correction_id'
      AND c.source_memory_id::text=r.ref->>'reference'
      AND c.source_content_sha256=r.ref->>'content_sha256' AND c.status='published'
    ) THEN 'historical' ELSE 'unavailable' END
    WHEN r.ref->>'kind'='evidence_snapshot' THEN coalesce((
     SELECT CASE
      WHEN e.content_digest IS DISTINCT FROM coalesce(r.ref->>'digest',r.ref->>'content_sha256')
       THEN 'needs_review'
      WHEN e.superseded_by_id IS NOT NULL OR e.conflicts_with_id IS NOT NULL
       OR (e.freshness_expires_at IS NOT NULL AND e.freshness_expires_at <= CURRENT_TIMESTAMP)
       OR (e.source_id IS NOT NULL AND s.status IS DISTINCT FROM 'active') THEN 'stale'
      WHEN NOT EXISTS(SELECT 1 FROM cehub_evidence.evidence_contents ec
        WHERE ec.tenant_id=e.tenant_id AND ec.content_digest=e.content_digest) THEN 'unavailable'
      ELSE 'current' END
     FROM cehub_evidence.evidence_snapshots e LEFT JOIN cehub_evidence.research_sources s
       ON s.tenant_id=e.tenant_id AND s.id=e.source_id
     WHERE e.tenant_id=m.tenant_id AND e.id::text=r.ref->>'reference'
    ),'unavailable')
    WHEN r.ref->>'kind'='document' THEN coalesce((SELECT CASE
     WHEN d.sha256=coalesce(r.ref->>'digest',r.ref->>'content_sha256') THEN 'current'
     ELSE 'needs_review' END FROM cehub_project.documents d
     WHERE d.tenant_id=m.tenant_id AND d.project_id=m.project_id
      AND d.id::text=r.ref->>'reference'),'unavailable')
    WHEN r.ref->>'kind'='specification' THEN coalesce((SELECT CASE
     WHEN s.version::text=r.ref->>'version' THEN 'current' ELSE 'stale' END
     FROM cehub_product.specifications s WHERE s.tenant_id=m.tenant_id
      AND s.project_id=m.project_id AND s.id::text=r.ref->>'reference'),'unavailable')
    ELSE 'needs_review' END
  )) FILTER (WHERE r.ref IS NOT NULL),'[]'::jsonb) AS sources
 FROM cehub_memory.memories m
 LEFT JOIN LATERAL jsonb_array_elements(m.source_refs) r(ref) ON true
 GROUP BY m.tenant_id,m.project_id,m.id,m.status
)
SELECT tenant_id,project_id,memory_id,sources,
 CASE WHEN status <> 'verified' THEN 'unverified'
 WHEN EXISTS(SELECT 1 FROM jsonb_array_elements(sources) s
  WHERE s->>'state' IN ('stale','unavailable'))
  THEN 'stale'
 WHEN EXISTS(SELECT 1 FROM jsonb_array_elements(sources) s WHERE s->>'state'='needs_review')
  THEN 'needs_review'
 WHEN jsonb_array_length(sources)=0 THEN 'manual'
 ELSE 'current' END AS state
FROM checks;

"""

AGENT_VIEW = r"""
CREATE OR REPLACE VIEW cehub_ai.agent_memory_projection
WITH (security_barrier = true)
AS
SELECT
    memory.id AS memory_id,
    memory.tenant_id,
    memory.project_id,
    memory.title,
    memory.content,
    memory.applicability,
    memory.tags,
    memory.source_refs,
    memory.content_sha256,
    embedding.provider,
    embedding.model,
    embedding.dimensions,
    embedding.embedding
FROM cehub_memory.memories AS memory
JOIN cehub_memory.memory_embeddings AS embedding
  ON embedding.tenant_id = memory.tenant_id
 AND embedding.project_id = memory.project_id
 AND embedding.memory_id = memory.id
 AND embedding.content_sha256 = memory.content_sha256
WHERE cehub_ai.agent_scope_allows(memory.tenant_id, memory.project_id)
  AND memory.status = 'verified'
  AND EXISTS (SELECT 1 FROM cehub_memory.memory_source_assessments a
   WHERE a.tenant_id=memory.tenant_id AND a.memory_id=memory.id
    AND a.state IN ('current','manual'));
"""

OLD_AGENT_VIEW = r"""
CREATE OR REPLACE VIEW cehub_ai.agent_memory_projection
WITH (security_barrier = true)
AS
SELECT
    memory.id AS memory_id,
    memory.tenant_id,
    memory.project_id,
    memory.title,
    memory.content,
    memory.applicability,
    memory.tags,
    memory.source_refs,
    memory.content_sha256,
    embedding.provider,
    embedding.model,
    embedding.dimensions,
    embedding.embedding
FROM cehub_memory.memories AS memory
JOIN cehub_memory.memory_embeddings AS embedding
  ON embedding.tenant_id = memory.tenant_id
 AND embedding.project_id = memory.project_id
 AND embedding.memory_id = memory.id
 AND embedding.content_sha256 = memory.content_sha256
WHERE cehub_ai.agent_scope_allows(memory.tenant_id, memory.project_id)
  AND memory.status = 'verified';
"""

MANIFEST = r"""
CREATE OR REPLACE FUNCTION cehub_ai.agent_manifest_sources_are_current(
 wanted_tenant uuid,wanted_run uuid,wanted_receipt uuid
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE pid uuid;
BEGIN
 SELECT project_id INTO pid FROM cehub_ai.agent_runs
  WHERE tenant_id=wanted_tenant AND id=wanted_run;
 IF NOT FOUND OR NOT cehub_ai.event_authorization_is_current(wanted_run) THEN RETURN false; END IF;
 RETURN NOT EXISTS(SELECT 1 FROM cehub_ai.agent_context_observations link
  JOIN cehub_ai.agent_tool_observations o ON o.id=link.observation_id
   AND o.tenant_id=link.tenant_id AND o.run_id=link.run_id,
   LATERAL jsonb_array_elements(coalesce(o.output_body->'items','[]'::jsonb)) item
  WHERE link.tenant_id=wanted_tenant AND link.run_id=wanted_run
   AND link.context_receipt_id=wanted_receipt AND o.tool_key='search_memory' AND NOT EXISTS(
    SELECT 1 FROM cehub_memory.memories memory JOIN cehub_memory.memory_embeddings embedding
     ON embedding.tenant_id=memory.tenant_id AND embedding.project_id=memory.project_id
      AND embedding.memory_id=memory.id AND embedding.content_sha256=memory.content_sha256
     WHERE memory.tenant_id=wanted_tenant AND memory.project_id=pid AND memory.status='verified'
      AND EXISTS (SELECT 1 FROM cehub_memory.memory_source_assessments a
       WHERE a.tenant_id=memory.tenant_id AND a.memory_id=memory.id
        AND a.state IN ('current','manual'))
      AND memory.id::text=item->>'memory_id' AND memory.content_sha256=item->>'content_sha256'));
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.agent_manifest_sources_are_current(uuid,uuid,uuid) FROM PUBLIC;
"""

OLD_MANIFEST = r"""
CREATE OR REPLACE FUNCTION cehub_ai.agent_manifest_sources_are_current(
 wanted_tenant uuid,wanted_run uuid,wanted_receipt uuid
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE pid uuid;
BEGIN
 SELECT project_id INTO pid FROM cehub_ai.agent_runs
  WHERE tenant_id=wanted_tenant AND id=wanted_run;
 IF NOT FOUND OR NOT cehub_ai.event_authorization_is_current(wanted_run) THEN RETURN false; END IF;
 RETURN NOT EXISTS(SELECT 1 FROM cehub_ai.agent_context_observations link
  JOIN cehub_ai.agent_tool_observations o ON o.id=link.observation_id
   AND o.tenant_id=link.tenant_id AND o.run_id=link.run_id,
   LATERAL jsonb_array_elements(coalesce(o.output_body->'items','[]'::jsonb)) item
  WHERE link.tenant_id=wanted_tenant AND link.run_id=wanted_run
   AND link.context_receipt_id=wanted_receipt AND o.tool_key='search_memory' AND NOT EXISTS(
    SELECT 1 FROM cehub_memory.memories memory JOIN cehub_memory.memory_embeddings embedding
     ON embedding.tenant_id=memory.tenant_id AND embedding.project_id=memory.project_id
      AND embedding.memory_id=memory.id AND embedding.content_sha256=memory.content_sha256
     WHERE memory.tenant_id=wanted_tenant AND memory.project_id=pid AND memory.status='verified'
      AND memory.id::text=item->>'memory_id' AND memory.content_sha256=item->>'content_sha256'));
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.agent_manifest_sources_are_current(uuid,uuid,uuid) FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(ASSESSMENTS)
    op.execute(MANIFEST)
    # Security projections are installed separately on some environments.
    if (
        op.get_bind()
        .exec_driver_sql("SELECT to_regclass('cehub_ai.agent_memory_projection')")
        .scalar_one()
    ):
        op.execute(AGENT_VIEW)


def downgrade() -> None:
    op.execute(OLD_MANIFEST)
    if (
        op.get_bind()
        .exec_driver_sql("SELECT to_regclass('cehub_ai.agent_memory_projection')")
        .scalar_one()
    ):
        op.execute(OLD_AGENT_VIEW)
    op.execute("DROP VIEW cehub_memory.memory_source_assessments")
