"""Confirmed retrospective versions, history, and version-bound knowledge candidates."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0165_meeting_retrospectives"
down_revision = "0164_knowledge_learning_jobs"
branch_labels = None
depends_on = None

OLD_VIEW = r"""
CREATE OR REPLACE VIEW cehub_memory.memory_source_assessments AS
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

NEW_VIEW = r"""
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

OLD_GUARD = r"""
CREATE OR REPLACE FUNCTION cehub_memory.guard_knowledge_candidate_job() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Knowledge learning history is retained' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' AND (NEW.state<>'pending' OR NOT EXISTS(
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


def upgrade() -> None:
    for column in (
        sa.Column("retrospective_conclusion", sa.Text()),
        sa.Column("retrospective_applicability", sa.Text()),
        sa.Column(
            "retrospective_source_refs",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "retrospective_version", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("retrospective_digest", sa.String(64)),
        sa.Column("retrospective_confirmed_by_user_id", sa.Uuid()),
        sa.Column("retrospective_confirmed_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("meetings", column, schema="cehub_project")
    op.create_foreign_key(
        "fk_meetings_retrospective_confirmer",
        "meetings",
        "users",
        ["tenant_id", "retrospective_confirmed_by_user_id"],
        ["tenant_id", "id"],
        source_schema="cehub_project",
        referent_schema="cehub_core",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_meetings_retrospective_consistent"),
        "meetings",
        "(retrospective_version=0 AND retrospective_conclusion IS NULL AND "
        "retrospective_applicability IS NULL AND retrospective_digest IS NULL AND "
        "retrospective_confirmed_by_user_id IS NULL AND retrospective_confirmed_at IS "
        "NULL AND retrospective_source_refs='[]'::jsonb) OR (retrospective_version>0 AND "
        "meeting_type='project_retrospective' AND status='completed' AND "
        "length(btrim(retrospective_conclusion)) BETWEEN 1 AND 15000 AND "
        "length(btrim(retrospective_applicability)) BETWEEN 1 AND 3000 AND "
        "retrospective_digest ~ '^[0-9a-f]{64}$' AND retrospective_conclusion IS NOT NULL "
        "AND retrospective_applicability IS NOT NULL AND retrospective_digest IS NOT NULL "
        "AND retrospective_confirmed_by_user_id IS NOT NULL AND "
        "retrospective_confirmed_at IS NOT NULL)",
        schema="cehub_project",
    )
    op.create_check_constraint(
        op.f("ck_meetings_retrospective_sources_array"),
        "meetings",
        "jsonb_typeof(retrospective_source_refs)='array'",
        schema="cehub_project",
    )
    op.execute("""
CREATE FUNCTION cehub_project.guard_retrospective_version() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.retrospective_version<>0 THEN
   RAISE EXCEPTION 'Create the meeting before confirming a retrospective' USING ERRCODE='23514';
  END IF;
 ELSIF ROW(NEW.retrospective_conclusion,NEW.retrospective_applicability,
  NEW.retrospective_source_refs,NEW.retrospective_version,NEW.retrospective_digest,
  NEW.retrospective_confirmed_by_user_id,NEW.retrospective_confirmed_at) IS DISTINCT FROM
 ROW(OLD.retrospective_conclusion,OLD.retrospective_applicability,
  OLD.retrospective_source_refs,OLD.retrospective_version,OLD.retrospective_digest,
  OLD.retrospective_confirmed_by_user_id,OLD.retrospective_confirmed_at) THEN
  IF NEW.retrospective_version<>OLD.retrospective_version+1
   OR NEW.retrospective_digest IS NOT DISTINCT FROM OLD.retrospective_digest
   OR OLD.status<>'completed' OR OLD.archived_at IS NOT NULL OR OLD.deleted_at IS NOT NULL THEN
   RAISE EXCEPTION 'Confirm a new retrospective version with its full basis' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_project.guard_retrospective_version() FROM PUBLIC;
CREATE TRIGGER guard_retrospective_version BEFORE INSERT OR UPDATE ON cehub_project.meetings
 FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_retrospective_version();
""")
    op.add_column(
        "knowledge_candidate_jobs",
        sa.Column("source_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        schema="cehub_memory",
    )
    op.create_check_constraint(
        op.f("ck_knowledge_candidate_jobs_source_version_nonnegative"),
        "knowledge_candidate_jobs",
        "source_version>=0",
        schema="cehub_memory",
    )
    op.drop_index(
        "uq_knowledge_candidate_source", "knowledge_candidate_jobs", schema="cehub_memory"
    )
    op.create_index(
        "uq_knowledge_candidate_source",
        "knowledge_candidate_jobs",
        ["tenant_id", "source_kind", "source_id", "source_version"],
        unique=True,
        postgresql_where=sa.text("state='created'"),
        schema="cehub_memory",
    )
    op.execute(NEW_GUARD)
    op.execute(NEW_VIEW)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_project.meetings WHERE retrospective_version>0) "
                "OR EXISTS(SELECT 1 FROM cehub_memory.knowledge_candidate_jobs "
                "WHERE source_version>0)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard confirmed retrospective history")
    op.execute(OLD_VIEW)
    op.execute(OLD_GUARD)
    op.drop_index(
        "uq_knowledge_candidate_source", "knowledge_candidate_jobs", schema="cehub_memory"
    )
    op.create_index(
        "uq_knowledge_candidate_source",
        "knowledge_candidate_jobs",
        ["tenant_id", "source_kind", "source_id"],
        unique=True,
        postgresql_where=sa.text("state='created'"),
        schema="cehub_memory",
    )
    op.drop_constraint(
        op.f("ck_knowledge_candidate_jobs_source_version_nonnegative"),
        "knowledge_candidate_jobs",
        schema="cehub_memory",
    )
    op.drop_column("knowledge_candidate_jobs", "source_version", schema="cehub_memory")
    op.execute("DROP TRIGGER guard_retrospective_version ON cehub_project.meetings")
    op.execute("DROP FUNCTION cehub_project.guard_retrospective_version()")
    op.drop_constraint("fk_meetings_retrospective_confirmer", "meetings", schema="cehub_project")
    op.drop_constraint(
        op.f("ck_meetings_retrospective_consistent"), "meetings", schema="cehub_project"
    )
    op.drop_constraint(
        op.f("ck_meetings_retrospective_sources_array"), "meetings", schema="cehub_project"
    )
    for name in (
        "retrospective_conclusion",
        "retrospective_applicability",
        "retrospective_source_refs",
        "retrospective_version",
        "retrospective_digest",
        "retrospective_confirmed_by_user_id",
        "retrospective_confirmed_at",
    ):
        op.drop_column("meetings", name, schema="cehub_project")
