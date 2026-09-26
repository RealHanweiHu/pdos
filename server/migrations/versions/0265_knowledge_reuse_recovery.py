"""Named recovery of retrieval failures using a retained successful embedding."""

from alembic import op

revision = "0265_knowledge_reuse_recovery"
down_revision = "0264_knowledge_reuse_jobs"
branch_labels = None
depends_on = None

UPGRADE = """

CREATE OR REPLACE FUNCTION cehub_memory.guard_knowledge_reuse_job() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Knowledge reuse history is retained' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.state<>'pending' OR NEW.embedding_receipt IS NOT NULL OR NEW.push_ids::jsonb<>'[]'::jsonb
   OR NOT EXISTS(SELECT 1 FROM cehub_audit.audit_log a
      WHERE a.tenant_id=NEW.tenant_id AND a.project_id=NEW.project_id
       AND a.id=NEW.source_audit_id AND a.entity_id=NEW.context_entity_id) THEN
   RAISE EXCEPTION 'Reuse requests require a real business source' USING ERRCODE='23514';
  END IF;
 ELSE
  IF (to_jsonb(NEW)-ARRAY['state','embedding_receipt','push_ids','reason','updated_at']) IS
DISTINCT FROM
     (to_jsonb(OLD)-ARRAY['state','embedding_receipt','push_ids','reason','updated_at'])
   OR NOT ((OLD.state='pending' AND NEW.state IN ('running','stale'))
     OR (OLD.state='running' AND NEW.state IN
('running','ready','empty','stale','failed','uncertain'))
     OR (OLD.state='failed' AND NEW.state='pending' AND OLD.embedding_receipt IS NOT NULL))
   OR (OLD.embedding_receipt IS NOT NULL AND OLD.embedding_receipt::jsonb IS DISTINCT FROM
NEW.embedding_receipt::jsonb) THEN
   RAISE EXCEPTION 'Reuse source and successful embedding receipt are immutable' USING
ERRCODE='23514';
  END IF;
 END IF;
 IF TG_OP='UPDATE' AND OLD.state='failed' AND NEW.state='pending' AND NOT EXISTS(
  SELECT 1 FROM cehub_audit.audit_log a
   WHERE a.tenant_id=NEW.tenant_id AND a.project_id=NEW.project_id
    AND a.entity_id=NEW.id AND a.actor_user_id=NEW.recipient_user_id
    AND a.action='knowledge.reuse.resume'
    AND a.context->>'request_id' IS NOT NULL
    AND a.before_snapshot->>'state'='failed'
    AND (a.before_snapshot->>'updated_at')::timestamptz=OLD.updated_at
    AND a.after_snapshot->>'state'='pending'
    AND (a.after_snapshot->>'updated_at')::timestamptz=NEW.updated_at
 ) THEN
  RAISE EXCEPTION 'Resuming knowledge reuse needs the named current request receipt'
   USING ERRCODE='23514';
 END IF;
 IF jsonb_typeof(NEW.push_ids::jsonb)<>'array' OR jsonb_array_length(NEW.push_ids::jsonb)>5
   OR (NEW.state='ready' AND jsonb_array_length(NEW.push_ids::jsonb)=0)
   OR (NEW.state<>'ready' AND NEW.push_ids::jsonb<>'[]'::jsonb)
   OR (NEW.state IN ('ready','empty') AND NEW.embedding_receipt IS NULL) THEN
  RAISE EXCEPTION 'Invalid knowledge reuse result' USING ERRCODE='23514';
 END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements_text(NEW.push_ids::jsonb) x(id)
  WHERE NOT EXISTS(SELECT 1 FROM cehub_memory.knowledge_pushes p WHERE p.id=x.id::uuid
   AND p.tenant_id=NEW.tenant_id AND p.project_id=NEW.project_id
   AND p.context_kind=NEW.context_kind AND p.context_entity_id=NEW.context_entity_id
   AND p.context_sha256=NEW.context_sha256)) THEN
  RAISE EXCEPTION 'Reuse results must match the original business input' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;

"""
DOWNGRADE = """

CREATE OR REPLACE FUNCTION cehub_memory.guard_knowledge_reuse_job() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Knowledge reuse history is retained' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.state<>'pending' OR NEW.embedding_receipt IS NOT NULL OR NEW.push_ids::jsonb<>'[]'::jsonb
   OR NOT EXISTS(SELECT 1 FROM cehub_audit.audit_log a
      WHERE a.tenant_id=NEW.tenant_id AND a.project_id=NEW.project_id
       AND a.id=NEW.source_audit_id AND a.entity_id=NEW.context_entity_id) THEN
   RAISE EXCEPTION 'Reuse requests require a real business source' USING ERRCODE='23514';
  END IF;
 ELSE
  IF (to_jsonb(NEW)-ARRAY['state','embedding_receipt','push_ids','reason','updated_at']) IS
DISTINCT FROM
     (to_jsonb(OLD)-ARRAY['state','embedding_receipt','push_ids','reason','updated_at'])
   OR NOT ((OLD.state='pending' AND NEW.state IN ('running','stale'))
     OR (OLD.state='running' AND NEW.state IN
('running','ready','empty','stale','failed','uncertain')))
   OR (OLD.embedding_receipt IS NOT NULL AND OLD.embedding_receipt::jsonb IS DISTINCT FROM
NEW.embedding_receipt::jsonb) THEN
   RAISE EXCEPTION 'Reuse source and successful embedding receipt are immutable' USING
ERRCODE='23514';
  END IF;
 END IF;
 IF jsonb_typeof(NEW.push_ids::jsonb)<>'array' OR jsonb_array_length(NEW.push_ids::jsonb)>5
   OR (NEW.state='ready' AND jsonb_array_length(NEW.push_ids::jsonb)=0)
   OR (NEW.state<>'ready' AND NEW.push_ids::jsonb<>'[]'::jsonb)
   OR (NEW.state IN ('ready','empty') AND NEW.embedding_receipt IS NULL) THEN
  RAISE EXCEPTION 'Invalid knowledge reuse result' USING ERRCODE='23514';
 END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements_text(NEW.push_ids::jsonb) x(id)
  WHERE NOT EXISTS(SELECT 1 FROM cehub_memory.knowledge_pushes p WHERE p.id=x.id::uuid
   AND p.tenant_id=NEW.tenant_id AND p.project_id=NEW.project_id
   AND p.context_kind=NEW.context_kind AND p.context_entity_id=NEW.context_entity_id
   AND p.context_sha256=NEW.context_sha256)) THEN
  RAISE EXCEPTION 'Reuse results must match the original business input' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;

"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
