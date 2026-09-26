"""Keep creator history and separately bind the latest draft editor."""

import sqlalchemy as sa
from alembic import op

revision = "0163_memory_review_basis"
down_revision = "0162_knowledge_source_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("memories", sa.Column("last_edited_by_user_id", sa.Uuid()), schema="cehub_memory")
    op.create_foreign_key(
        "fk_memories_last_editor",
        "memories",
        "users",
        ["tenant_id", "last_edited_by_user_id"],
        ["tenant_id", "id"],
        source_schema="cehub_memory",
        referent_schema="cehub_core",
        ondelete="RESTRICT",
    )
    # Only pending drafts inherit an editor from actual audit history.
    # Existing published records keep their original acceptance history.
    op.execute("""UPDATE cehub_memory.memories m SET last_edited_by_user_id=(
      SELECT a.actor_user_id FROM cehub_audit.audit_log a
      WHERE a.tenant_id=m.tenant_id AND a.project_id=m.project_id
       AND a.entity='memory' AND a.entity_id=m.id AND a.action='memory.update'
      ORDER BY a.id DESC LIMIT 1) WHERE m.status='draft'""")
    op.create_check_constraint(
        op.f("ck_memories_editor_four_eyes"),
        "memories",
        "last_edited_by_user_id IS NULL OR verified_by_user_id IS NULL OR "
        "last_edited_by_user_id <> verified_by_user_id",
        schema="cehub_memory",
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_memory.memories "
                "WHERE last_edited_by_user_id IS NOT NULL)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard draft-editor review provenance")
    op.drop_constraint(op.f("ck_memories_editor_four_eyes"), "memories", schema="cehub_memory")
    op.drop_constraint("fk_memories_last_editor", "memories", schema="cehub_memory")
    op.drop_column("memories", "last_edited_by_user_id", schema="cehub_memory")
