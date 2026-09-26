"""Freeze explicit replacement evidence in knowledge corrections."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0162_knowledge_source_binding"
down_revision = "0161_knowledge_source_validity"
branch_labels = None
depends_on = None


GUARD = r"""
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
 ) THEN
  RAISE EXCEPTION 'Publication must atomically replace the approved source' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
"""


def upgrade() -> None:
    op.add_column(
        "knowledge_corrections",
        sa.Column("source_selections", postgresql.JSONB()),
        schema="cehub_memory",
    )
    op.add_column(
        "knowledge_corrections",
        sa.Column("proposed_source_refs", postgresql.JSONB()),
        schema="cehub_memory",
    )
    op.create_check_constraint(
        op.f("ck_knowledge_corrections_source_choices_consistent"),
        "knowledge_corrections",
        "(source_selections IS NULL AND proposed_source_refs IS NULL) OR "
        "(source_selections IS NOT NULL AND proposed_source_refs IS NOT NULL AND "
        "jsonb_typeof(source_selections)='array' AND "
        "jsonb_typeof(proposed_source_refs)='array' AND "
        "jsonb_array_length(source_selections) BETWEEN 1 AND 20 AND "
        "jsonb_array_length(source_selections)=jsonb_array_length(proposed_source_refs))",
        schema="cehub_memory",
    )
    # The existing correction guard freezes every field except the five review fields.
    op.execute(GUARD)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_memory.knowledge_corrections "
                "WHERE source_selections IS NOT NULL)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard reviewed source choices")
    op.drop_constraint(
        op.f("ck_knowledge_corrections_source_choices_consistent"),
        "knowledge_corrections",
        schema="cehub_memory",
    )
    op.execute(OLD_GUARD)
    op.drop_column("knowledge_corrections", "proposed_source_refs", schema="cehub_memory")
    op.drop_column("knowledge_corrections", "source_selections", schema="cehub_memory")
