"""Versioned root-cause and effectiveness learning through the original review queue."""

# ruff: noqa: E501
from alembic import op

revision = "0353_quality_learning"
down_revision = "0352_product_result_feedback"
branch_labels = None
depends_on = None

OLD_VIEW = r"""
CREATE OR REPLACE VIEW cehub_memory.memory_source_assessments AS
WITH checks AS (
 SELECT m.tenant_id,m.project_id,m.id AS memory_id,m.status,
  coalesce(jsonb_agg(jsonb_build_object('kind',r.ref->>'kind','reference',r.ref->>'reference',
   'state', CASE
    WHEN r.ref IS NULL THEN 'manual'
    WHEN r.ref->>'kind'='meeting_retrospective' THEN coalesce((SELECT CASE
     WHEN mt.retrospective_version::text=r.ref->>'version'
      AND mt.retrospective_digest=r.ref->>'digest' AND mt.status='completed'
      AND mt.deleted_at IS NULL THEN 'current' ELSE 'stale' END
     FROM cehub_project.meetings mt WHERE mt.tenant_id=m.tenant_id
      AND mt.project_id=m.project_id AND mt.id::text=r.ref->>'reference'),'unavailable')
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

NEW_VIEW = r"""
CREATE OR REPLACE VIEW cehub_memory.memory_source_assessments AS
WITH checks AS (
 SELECT m.tenant_id,m.project_id,m.id AS memory_id,m.status,
  coalesce(jsonb_agg(jsonb_build_object('kind',r.ref->>'kind','reference',r.ref->>'reference',
   'state', CASE
    WHEN r.ref IS NULL THEN 'manual'
    WHEN r.ref->>'kind'='root_cause' THEN coalesce((SELECT CASE
     WHEN rc.version::text=r.ref->>'version' AND rc.status='approved' THEN 'current' ELSE 'stale' END
     FROM cehub_quality.root_cause_analyses rc WHERE rc.tenant_id=m.tenant_id
      AND rc.project_id=m.project_id AND rc.id::text=r.ref->>'reference'),'unavailable')
    WHEN r.ref->>'kind'='effectiveness_review' THEN coalesce((SELECT CASE
     WHEN er.review_number::text=r.ref->>'version' AND NOT EXISTS(
      SELECT 1 FROM cehub_quality.effectiveness_reviews later WHERE later.tenant_id=er.tenant_id
       AND later.project_id=er.project_id AND later.ncr_id=er.ncr_id AND later.review_number>er.review_number
     ) THEN 'current' ELSE 'stale' END FROM cehub_quality.effectiveness_reviews er
      WHERE er.tenant_id=m.tenant_id AND er.project_id=m.project_id AND er.id::text=r.ref->>'reference'),'unavailable')
    WHEN r.ref->>'kind'='test_run' THEN coalesce((SELECT CASE
     WHEN r.ref->>'updated_at_utc' IS NULL THEN 'needs_review'
     WHEN to_char(tr.updated_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')=r.ref->>'updated_at_utc'
      AND tr.draft_state='confirmed' AND tr.status IN ('passed','failed','aborted') THEN 'current' ELSE 'stale' END
     FROM cehub_quality.test_runs tr WHERE tr.tenant_id=m.tenant_id AND tr.project_id=m.project_id
      AND tr.id::text=r.ref->>'reference'),'unavailable')
    WHEN r.ref->>'kind'='decision' THEN coalesce((SELECT CASE
     WHEN r.ref->>'updated_at_utc' IS NULL THEN 'needs_review'
     WHEN to_char(dr.updated_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')=r.ref->>'updated_at_utc'
      THEN 'current' ELSE 'stale' END FROM cehub_project.decisions dr
     WHERE dr.tenant_id=m.tenant_id AND dr.project_id=m.project_id AND dr.id::text=r.ref->>'reference'),'unavailable')
    WHEN r.ref->>'kind'='meeting_retrospective' THEN coalesce((SELECT CASE
     WHEN mt.retrospective_version::text=r.ref->>'version'
      AND mt.retrospective_digest=r.ref->>'digest' AND mt.status='completed'
      AND mt.deleted_at IS NULL THEN 'current' ELSE 'stale' END
     FROM cehub_project.meetings mt WHERE mt.tenant_id=m.tenant_id
      AND mt.project_id=m.project_id AND mt.id::text=r.ref->>'reference'),'unavailable')
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

OLD_GUARD = r"""
CREATE OR REPLACE FUNCTION cehub_memory.guard_knowledge_candidate_job() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Knowledge learning history is retained' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' AND (NEW.state<>'pending'
  OR NEW.source_version <> CASE WHEN NEW.source_kind='project_retrospective'
   THEN coalesce((NEW.source_snapshot->>'retrospective_version')::integer,0) ELSE 0 END
  OR NOT EXISTS(
  SELECT 1 FROM cehub_audit.audit_log a WHERE a.id=NEW.source_audit_id
   AND a.tenant_id=NEW.tenant_id AND a.project_id=NEW.project_id
   AND a.entity_id=NEW.source_id AND a.actor_user_id=NEW.actor_user_id
   AND a.event_id=NEW.source_event_id AND a.after_snapshot=NEW.source_snapshot
 )) THEN
  RAISE EXCEPTION 'Learning must bind the actual committed business audit' USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' AND (OLD.state NOT IN ('pending','failed')
  OR NEW.attempts <> OLD.attempts+1
  OR (to_jsonb(NEW)-ARRAY['state','memory_id','reason','attempts','available_at','updated_at'])
   IS DISTINCT FROM
  (to_jsonb(OLD)-ARRAY['state','memory_id','reason','attempts','available_at','updated_at'])) THEN
  RAISE EXCEPTION 'Learning source is immutable and only pending work can advance'
   USING ERRCODE='23514';
 END IF;
 IF NEW.memory_id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM cehub_memory.memories m WHERE m.tenant_id=NEW.tenant_id
   AND m.project_id=NEW.project_id AND m.id=NEW.memory_id
   AND (NEW.state='duplicate' OR m.created_by_user_id=NEW.actor_user_id)
 ) THEN
  RAISE EXCEPTION 'Candidate result must remain within its originating project'
   USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_memory.guard_knowledge_candidate_job() FROM PUBLIC;
"""

NEW_GUARD = r"""
CREATE OR REPLACE FUNCTION cehub_memory.guard_knowledge_candidate_job() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Knowledge learning history is retained' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' AND (NEW.state<>'pending'
  OR NEW.source_version <> CASE WHEN NEW.source_kind='project_retrospective'
   THEN coalesce((NEW.source_snapshot->>'retrospective_version')::integer,0)
   WHEN NEW.source_kind='root_cause' THEN coalesce((NEW.source_snapshot->>'version')::integer,0)
   WHEN NEW.source_kind='effectiveness_review' THEN coalesce((NEW.source_snapshot->>'review_number')::integer,0) ELSE 0 END
  OR NOT EXISTS(
  SELECT 1 FROM cehub_audit.audit_log a WHERE a.id=NEW.source_audit_id
   AND a.tenant_id=NEW.tenant_id AND a.project_id=NEW.project_id
   AND a.entity_id=NEW.source_id AND a.actor_user_id=NEW.actor_user_id
   AND a.event_id=NEW.source_event_id AND a.after_snapshot=NEW.source_snapshot
 )) THEN
  RAISE EXCEPTION 'Learning must bind the actual committed business audit' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' AND NEW.source_kind IN ('root_cause','effectiveness_review') AND (
  NEW.source_version<1 OR NOT EXISTS(
   SELECT 1 FROM cehub_event.events e WHERE e.tenant_id=NEW.tenant_id AND e.project_id=NEW.project_id
    AND e.event_id=NEW.source_event_id AND e.entity_id=NEW.source_id AND (
     (NEW.source_kind='root_cause' AND e.event_type='ROOT_CAUSE_ANALYSIS_CHANGED'
       AND e.payload->>'action'='approved' AND NEW.source_snapshot->>'status'='approved')
     OR (NEW.source_kind='effectiveness_review' AND e.event_type='EFFECTIVENESS_REVIEWED'
       AND NEW.source_snapshot->>'result' IN ('effective','ineffective'))
    )
  )) THEN RAISE EXCEPTION 'Quality learning requires the actual approved/reviewed event'; END IF;
 IF TG_OP='UPDATE' AND (OLD.state NOT IN ('pending','failed')
  OR NEW.attempts <> OLD.attempts+1
  OR (to_jsonb(NEW)-ARRAY['state','memory_id','reason','attempts','available_at','updated_at'])
   IS DISTINCT FROM
  (to_jsonb(OLD)-ARRAY['state','memory_id','reason','attempts','available_at','updated_at'])) THEN
  RAISE EXCEPTION 'Learning source is immutable and only pending work can advance'
   USING ERRCODE='23514';
 END IF;
 IF NEW.memory_id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM cehub_memory.memories m WHERE m.tenant_id=NEW.tenant_id
   AND m.project_id=NEW.project_id AND m.id=NEW.memory_id
   AND (NEW.state='duplicate' OR m.created_by_user_id=NEW.actor_user_id)
 ) THEN
  RAISE EXCEPTION 'Candidate result must remain within its originating project'
   USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_memory.guard_knowledge_candidate_job() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cehub_memory.knowledge_candidate_jobs DROP CONSTRAINT ck_knowledge_candidate_jobs_source_kind_allowed"
    )
    op.execute(
        "ALTER TABLE cehub_memory.knowledge_candidate_jobs ADD CONSTRAINT ck_knowledge_candidate_jobs_source_kind_allowed CHECK(source_kind IN ('issue','decision','test_review','project_retrospective','root_cause','effectiveness_review'))"
    )
    op.execute(NEW_GUARD)
    op.execute(NEW_VIEW)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_memory.knowledge_candidate_jobs WHERE source_kind IN ('root_cause','effectiveness_review')) THEN RAISE EXCEPTION 'Retain quality learning history'; END IF; END $$;"
    )
    op.execute(OLD_VIEW)
    op.execute(OLD_GUARD)
    op.execute(
        "ALTER TABLE cehub_memory.knowledge_candidate_jobs DROP CONSTRAINT ck_knowledge_candidate_jobs_source_kind_allowed"
    )
    op.execute(
        "ALTER TABLE cehub_memory.knowledge_candidate_jobs ADD CONSTRAINT ck_knowledge_candidate_jobs_source_kind_allowed CHECK(source_kind IN ('issue','decision','test_review','project_retrospective'))"
    )
