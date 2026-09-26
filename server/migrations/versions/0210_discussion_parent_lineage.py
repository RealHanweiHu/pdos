"""Related discussions preserve the original actor, topic and shared budget."""

import sqlalchemy as sa
from alembic import op

revision = "0210_discussion_parent_lineage"
down_revision = "0209_project_discussion_topics"
branch_labels = None
depends_on = None

GUARD = """
CREATE FUNCTION cehub_ai.guard_discussion_parent_lineage() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.parent_run_id IS NULL THEN RETURN NEW; END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings p
 JOIN cehub_ai.agent_runs pr ON pr.tenant_id=p.tenant_id AND pr.id=p.run_id
 JOIN cehub_ai.agent_runs cr ON cr.tenant_id=NEW.tenant_id AND cr.id=NEW.run_id
 JOIN cehub_ai.budget_run_links pl ON pl.tenant_id=pr.tenant_id AND pl.run_id=pr.id
 JOIN cehub_ai.budget_run_links cl ON cl.tenant_id=cr.tenant_id AND cl.run_id=cr.id
 WHERE p.tenant_id=NEW.tenant_id AND p.run_id=NEW.parent_run_id
 AND p.project_id=NEW.project_id AND p.topic_kind=NEW.topic_kind
 AND p.ecr_id IS NOT DISTINCT FROM NEW.ecr_id
 AND pr.requested_by_user_id=cr.requested_by_user_id
 AND pr.status NOT IN ('queued','running','waiting_input')
 AND NOT coalesce((pr.run_context->>'discussion_recovery_requested')::boolean,false)
 AND pl.lineage_id=cl.lineage_id
 AND NEW.config->'request'->>'parent_run_id'=NEW.parent_run_id::text
 AND length(btrim(NEW.config->'request'->>'followup_reason'))>0) THEN
 RAISE EXCEPTION 'related discussion requires original topic actor and budget lineage'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER guard_discussion_parent_lineage AFTER INSERT
 ON cehub_ai.debate_run_bindings DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
 EXECUTE FUNCTION cehub_ai.guard_discussion_parent_lineage();
REVOKE ALL ON FUNCTION cehub_ai.guard_discussion_parent_lineage() FROM PUBLIC;
"""


def upgrade() -> None:
    op.add_column("debate_run_bindings", sa.Column("parent_run_id", sa.Uuid()), schema="cehub_ai")
    op.create_foreign_key(
        "fk_debate_binding_parent",
        "debate_run_bindings",
        "debate_run_bindings",
        ["tenant_id", "parent_run_id"],
        ["tenant_id", "run_id"],
        source_schema="cehub_ai",
        referent_schema="cehub_ai",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_debate_run_bindings_parent_not_self"),
        "debate_run_bindings",
        "parent_run_id IS NULL OR parent_run_id <> run_id",
        schema="cehub_ai",
    )
    op.execute(sa.text(GUARD))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_ai.debate_run_bindings "
                "WHERE parent_run_id IS NOT NULL)"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to discard discussion lineage history")
    op.execute("DROP TRIGGER guard_discussion_parent_lineage ON cehub_ai.debate_run_bindings")
    op.execute("DROP FUNCTION cehub_ai.guard_discussion_parent_lineage()")
    op.drop_constraint("fk_debate_binding_parent", "debate_run_bindings", schema="cehub_ai")
    op.drop_constraint(
        op.f("ck_debate_run_bindings_parent_not_self"), "debate_run_bindings", schema="cehub_ai"
    )
    op.drop_column("debate_run_bindings", "parent_run_id", schema="cehub_ai")
