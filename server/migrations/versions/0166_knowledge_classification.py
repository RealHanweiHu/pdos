"""Human-reviewed knowledge classifications without rewriting legacy acceptance."""

import sqlalchemy as sa
from alembic import op

revision = "0166_knowledge_classification"
down_revision = "0165_meeting_retrospectives"
branch_labels = None
depends_on = None

OLD_GUARD = r"""
CREATE OR REPLACE FUNCTION cehub_memory.guard_knowledge_correction() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Knowledge corrections preserve history' USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' AND (OLD.status <> 'pending' OR NEW.status='pending' OR
  (to_jsonb(NEW)-ARRAY['status','replacement_memory_id',
   'reviewed_by_user_id','review_reason','reviewed_at'])
   IS DISTINCT FROM
  (to_jsonb(OLD)-ARRAY['status','replacement_memory_id',
   'reviewed_by_user_id','review_reason','reviewed_at'])) THEN
  RAISE EXCEPTION 'Only a pending correction can receive one review' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' AND (NEW.status <> 'pending' OR NOT EXISTS (
  SELECT 1 FROM cehub_memory.memories m WHERE m.tenant_id=NEW.tenant_id
   AND m.project_id=NEW.project_id AND m.id=NEW.source_memory_id
   AND m.status='verified' AND m.content_sha256=NEW.source_content_sha256
 )) THEN
  RAISE EXCEPTION 'Correction must reference current verified knowledge' USING ERRCODE='23514';
 END IF;
 IF NEW.status='published' AND NOT EXISTS (
  SELECT 1 FROM cehub_memory.memories old JOIN cehub_memory.memories fresh
   ON fresh.tenant_id=old.tenant_id AND fresh.project_id=old.project_id
  WHERE old.tenant_id=NEW.tenant_id AND old.project_id=NEW.project_id
   AND old.id=NEW.source_memory_id AND old.status='archived'
   AND old.content_sha256=NEW.source_content_sha256
   AND fresh.id=NEW.replacement_memory_id AND fresh.status='verified'
   AND fresh.content_sha256=NEW.proposal_sha256
   AND fresh.created_by_user_id=NEW.proposer_user_id
   AND fresh.verified_by_user_id=NEW.reviewed_by_user_id
   AND fresh.source_refs = coalesce(NEW.proposed_source_refs,old.source_refs)
    || jsonb_build_array(jsonb_build_object('kind','memory_correction',
     'reference',old.id::text,'content_sha256',old.content_sha256,
     'correction_id',NEW.id::text))
 ) THEN
  RAISE EXCEPTION 'Publication must atomically replace the approved source' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
"""
NEW_GUARD = r"""
CREATE OR REPLACE FUNCTION cehub_memory.guard_knowledge_correction() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Knowledge corrections preserve history' USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' AND (OLD.status <> 'pending' OR NEW.status='pending' OR
  (to_jsonb(NEW)-ARRAY['status','replacement_memory_id',
   'reviewed_by_user_id','review_reason','reviewed_at'])
   IS DISTINCT FROM
  (to_jsonb(OLD)-ARRAY['status','replacement_memory_id',
   'reviewed_by_user_id','review_reason','reviewed_at'])) THEN
  RAISE EXCEPTION 'Only a pending correction can receive one review' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' AND (NEW.status <> 'pending' OR NOT EXISTS (
  SELECT 1 FROM cehub_memory.memories m WHERE m.tenant_id=NEW.tenant_id
   AND m.project_id=NEW.project_id AND m.id=NEW.source_memory_id
   AND m.status='verified' AND m.content_sha256=NEW.source_content_sha256
 )) THEN
  RAISE EXCEPTION 'Correction must reference current verified knowledge' USING ERRCODE='23514';
 END IF;
 IF NEW.status='published' AND NOT EXISTS (
  SELECT 1 FROM cehub_memory.memories old JOIN cehub_memory.memories fresh
   ON fresh.tenant_id=old.tenant_id AND fresh.project_id=old.project_id
  WHERE old.tenant_id=NEW.tenant_id AND old.project_id=NEW.project_id
   AND old.id=NEW.source_memory_id AND old.status='archived'
   AND old.content_sha256=NEW.source_content_sha256
   AND fresh.id=NEW.replacement_memory_id AND fresh.status='verified'
   AND fresh.content_sha256=NEW.proposal_sha256
   AND fresh.knowledge_kind=NEW.proposal->>'knowledge_kind'
   AND fresh.created_by_user_id=NEW.proposer_user_id
   AND fresh.verified_by_user_id=NEW.reviewed_by_user_id
   AND fresh.source_refs = coalesce(NEW.proposed_source_refs,old.source_refs)
    || jsonb_build_array(jsonb_build_object('kind','memory_correction',
     'reference',old.id::text,'content_sha256',old.content_sha256,
     'correction_id',NEW.id::text))
 ) THEN
  RAISE EXCEPTION 'Publication must atomically replace the approved source' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
"""


def upgrade() -> None:
    op.add_column("memories", sa.Column("knowledge_kind", sa.String(32)), schema="cehub_memory")
    op.create_check_constraint(
        op.f("ck_memories_knowledge_kind_allowed"),
        "memories",
        "knowledge_kind IS NULL OR knowledge_kind IN "
        "('design_rule','failure_case','supplier_experience','benchmark')",
        schema="cehub_memory",
    )
    op.create_index(
        "ix_memories_project_kind",
        "memories",
        ["tenant_id", "project_id", "knowledge_kind"],
        schema="cehub_memory",
    )
    op.execute("""
CREATE FUNCTION cehub_memory.guard_knowledge_classification() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='INSERT' AND NEW.status='verified' AND NEW.knowledge_kind IS NULL THEN
  RAISE EXCEPTION 'New published knowledge requires a reviewed classification'
   USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' THEN
  IF (OLD.status='draft' AND NEW.status='verified' AND NEW.knowledge_kind IS NULL)
   OR (OLD.status<>'draft' AND NEW.knowledge_kind IS DISTINCT FROM OLD.knowledge_kind)
   OR (NEW.knowledge_kind IS DISTINCT FROM OLD.knowledge_kind
    AND NEW.content_sha256=OLD.content_sha256) THEN
   RAISE EXCEPTION 'Classification changes require a new reviewed version' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_memory.guard_knowledge_classification() FROM PUBLIC;
CREATE TRIGGER guard_knowledge_classification BEFORE INSERT OR UPDATE ON cehub_memory.memories
 FOR EACH ROW EXECUTE FUNCTION cehub_memory.guard_knowledge_classification();
""")
    op.execute(NEW_GUARD)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_memory.memories "
                "WHERE knowledge_kind IS NOT NULL) "
                "OR EXISTS(SELECT 1 FROM cehub_memory.knowledge_corrections WHERE "
                "proposal->>'knowledge_kind' IS NOT NULL)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard knowledge classification history")
    op.execute(OLD_GUARD)
    op.execute("DROP TRIGGER guard_knowledge_classification ON cehub_memory.memories")
    op.execute("DROP FUNCTION cehub_memory.guard_knowledge_classification()")
    op.drop_index("ix_memories_project_kind", "memories", schema="cehub_memory")
    op.drop_constraint(
        op.f("ck_memories_knowledge_kind_allowed"), "memories", schema="cehub_memory"
    )
    op.drop_column("memories", "knowledge_kind", schema="cehub_memory")
