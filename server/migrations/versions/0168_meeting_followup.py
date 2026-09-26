"""Link meeting agendas to actual execution without duplicating later actions."""

import sqlalchemy as sa
from alembic import op

revision = "0168_meeting_followup"
down_revision = "0167_meeting_preparation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meeting_agenda_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("agenda_item_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("relation_kind", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "relation_kind IN ('created','linked','carried')",
            name=op.f("ck_meeting_agenda_actions_relation_allowed"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "agenda_item_id", "task_id", name="uq_meeting_agenda_task"
        ),
        sa.UniqueConstraint(
            "tenant_id", "created_by_user_id", "request_id", name="uq_meeting_action_request"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "meeting_id"],
            ["cehub_project.meetings.tenant_id", "cehub_project.meetings.id"],
            name="fk_meeting_action_meeting",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agenda_item_id"],
            [
                "cehub_project.meeting_agenda_items.tenant_id",
                "cehub_project.meeting_agenda_items.id",
            ],
            name="fk_meeting_action_agenda",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["cehub_project.tasks.tenant_id", "cehub_project.tasks.id"],
            name="fk_meeting_action_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_meeting_action_actor",
            ondelete="RESTRICT",
        ),
        schema="cehub_project",
    )
    op.create_index(
        "ix_meeting_actions_project",
        "meeting_agenda_actions",
        ["tenant_id", "project_id", "meeting_id"],
        schema="cehub_project",
    )
    op.execute("""
CREATE FUNCTION cehub_project.guard_meeting_agenda_action() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Meeting execution origins are retained' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_project.meetings m
  JOIN cehub_project.meeting_agenda_items a ON a.tenant_id=m.tenant_id AND a.meeting_id=m.id
  JOIN cehub_project.tasks t ON t.tenant_id=m.tenant_id AND t.project_id=m.project_id
  WHERE m.tenant_id=NEW.tenant_id AND m.project_id=NEW.project_id AND m.id=NEW.meeting_id
   AND a.id=NEW.agenda_item_id AND t.id=NEW.task_id
   AND (NEW.relation_kind<>'created' OR (t.kind='meeting_action'
    AND t.source_entity='meetings' AND t.source_entity_id=m.id))) THEN
  RAISE EXCEPTION 'Execution link must bind this project and actual meeting agenda'
   USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_project.guard_meeting_agenda_action() FROM PUBLIC;
CREATE TRIGGER guard_meeting_agenda_action BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_project.meeting_agenda_actions FOR EACH ROW
 EXECUTE FUNCTION cehub_project.guard_meeting_agenda_action();
""")


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.meeting_agenda_actions)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard meeting execution origins")
    op.drop_table("meeting_agenda_actions", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_meeting_agenda_action()")
