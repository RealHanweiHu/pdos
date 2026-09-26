"""Versioned human verification of original supplier notice candidates."""

from alembic import op

revision = "0317_supplier_notice_reviews"
down_revision = "0316_supplier_notice_dispatches"
branch_labels = None
depends_on = None

DDL = """


CREATE TABLE cehub_supplier.supplier_notice_reviews (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        candidate_id UUID NOT NULL,
        version INTEGER NOT NULL,
        decision VARCHAR(24) NOT NULL,
        review JSONB NOT NULL,
        snapshot JSONB NOT NULL,
        source_digest VARCHAR(64) NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        created_by_user_id UUID NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        CONSTRAINT pk_supplier_notice_reviews PRIMARY KEY (id),
        CONSTRAINT uq_notice_review_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT uq_notice_review_version UNIQUE (candidate_id, version),
        CONSTRAINT uq_notice_review_request UNIQUE (tenant_id, created_by_user_id, request_id),
        CONSTRAINT fk_supplier_notice_reviews_tenant_id_supplier_notice_candidates FOREIGN
KEY(tenant_id, project_id, candidate_id) REFERENCES cehub_supplier.supplier_notice_candidates
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_supplier_notice_reviews_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_supplier_notice_reviews_shape CHECK (version>0 AND decision IN
('accepted','excluded','needs_info') AND jsonb_typeof(review)='object' AND
jsonb_typeof(snapshot)='object' AND source_digest ~ '^[a-f0-9]{64}$' AND request_digest ~
'^[a-f0-9]{64}$')
)

;
CREATE FUNCTION cehub_supplier.guard_notice_review() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE previous integer; source jsonb;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR
UPDATE;
 SELECT coalesce(max(version),0) INTO previous FROM cehub_supplier.supplier_notice_reviews
 WHERE candidate_id=NEW.candidate_id;
 IF NEW.version<>previous+1 OR NEW.review->>'expected_version' IS DISTINCT FROM previous::text
    OR NEW.review->>'decision' IS DISTINCT FROM NEW.decision OR NEW.review->>'request_id' IS
DISTINCT FROM NEW.request_id::text
    OR NEW.snapshot->>'candidate_id' IS DISTINCT FROM NEW.candidate_id::text THEN
  RAISE EXCEPTION 'notice review must bind the next exact version';
 END IF;
 SELECT s.source_snapshot INTO source FROM cehub_supplier.supplier_notice_candidates c
 JOIN cehub_supplier.supplier_notice_scans s ON s.id=c.first_scan_id
 AND s.tenant_id=c.tenant_id AND s.project_id=c.project_id
 WHERE c.id=NEW.candidate_id AND c.tenant_id=NEW.tenant_id AND c.project_id=NEW.project_id
 AND c.scope_digest=NEW.snapshot->>'candidate_scope_digest';
 IF source IS NULL OR source IS DISTINCT FROM NEW.snapshot->'original'
    OR NEW.snapshot->>'content_available' IS DISTINCT FROM 'true' THEN
  RAISE EXCEPTION 'notice review requires original candidate source';
 END IF;
 IF NEW.decision='accepted' THEN
  IF NOT EXISTS (
   SELECT 1 FROM cehub_supplier.supplier_notice_candidates candidate
   JOIN cehub_supplier.supplier_notice_watches watch ON watch.id=candidate.watch_id
        AND watch.tenant_id=candidate.tenant_id AND watch.project_id=candidate.project_id
   JOIN cehub_supplier.supplier_notice_watch_revisions revision ON revision.watch_id=watch.id
        AND revision.version=watch.version
   JOIN cehub_evidence.research_subscriptions sub ON sub.id=watch.subscription_id
        AND sub.tenant_id=watch.tenant_id
   JOIN cehub_evidence.evidence_snapshots original ON original.id=candidate.snapshot_id
        AND original.tenant_id=candidate.tenant_id
   JOIN cehub_evidence.research_sources registry ON registry.id=original.source_id
        AND registry.tenant_id=original.tenant_id
   WHERE candidate.id=NEW.candidate_id AND candidate.tenant_id=NEW.tenant_id
     AND candidate.project_id=NEW.project_id AND watch.active AND sub.status='active'
     AND registry.status='active' AND original.superseded_by_id IS NULL
     AND original.conflicts_with_id IS NULL
     AND (original.freshness_expires_at IS NULL OR original.freshness_expires_at>now())
     AND revision.id::text=NEW.snapshot#>>'{current,watch_revision,id}'
     AND sub.last_snapshot_id::text=NEW.snapshot#>>'{current,snapshot,id}'
     AND watch.snapshot=NEW.snapshot#>'{current,watch_source}'
  ) THEN RAISE EXCEPTION 'accepted notice requires current mapping and valid original source'; END
IF;
  IF (SELECT count(DISTINCT entry->>'kind') FROM jsonb_array_elements(NEW.review->'dates') entry
      WHERE entry->>'kind' IN ('announced','effective','last_order','last_delivery')
      AND nullif(btrim(entry->>'basis'),'') IS NOT NULL)<>4 THEN
   RAISE EXCEPTION 'notice dates require four explicit human determinations';
  END IF;
  IF NEW.snapshot->>'original_valid' IS DISTINCT FROM 'true'
     OR NEW.snapshot->>'scope_current' IS DISTINCT FROM 'true'
     OR NEW.review->>'original_text_checked' IS DISTINCT FROM 'true'
     OR NEW.review->>'manufacturer_checked' IS DISTINCT FROM 'true'
     OR NEW.review->>'part_scope_checked' IS DISTINCT FROM 'true'
     OR nullif(btrim(NEW.review->>'notice_identifier'),'') IS NULL
     OR nullif(btrim(NEW.review->>'identity_basis'),'') IS NULL
     OR nullif(btrim(NEW.review->>'applicable_scope'),'') IS NULL
     OR nullif(btrim(NEW.review->>'impact'),'') IS NULL
     OR jsonb_array_length(NEW.review->'dates')<>4 THEN
   RAISE EXCEPTION 'accepted notice requires explicit human verification';
  END IF;
  IF NEW.snapshot->>'latest_snapshot_changed'='true' AND
    (NEW.review->>'latest_snapshot_checked' IS DISTINCT FROM 'true'
     OR nullif(btrim(NEW.review->>'latest_snapshot_basis'),'') IS NULL) THEN
   RAISE EXCEPTION 'changed latest text requires human reconciliation';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER notice_review_guard BEFORE INSERT ON cehub_supplier.supplier_notice_reviews
 FOR EACH ROW EXECUTE FUNCTION cehub_supplier.guard_notice_review();
CREATE TRIGGER notice_review_immutable BEFORE UPDATE OR DELETE
 ON cehub_supplier.supplier_notice_reviews FOR EACH ROW
 EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON FUNCTION cehub_supplier.guard_notice_review() FROM PUBLIC;
REVOKE ALL ON cehub_supplier.supplier_notice_reviews FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM cehub_supplier.supplier_notice_reviews) THEN
        RAISE EXCEPTION 'retain human notice review history';
      END IF;
    END $$;
    DROP TABLE cehub_supplier.supplier_notice_reviews;
    DROP FUNCTION cehub_supplier.guard_notice_review();
    """)
