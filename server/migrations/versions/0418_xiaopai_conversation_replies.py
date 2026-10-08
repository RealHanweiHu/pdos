"""Source-bound multi-turn replies without granting any business write capability."""

# ruff: noqa: E501
import json

from alembic import op
from sqlalchemy import String, literal, text

revision = "0418_xiaopai_conversation_replies"
down_revision = "0417_product_manager_role"
branch_labels = None
depends_on = None

SHAPE = """context_version='xiaopai-conversation-v1' AND agent_key='ai_chat'
 AND market_space_id IS NULL AND ((scope_kind='tenant' AND project_id IS NULL)
 OR (scope_kind='project' AND project_id IS NOT NULL))
 AND subscription_id IS NULL AND first_event_row_id IS NULL AND last_event_row_id IS NULL
 AND event_count=0 AND event_row_ids='[]'::jsonb AND request_id IS NOT NULL
 AND requested_by_user_id IS NOT NULL AND status IN ('running','succeeded','degraded','failed')"""

DDL = r"""
CREATE FUNCTION cehub_ai.guard_xiaopai_reply_run() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE s jsonb; c cehub_ai.conversations%ROWTYPE; m cehub_ai.conversation_messages%ROWTYPE;
BEGIN
 IF TG_OP='UPDATE' AND OLD.context_version='xiaopai-conversation-v1'
 AND NEW.context_version IS DISTINCT FROM OLD.context_version THEN
  RAISE EXCEPTION 'Conversation reply version is immutable'; END IF;
 IF NEW.context_version<>'xiaopai-conversation-v1' THEN RETURN NEW; END IF;
 s:=NEW.run_context->'reply_source';
 SELECT * INTO c FROM cehub_ai.conversations WHERE tenant_id=NEW.tenant_id
  AND id=(s->>'conversation_id')::uuid;
 SELECT * INTO m FROM cehub_ai.conversation_messages WHERE tenant_id=NEW.tenant_id
  AND conversation_id=c.id AND id=(s->>'message_id')::uuid;
 IF c.id IS NULL OR m.id IS NULL OR NEW.requested_by_user_id IS DISTINCT FROM m.author_user_id
  OR NEW.project_id IS DISTINCT FROM c.project_id OR NEW.agent_key<>'ai_chat'
  OR s->>'actor_id' IS DISTINCT FROM NEW.requested_by_user_id::text
  OR s->>'question' IS DISTINCT FROM m.body OR (s->>'context_version')::int<>c.context_version
  OR coalesce(s->>'digest','') !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'Reply requires its fixed conversation message and actor'; END IF;
 IF TG_OP='INSERT' AND (c.archived_at IS NOT NULL
  OR NOT cehub_ai.conversation_actor_allowed(c.tenant_id,c.project_id,c.created_by_user_id,
    c.visibility,NEW.requested_by_user_id)
  OR (c.market_space_id IS NOT NULL AND NOT cehub_ai.require_product_conversation_actor(
    c.tenant_id,c.market_space_id,c.product_line_id,NEW.requested_by_user_id))) THEN
  RAISE EXCEPTION 'Reply conversation is not currently authorized'; END IF;
 IF TG_OP='UPDATE' AND (NEW.id,NEW.tenant_id,NEW.project_id,NEW.scope_kind,NEW.market_space_id,
   NEW.agent_key,NEW.request_id,NEW.requested_by_user_id,NEW.run_context->'reply_source')
  IS DISTINCT FROM (OLD.id,OLD.tenant_id,OLD.project_id,OLD.scope_kind,OLD.market_space_id,
   OLD.agent_key,OLD.request_id,OLD.requested_by_user_id,OLD.run_context->'reply_source') THEN
  RAISE EXCEPTION 'Reply scope and source are immutable'; END IF;
 IF TG_OP='UPDATE' AND OLD.status<>'running' AND NEW IS DISTINCT FROM OLD THEN
  RAISE EXCEPTION 'Completed reply is immutable'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_xiaopai_reply_run() FROM PUBLIC;
CREATE TRIGGER guard_xiaopai_reply_run BEFORE INSERT OR UPDATE ON cehub_ai.agent_runs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_xiaopai_reply_run();

ALTER FUNCTION cehub_ai.application_authorization_is_current(uuid)
 RENAME TO application_pre_xiaopai_reply_authorization_is_current;
CREATE FUNCTION cehub_ai.application_authorization_is_current(wanted_run uuid)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cehub_ai.agent_runs
  WHERE id=wanted_run AND context_version='xiaopai-conversation-v1') THEN EXISTS(
  SELECT 1 FROM cehub_ai.agent_runs r
  JOIN cehub_ai.application_authorizations a ON a.tenant_id=r.tenant_id AND a.run_id=r.id
  JOIN cehub_core.users u ON u.tenant_id=r.tenant_id AND u.id=a.principal_id
  JOIN cehub_core.tenants t ON t.id=r.tenant_id
  JOIN cehub_ai.conversations c ON c.tenant_id=r.tenant_id
    AND c.id::text=r.run_context->'reply_source'->>'conversation_id'
  JOIN cehub_ai.conversation_messages m ON m.tenant_id=c.tenant_id AND m.conversation_id=c.id
    AND m.id::text=r.run_context->'reply_source'->>'message_id'
  WHERE r.id=wanted_run AND r.agent_key='ai_chat' AND r.status='running'
   AND r.requested_by_user_id=a.principal_id AND m.author_user_id=a.principal_id
   AND r.project_id IS NOT DISTINCT FROM c.project_id
   AND a.project_id IS NOT DISTINCT FROM c.project_id
   AND u.is_active AND t.status='active' AND c.archived_at IS NULL
   AND u.role IN ('owner','admin','product_manager','project_manager','engineer','quality')
   AND a.expires_at>clock_timestamp() AND u.role=a.pins->>'role'
   AND u.auth_version=(a.pins->>'auth_version')::integer
   AND a.pins->>'action'='ai_chat.use'
   AND a.body->>'purpose'='xiaopai_reply'
   AND a.body->>'principal_id'=u.id::text AND a.body->>'run_id'=r.id::text
   AND a.body->>'tenant_id'=r.tenant_id::text
   AND a.body->'scope'=CASE WHEN c.project_id IS NOT NULL THEN
     jsonb_build_object('kind','project','ref_id',c.project_id::text) ELSE
     jsonb_build_object('kind','tenant','ref_id',c.tenant_id::text) END
   AND jsonb_array_length(a.body->'sources')=1
   AND a.body->'sources' @> jsonb_build_array(jsonb_build_object('kind','conversation_message',
     'ref_id',m.id::text,'tenant_id',r.tenant_id::text,
     'digest',r.run_context->'reply_source'->>'digest'))
   AND cehub_ai.conversation_actor_allowed(c.tenant_id,c.project_id,c.created_by_user_id,
     c.visibility,u.id)
   AND (c.market_space_id IS NULL OR cehub_ai.require_product_conversation_actor(
     c.tenant_id,c.market_space_id,c.product_line_id,u.id))
 ) ELSE cehub_ai.application_pre_xiaopai_reply_authorization_is_current(wanted_run) END;
$$;
REVOKE ALL ON FUNCTION cehub_ai.application_authorization_is_current(uuid) FROM PUBLIC;
"""


def constraints(add: bool) -> None:
    c = op.get_bind()
    for name in ("scope", "event_bounds_consistent"):
        full = "ck_agent_runs_" + name
        old = c.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='cehub_ai.agent_runs'::regclass AND conname=:name"
            ),
            {"name": full},
        ).scalar_one()
        prior_comment = c.execute(
            text(
                "SELECT obj_description(oid,'pg_constraint') FROM pg_constraint WHERE conrelid='cehub_ai.agent_runs'::regclass AND conname=:name"
            ),
            {"name": full},
        ).scalar_one()
        original = old if add else prior_comment
        if not add and original and original.startswith("{"):
            saved = json.loads(original)
            original, prior_comment = saved["definition"], saved["comment"]
        if not original or not original.startswith("CHECK ("):
            raise RuntimeError("Original reply-run constraint is unavailable")
        expression = original.removeprefix("CHECK (").removesuffix(")")
        if add:
            expression = f"({expression}) OR ({SHAPE}) IS TRUE"
        op.execute(f"ALTER TABLE cehub_ai.agent_runs DROP CONSTRAINT {full}")
        op.execute(f"ALTER TABLE cehub_ai.agent_runs ADD CONSTRAINT {full} CHECK ({expression})")
        if add:
            encoded = str(
                literal(
                    json.dumps({"definition": old, "comment": prior_comment}), type_=String()
                ).compile(dialect=c.dialect, compile_kwargs={"literal_binds": True})
            )
            op.execute(f"COMMENT ON CONSTRAINT {full} ON cehub_ai.agent_runs IS {encoded}")
        elif prior_comment and prior_comment != original:
            encoded = str(
                literal(prior_comment, type_=String()).compile(
                    dialect=c.dialect, compile_kwargs={"literal_binds": True}
                )
            )
            op.execute(f"COMMENT ON CONSTRAINT {full} ON cehub_ai.agent_runs IS {encoded}")


def template_guard(add: bool) -> None:
    c = op.get_bind()
    definition = c.execute(
        text("SELECT pg_get_functiondef('cehub_ai.guard_tenant_template_run()'::regprocedure)")
    ).scalar_one()
    old = "IF NEW.scope_kind<>'tenant' THEN RETURN NEW; END IF;"
    new = "IF NEW.scope_kind<>'tenant' OR NEW.context_version='xiaopai-conversation-v1' THEN RETURN NEW; END IF;"
    assert (old if add else new) in definition
    op.execute(definition.replace(old if add else new, new if add else old, 1))


def upgrade() -> None:
    constraints(True)
    template_guard(True)
    op.execute(DDL)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs WHERE context_version='xiaopai-conversation-v1') THEN RAISE EXCEPTION 'Retain conversation replies and budgets'; END IF; END $$;"
    )
    op.execute("DROP FUNCTION cehub_ai.application_authorization_is_current(uuid)")
    op.execute(
        "ALTER FUNCTION cehub_ai.application_pre_xiaopai_reply_authorization_is_current(uuid) RENAME TO application_authorization_is_current"
    )
    op.execute("DROP TRIGGER guard_xiaopai_reply_run ON cehub_ai.agent_runs")
    op.execute("DROP FUNCTION cehub_ai.guard_xiaopai_reply_run()")
    template_guard(False)
    constraints(False)
