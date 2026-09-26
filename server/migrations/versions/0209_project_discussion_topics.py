"""General project topics reuse the frozen discussion execution and receipt chain."""

import sqlalchemy as sa
from alembic import op

revision = "0209_project_discussion_topics"
down_revision = "0208_discussion_resume"
branch_labels = None
depends_on = None

OLD_GUARD = """
CREATE OR REPLACE FUNCTION cehub_ai.guard_debate_binding() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.agent_runs r JOIN cehub_ai.debate_sessions s
 ON s.tenant_id=r.tenant_id AND s.id=NEW.session_id
 WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.run_id AND r.project_id=NEW.project_id
 AND s.project_id=NEW.project_id AND s.topic_entity='engineering_change_request'
 AND s.topic_entity_id=NEW.ecr_id AND s.initiated_by_user_id=r.requested_by_user_id
 AND r.context_version='change-discussion-request-v1'
 AND r.run_context->>'debate_session_id'=NEW.session_id::text
 AND r.run_context->>'discussion_source_digest'=NEW.source->>'digest') THEN
 RAISE EXCEPTION 'discussion binding does not match original run and topic'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""
NEW_GUARD = OLD_GUARD.replace(
    "s.topic_entity='engineering_change_request'\n AND s.topic_entity_id=NEW.ecr_id",
    """s.topic_entity=NEW.topic_kind
 AND ((NEW.topic_kind='engineering_change_request' AND s.topic_entity_id=NEW.ecr_id)
 OR (NEW.topic_kind='project' AND s.topic_entity_id=NEW.project_id AND NEW.ecr_id IS NULL
 AND NEW.source->>'source_kind'='project_discussion'
 AND NEW.source->>'topic_id'=NEW.project_id::text
 AND NEW.source->>'actor_id'=r.requested_by_user_id::text))""",
)
TOPICS = (
    "'engineering_change_request','gate','issue','customer_change_request',"
    "'requirement','specification','product_definition','meeting','risk'"
)


def upgrade() -> None:
    op.execute("ALTER TABLE cehub_ai.debate_run_bindings ALTER COLUMN ecr_id DROP NOT NULL")
    op.execute(
        "ALTER TABLE cehub_ai.debate_run_bindings ADD COLUMN topic_kind varchar(32) "
        "NOT NULL DEFAULT 'engineering_change_request'"
    )
    op.create_check_constraint(
        op.f("ck_debate_run_bindings_topic_scope"),
        "debate_run_bindings",
        "(topic_kind='engineering_change_request' AND ecr_id IS NOT NULL) OR "
        "(topic_kind='project' AND ecr_id IS NULL)",
        schema="cehub_ai",
    )
    op.drop_constraint(
        op.f("ck_debate_sessions_topic_entity_allowed"), "debate_sessions", schema="cehub_ai"
    )
    op.create_check_constraint(
        op.f("ck_debate_sessions_topic_entity_allowed"),
        "debate_sessions",
        "topic_entity IN ('project'," + TOPICS + ")",
        schema="cehub_ai",
    )
    op.execute(sa.text(NEW_GUARD))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_ai.debate_sessions WHERE topic_entity='project')"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to discard project discussion history")
    op.execute(sa.text(OLD_GUARD))
    op.drop_constraint(
        op.f("ck_debate_run_bindings_topic_scope"), "debate_run_bindings", schema="cehub_ai"
    )
    op.execute(
        "ALTER TABLE cehub_ai.debate_run_bindings DROP COLUMN topic_kind, "
        "ALTER COLUMN ecr_id SET NOT NULL"
    )
    op.drop_constraint(
        op.f("ck_debate_sessions_topic_entity_allowed"), "debate_sessions", schema="cehub_ai"
    )
    op.create_check_constraint(
        op.f("ck_debate_sessions_topic_entity_allowed"),
        "debate_sessions",
        "topic_entity IN (" + TOPICS + ")",
        schema="cehub_ai",
    )
