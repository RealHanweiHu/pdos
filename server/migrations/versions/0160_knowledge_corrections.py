"""Human knowledge corrections and atomic replacement publication."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0160_knowledge_corrections"
down_revision = "0159_knowledge_takeover"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_corrections",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_memory_id", sa.Uuid(), nullable=False),
        sa.Column("proposer_user_id", sa.Uuid(), nullable=False),
        sa.Column("source_content_sha256", sa.String(64), nullable=False),
        sa.Column("source_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("proposal", postgresql.JSONB(), nullable=False),
        sa.Column("proposal_sha256", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("replacement_memory_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["cehub_project.projects.tenant_id", "cehub_project.projects.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_correction_project",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_memory_id"],
            ["cehub_memory.memories.tenant_id", "cehub_memory.memories.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_correction_source",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "replacement_memory_id"],
            ["cehub_memory.memories.tenant_id", "cehub_memory.memories.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_correction_replacement",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "proposer_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_correction_proposer",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewed_by_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_correction_reviewer",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'published', 'rejected')",
            name=op.f("ck_knowledge_corrections_status_allowed"),
        ),
        sa.CheckConstraint(
            "reviewed_by_user_id IS NULL OR reviewed_by_user_id <> proposer_user_id",
            name=op.f("ck_knowledge_corrections_four_eyes"),
        ),
        sa.CheckConstraint(
            "(status='pending' AND "
            "reviewed_by_user_id IS NULL AND "
            "review_reason IS NULL AND "
            "reviewed_at IS NULL AND "
            "replacement_memory_id IS NULL) OR "
            "(status IN ('published','rejected') AND "
            "reviewed_by_user_id IS NOT NULL AND "
            "length(btrim(review_reason)) > 0 AND "
            "reviewed_at IS NOT NULL AND "
            "((status='published' AND "
            "replacement_memory_id IS NOT NULL) OR "
            "(status='rejected' AND "
            "replacement_memory_id IS NULL)))",
            name=op.f("ck_knowledge_corrections_review_consistent"),
        ),
        schema="cehub_memory",
    )
    op.create_index(
        "ix_knowledge_corrections_project",
        "knowledge_corrections",
        ["tenant_id", "project_id", "created_at"],
        schema="cehub_memory",
    )
    op.create_index(
        "uq_knowledge_correction_published_source",
        "knowledge_corrections",
        ["tenant_id", "source_memory_id"],
        unique=True,
        postgresql_where=sa.text("status='published'"),
        schema="cehub_memory",
    )
    op.execute("""
CREATE FUNCTION cehub_memory.guard_knowledge_correction() RETURNS trigger
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
REVOKE ALL ON FUNCTION cehub_memory.guard_knowledge_correction() FROM PUBLIC;
CREATE TRIGGER guard_knowledge_correction BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_memory.knowledge_corrections FOR EACH ROW
 EXECUTE FUNCTION cehub_memory.guard_knowledge_correction();
""")


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_memory.knowledge_corrections)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard knowledge correction history")
    op.drop_table("knowledge_corrections", schema="cehub_memory")
    op.execute("DROP FUNCTION cehub_memory.guard_knowledge_correction()")
