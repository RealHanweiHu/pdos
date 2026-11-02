"""Immutable server-owned conversation-to-proposal bindings."""
# ruff: noqa: E501

from migrations.schema_s0_0793 import SCHEMA_SQL as PREVIOUS_SCHEMA_SQL

PREVIOUS_RUN_GUARD = next(
    statement for statement in PREVIOUS_SCHEMA_SQL
    if "CREATE OR REPLACE FUNCTION public.kernel_run_guard()" in statement
)

TABLE_SQL = """CREATE TABLE public.agent_session_bindings (
 session_id UUID NOT NULL,
 owner_id UUID NOT NULL,
 category_id UUID NOT NULL,
 proposal_id UUID NOT NULL,
 receipt_id UUID NOT NULL,
 id UUID NOT NULL,
 tenant_id UUID NOT NULL,
 created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 PRIMARY KEY (id),
 UNIQUE (tenant_id, id),
 UNIQUE (tenant_id, session_id),
 UNIQUE (tenant_id, receipt_id),
 FOREIGN KEY (tenant_id, session_id) REFERENCES public.agent_sessions (tenant_id, id),
 FOREIGN KEY (tenant_id, owner_id) REFERENCES public.principals (tenant_id, id),
 FOREIGN KEY (tenant_id, category_id, proposal_id) REFERENCES public.proposals (tenant_id, category_id, id),
 FOREIGN KEY (tenant_id, receipt_id) REFERENCES public.action_receipts (tenant_id, id)
)"""

INDEX_SQL = "CREATE INDEX ix_agent_session_bindings_tenant_id ON public.agent_session_bindings (tenant_id)"

SCOPE_SQL = """tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
 AND owner_id=scope_requester() AND scope_actor()=scope_requester()
 AND EXISTS(SELECT 1 FROM principals a WHERE a.tenant_id=agent_session_bindings.tenant_id
   AND a.id=scope_actor() AND a.active)
 AND EXISTS(SELECT 1 FROM principals a WHERE a.tenant_id=agent_session_bindings.tenant_id
   AND a.id=scope_requester() AND a.active)
 AND EXISTS(SELECT 1 FROM agent_sessions s WHERE s.tenant_id=agent_session_bindings.tenant_id
   AND s.id=agent_session_bindings.session_id AND s.owner_id=agent_session_bindings.owner_id
   AND (s.category_id IS NULL OR category_access(s.tenant_id,s.category_id)))
 AND EXISTS(SELECT 1 FROM agent_sessions s JOIN proposals p ON p.tenant_id=s.tenant_id
   AND p.category_id=s.category_id WHERE s.tenant_id=agent_session_bindings.tenant_id
   AND s.id=agent_session_bindings.session_id AND p.id=agent_session_bindings.proposal_id)"""

READ_SCOPE_SQL = SCOPE_SQL.replace(" AND scope_actor()=scope_requester()", "")
POLICY_SQL = f"""CREATE POLICY session_binding_scope ON public.agent_session_bindings
 USING ({READ_SCOPE_SQL}) WITH CHECK ({SCOPE_SQL})"""

TRIGGER_SQL = """CREATE TRIGGER session_binding_append BEFORE UPDATE OR DELETE
 ON public.agent_session_bindings FOR EACH ROW EXECUTE FUNCTION kernel_append_only()"""

REPLACEMENT = "COALESCE((SELECT b.proposal_id FROM public.agent_session_bindings b WHERE b.tenant_id=s.tenant_id AND b.session_id=s.id), s.proposal_id)"
assert PREVIOUS_RUN_GUARD.count("s.proposal_id IS DISTINCT FROM NEW.proposal_id") == 1
RUN_GUARD = PREVIOUS_RUN_GUARD.replace(
    "s.proposal_id IS DISTINCT FROM NEW.proposal_id",
    f"{REPLACEMENT} IS DISTINCT FROM NEW.proposal_id",
)

PREVIOUS_CONTINUATION_GUARD = """CREATE OR REPLACE FUNCTION kernel_continuation_guard() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE p agent_runs; BEGIN
  IF TG_OP='UPDATE' THEN
    IF NEW.continued_from_id IS DISTINCT FROM OLD.continued_from_id THEN
      RAISE EXCEPTION 'Continuation binding immutable' USING ERRCODE='23514';
    END IF;
  ELSIF NEW.continued_from_id IS NOT NULL THEN
    SELECT * INTO p FROM agent_runs WHERE tenant_id=NEW.tenant_id
      AND id=NEW.continued_from_id FOR UPDATE;
    IF p.id IS NULL OR p.id=NEW.id OR p.requester_id<>NEW.requester_id
      OR p.session_id<>NEW.session_id OR p.category_id IS DISTINCT FROM NEW.category_id
      OR p.product_id IS DISTINCT FROM NEW.product_id
      OR p.proposal_id IS DISTINCT FROM NEW.proposal_id OR p.reverted_at IS NOT NULL
      OR p.state NOT IN ('completed','partial','failed','cancelled') THEN
      RAISE EXCEPTION 'Continuation requires same actual completed scope'
        USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$"""
CONTINUATION_CONDITION = """(p.proposal_id IS NOT NULL AND p.proposal_id IS DISTINCT FROM NEW.proposal_id)
      OR (p.proposal_id IS NULL AND NEW.proposal_id IS NOT NULL AND NOT EXISTS(
        SELECT 1 FROM public.agent_session_bindings b WHERE b.tenant_id=NEW.tenant_id
          AND b.session_id=NEW.session_id AND b.proposal_id=NEW.proposal_id))"""
assert PREVIOUS_CONTINUATION_GUARD.count("p.proposal_id IS DISTINCT FROM NEW.proposal_id") == 1
CONTINUATION_GUARD = PREVIOUS_CONTINUATION_GUARD.replace(
    "p.proposal_id IS DISTINCT FROM NEW.proposal_id",
    CONTINUATION_CONDITION,
)

SCHEMA_SQL = [
    TABLE_SQL,
    INDEX_SQL,
    "ALTER TABLE public.agent_session_bindings ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.agent_session_bindings FORCE ROW LEVEL SECURITY",
    POLICY_SQL,
    "REVOKE ALL ON public.agent_session_bindings FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch",
    "GRANT SELECT,INSERT ON public.agent_session_bindings TO pdos_next_app",
    TRIGGER_SQL,
]

GUARD_SQL = [RUN_GUARD, CONTINUATION_GUARD]
HISTORY_GUARD_SQL = """DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.agent_session_bindings)
 OR EXISTS(SELECT 1 FROM public.agent_runs child JOIN public.agent_runs parent
  ON parent.tenant_id=child.tenant_id AND parent.id=child.continued_from_id
  WHERE parent.proposal_id IS NULL AND child.proposal_id IS NOT NULL) THEN
  RAISE EXCEPTION 'Session binding history requires s0_0823';
 END IF;
END $$"""
DOWNGRADE_GUARD_SQL = [HISTORY_GUARD_SQL, PREVIOUS_RUN_GUARD, PREVIOUS_CONTINUATION_GUARD]
DOWNGRADE_SQL = [
    "DROP TRIGGER IF EXISTS session_binding_append ON public.agent_session_bindings",
    "DROP TABLE IF EXISTS public.agent_session_bindings",
]
