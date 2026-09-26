"""Task takeover retrieval and immutable, contextual knowledge use receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0159_knowledge_takeover"
down_revision = "0158_schedule_projection_guards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Old rows keep NULL: their original matching input cannot be reconstructed.
    op.add_column(
        "knowledge_pushes", sa.Column("context_sha256", sa.String(64)), schema="cehub_memory"
    )
    op.drop_constraint(
        "uq_knowledge_pushes_context_memory", "knowledge_pushes", schema="cehub_memory"
    )
    op.create_unique_constraint(
        "uq_knowledge_pushes_context_memory",
        "knowledge_pushes",
        ["tenant_id", "context_kind", "context_entity_id", "memory_id", "context_sha256"],
        schema="cehub_memory",
    )
    op.drop_constraint(
        op.f("ck_knowledge_pushes_context_kind_allowed"), "knowledge_pushes", schema="cehub_memory"
    )
    op.create_check_constraint(
        op.f("ck_knowledge_pushes_context_kind_allowed"),
        "knowledge_pushes",
        "context_kind IN ('project_kickoff', 'change_request', 'part_selection', 'task_takeover')",
        schema="cehub_memory",
    )
    op.create_table(
        "knowledge_push_feedback",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("push_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("memory_content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('adopted', 'not_useful')",
            name=op.f("ck_knowledge_push_feedback_action_allowed"),
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) BETWEEN 1 AND 5000",
            name=op.f("ck_knowledge_push_feedback_reason_present"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "push_id", "actor_user_id", name="uq_knowledge_feedback_actor"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "push_id"],
            ["cehub_memory.knowledge_pushes.tenant_id", "cehub_memory.knowledge_pushes.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_feedback_push",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_feedback_actor",
        ),
        schema="cehub_memory",
    )
    op.execute("""
CREATE FUNCTION cehub_memory.guard_knowledge_feedback() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP <> 'INSERT' THEN
  RAISE EXCEPTION 'Knowledge use receipts are immutable' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM cehub_memory.knowledge_pushes p
  JOIN cehub_memory.memories m ON m.tenant_id=p.tenant_id AND m.id=p.memory_id
  WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.push_id
   AND m.status='verified' AND m.content_sha256=NEW.memory_content_sha256) THEN
  RAISE EXCEPTION 'Knowledge is no longer verified at this version' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_memory.guard_knowledge_feedback() FROM PUBLIC;
CREATE TRIGGER guard_knowledge_feedback BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_memory.knowledge_push_feedback FOR EACH ROW
 EXECUTE FUNCTION cehub_memory.guard_knowledge_feedback();
""")


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM cehub_memory.knowledge_push_feedback) "
            "OR EXISTS(SELECT 1 FROM cehub_memory.knowledge_pushes "
            "WHERE context_sha256 IS NOT NULL)"
        )
    ).scalar_one():
        raise RuntimeError("Refusing to discard task knowledge or use history")
    op.drop_table("knowledge_push_feedback", schema="cehub_memory")
    op.drop_constraint(
        "uq_knowledge_pushes_context_memory", "knowledge_pushes", schema="cehub_memory"
    )
    op.create_unique_constraint(
        "uq_knowledge_pushes_context_memory",
        "knowledge_pushes",
        ["tenant_id", "context_kind", "context_entity_id", "memory_id"],
        schema="cehub_memory",
    )
    op.drop_column("knowledge_pushes", "context_sha256", schema="cehub_memory")
    op.execute("DROP FUNCTION cehub_memory.guard_knowledge_feedback()")
    op.drop_constraint(
        op.f("ck_knowledge_pushes_context_kind_allowed"), "knowledge_pushes", schema="cehub_memory"
    )
    op.create_check_constraint(
        op.f("ck_knowledge_pushes_context_kind_allowed"),
        "knowledge_pushes",
        "context_kind IN ('project_kickoff', 'change_request', 'part_selection')",
        schema="cehub_memory",
    )
