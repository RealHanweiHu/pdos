# ruff: noqa: E501
"""Source-bound preproject dialogue and immutable human confirmation receipts."""

from alembic import op
from sqlalchemy import text
from sqlalchemy.schema import CreateTable

revision = "0428_preproject_dialogue"
down_revision = "0427_category_reference_aliases"
branch_labels = None
depends_on = None

GUARD = """
CREATE FUNCTION cehub_ai.guard_preproject_confirmation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r cehub_ai.agent_runs%ROWTYPE; m cehub_ai.conversation_messages%ROWTYPE;
 c cehub_ai.conversations%ROWTYPE;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Preproject confirmation is immutable'; END IF;
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;
 SELECT * INTO m FROM cehub_ai.conversation_messages WHERE tenant_id=NEW.tenant_id AND id=NEW.message_id;
 SELECT * INTO c FROM cehub_ai.conversations WHERE tenant_id=NEW.tenant_id AND id=NEW.conversation_id;
 IF r.id IS NULL OR m.id IS NULL OR c.id IS NULL OR m.conversation_id<>c.id
 OR m.author_user_id<>NEW.actor_user_id OR c.created_by_user_id<>NEW.actor_user_id
 OR c.visibility<>'private' OR c.archived_at IS NOT NULL OR m.preproject_goal IS DISTINCT FROM NEW.goal
 OR r.requested_by_user_id<>NEW.actor_user_id OR r.context_version<>'xiaopai-conversation-v1'
 OR r.status<>'succeeded' OR r.run_context->'reply_source'->>'message_id' IS DISTINCT FROM m.id::text
 OR r.run_context->'reply_result'->'preproject'->>'goal' IS DISTINCT FROM NEW.goal
 OR r.run_context->'reply_result'->'preproject'->>'stage' IS DISTINCT FROM 'ready'
 OR r.run_context->'reply_result'->'preproject'->>'candidate_digest' IS DISTINCT FROM NEW.candidate_digest
 OR (NEW.goal='category' AND c.scope_kind<>'personal')
 OR (NEW.goal='proposal' AND c.market_space_id IS DISTINCT FROM NEW.category_id)
 OR (NEW.goal='proposal' AND NEW.public_data<>'{}'::jsonb)
 OR (NEW.goal='category' AND NOT EXISTS (SELECT 1 FROM cehub_product.market_spaces s
     WHERE s.tenant_id=NEW.tenant_id AND s.id=NEW.category_id AND s.owner_user_id=NEW.actor_user_id))
 OR (NEW.goal='proposal' AND NOT EXISTS (SELECT 1 FROM cehub_product.product_proposals p
     WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.proposal_id AND p.market_space_id=NEW.category_id AND p.owner_user_id=NEW.actor_user_id))
 THEN RAISE EXCEPTION 'Preproject confirmation requires its fixed private candidate and human'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER preproject_confirmation_guard BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_ai.preproject_confirmations FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_preproject_confirmation();
REVOKE ALL ON cehub_ai.preproject_confirmations FROM PUBLIC,pdos_agent;
REVOKE ALL ON FUNCTION cehub_ai.guard_preproject_confirmation() FROM PUBLIC,pdos_agent;
"""


def upgrade() -> None:
    from app.db.schema import tables

    op.execute("ALTER TABLE cehub_ai.conversation_messages ADD COLUMN preproject_goal varchar(16)")
    op.execute(
        "ALTER TABLE cehub_ai.conversation_messages ADD CONSTRAINT ck_conversation_messages_preproject_goal CHECK (preproject_goal IS NULL OR (project_id IS NULL AND action='note' AND preproject_goal IN ('category','proposal')))"
    )
    op.execute(
        str(CreateTable(tables.preproject_confirmations).compile(dialect=op.get_bind().dialect))
    )
    op.execute(GUARD)


def downgrade() -> None:
    c = op.get_bind()
    if c.execute(
        text(
            "SELECT EXISTS(SELECT 1 FROM cehub_ai.preproject_confirmations) OR EXISTS(SELECT 1 FROM cehub_ai.conversation_messages WHERE preproject_goal IS NOT NULL)"
        )
    ).scalar_one():
        raise RuntimeError("Preproject dialogue history must be preserved")
    op.execute("DROP TABLE cehub_ai.preproject_confirmations")
    op.execute("DROP FUNCTION cehub_ai.guard_preproject_confirmation()")
    op.execute(
        "ALTER TABLE cehub_ai.conversation_messages DROP CONSTRAINT ck_conversation_messages_preproject_goal"
    )
    op.execute("ALTER TABLE cehub_ai.conversation_messages DROP COLUMN preproject_goal")
