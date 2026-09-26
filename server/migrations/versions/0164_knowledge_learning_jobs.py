"""Durable rule-generated knowledge candidates, separate from source completion."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0164_knowledge_learning_jobs"
down_revision = "0163_memory_review_basis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_candidate_jobs",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("source_audit_id", sa.BigInteger(), nullable=False),
        sa.Column("source_event_id", sa.String(128), nullable=False),
        sa.Column("source_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(128), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_kind IN ('issue', 'decision', 'test_review', 'project_retrospective')",
            name=op.f("ck_knowledge_candidate_jobs_source_kind_allowed"),
        ),
        sa.CheckConstraint(
            "state IN ('pending','created','duplicate','skipped','failed')",
            name=op.f("ck_knowledge_candidate_jobs_state_allowed"),
        ),
        sa.CheckConstraint(
            "attempts >= 0", name=op.f("ck_knowledge_candidate_jobs_attempts_nonnegative")
        ),
        sa.CheckConstraint(
            "(state IN ('created','duplicate') AND memory_id IS NOT NULL) OR "
            "(state NOT IN ('created','duplicate') AND memory_id IS NULL)",
            name=op.f("ck_knowledge_candidate_jobs_result_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["cehub_project.projects.tenant_id", "cehub_project.projects.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_candidate_project",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_candidate_actor",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "memory_id"],
            ["cehub_memory.memories.tenant_id", "cehub_memory.memories.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_candidate_memory",
        ),
        sa.ForeignKeyConstraint(
            ["source_audit_id"],
            ["cehub_audit.audit_log.id"],
            name=op.f("fk_knowledge_candidate_jobs_source_audit_id_audit_log"),
        ),
        sa.UniqueConstraint("source_audit_id", name="uq_knowledge_candidate_audit"),
        schema="cehub_memory",
    )
    op.create_index(
        "ix_knowledge_candidate_pending",
        "knowledge_candidate_jobs",
        ["state", "available_at"],
        schema="cehub_memory",
    )
    op.create_index(
        "uq_knowledge_candidate_source",
        "knowledge_candidate_jobs",
        ["tenant_id", "source_kind", "source_id"],
        unique=True,
        postgresql_where=sa.text("state='created'"),
        schema="cehub_memory",
    )
    op.execute("""
CREATE FUNCTION cehub_memory.guard_knowledge_candidate_job() RETURNS trigger
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
CREATE TRIGGER guard_knowledge_candidate_job BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_memory.knowledge_candidate_jobs FOR EACH ROW
 EXECUTE FUNCTION cehub_memory.guard_knowledge_candidate_job();
""")


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_memory.knowledge_candidate_jobs)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard durable learning work")
    op.drop_table("knowledge_candidate_jobs", schema="cehub_memory")
    op.execute("DROP FUNCTION cehub_memory.guard_knowledge_candidate_job()")
