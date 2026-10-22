"""Private append-only Session presentation; never mutate a Run or business fact."""

# ruff: noqa: E501 -- Reviewed applied SQL literals remain byte-identical.

# Filled from the exact reviewed ORM table before the version migration is added.
TABLE_SQL = ("CREATE TABLE agent_session_presentations (\n\tsession_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tprevious_id UUID, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\taction VARCHAR(16) NOT NULL, \n\ttitle VARCHAR(160), \n\tpinned BOOLEAN NOT NULL, \n\tarchived BOOLEAN NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, session_id, revision), \n\tUNIQUE (tenant_id, owner_id, request_key), \n\tFOREIGN KEY(tenant_id, session_id) REFERENCES agent_sessions (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, previous_id) REFERENCES agent_session_presentations (tenant_id, id), \n\tCONSTRAINT session_presentation_revision CHECK (revision > 0), \n\tCONSTRAINT session_presentation_action CHECK (action IN ('rename', 'pin', 'unpin', 'archive', 'restore')), \n\tCONSTRAINT session_presentation_request_sha256 CHECK (request_sha256 ~ '^[0-9a-f]{64}$'), \n\tCONSTRAINT session_presentation_title CHECK (title IS NULL OR char_length(title) BETWEEN 1 AND 160), \n\tCONSTRAINT session_presentation_previous CHECK ((revision = 1) = (previous_id IS NULL))\n)", 'CREATE INDEX ix_agent_session_presentations_tenant_id ON agent_session_presentations (tenant_id)')

INSERT_GUARD_SQL = """
CREATE FUNCTION public.guard_session_presentation_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path TO pg_catalog, public, pg_temp AS $$
DECLARE
 previous public.agent_session_presentations%ROWTYPE;
 session_owner uuid;
 prior_title text;
 prior_pinned boolean := false;
 prior_archived boolean := false;
BEGIN
 IF NEW.tenant_id IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
  OR NEW.owner_id IS DISTINCT FROM public.scope_requester()
  OR public.scope_actor() IS DISTINCT FROM public.scope_requester()
  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=NEW.tenant_id
    AND h.id=NEW.owner_id AND h.kind='human' AND h.active) THEN
  RAISE EXCEPTION 'Session presentation requires the actual human owner' USING ERRCODE='42501';
 END IF;
 SELECT s.owner_id INTO session_owner FROM public.agent_sessions s
  WHERE s.tenant_id=NEW.tenant_id AND s.id=NEW.session_id
   AND s.category_id IS NOT DISTINCT FROM nullif(current_setting('pdos.category_id',true),'')::uuid;
 IF session_owner IS DISTINCT FROM NEW.owner_id THEN
  RAISE EXCEPTION 'Session parent is not currently readable by its owner' USING ERRCODE='42501';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(
  'session-presentation:'||NEW.tenant_id::text||':'||NEW.session_id::text,0));
 SELECT * INTO previous FROM public.agent_session_presentations p
  WHERE p.tenant_id=NEW.tenant_id AND p.session_id=NEW.session_id
  ORDER BY p.revision DESC LIMIT 1;
 IF previous.id IS NULL THEN
  IF NEW.revision<>1 OR NEW.previous_id IS NOT NULL THEN
   RAISE EXCEPTION 'First presentation revision must be one' USING ERRCODE='23514';
  END IF;
 ELSE
  IF NEW.revision<>previous.revision+1 OR NEW.previous_id IS DISTINCT FROM previous.id
   OR NEW.owner_id IS DISTINCT FROM previous.owner_id THEN
   RAISE EXCEPTION 'Presentation must append to its exact current predecessor' USING ERRCODE='23514';
  END IF;
  prior_title=previous.title; prior_pinned=previous.pinned; prior_archived=previous.archived;
 END IF;
 IF (NEW.action='rename' AND (NEW.pinned IS DISTINCT FROM prior_pinned OR NEW.archived IS DISTINCT FROM prior_archived))
  OR (NEW.action='pin' AND (NEW.title IS DISTINCT FROM prior_title OR NOT NEW.pinned OR NEW.archived IS DISTINCT FROM prior_archived))
  OR (NEW.action='unpin' AND (NEW.title IS DISTINCT FROM prior_title OR NEW.pinned OR NEW.archived IS DISTINCT FROM prior_archived))
  OR (NEW.action='archive' AND (NEW.title IS DISTINCT FROM prior_title OR NEW.pinned IS DISTINCT FROM prior_pinned OR NOT NEW.archived))
  OR (NEW.action='restore' AND (NEW.title IS DISTINCT FROM prior_title OR NEW.pinned IS DISTINCT FROM prior_pinned OR NEW.archived)) THEN
  RAISE EXCEPTION 'Presentation action changed unrelated display state' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END;
$$
"""

IMMUTABLE_SQL = """
CREATE FUNCTION public.reject_session_presentation_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path TO pg_catalog, public, pg_temp AS $$
BEGIN
 RAISE EXCEPTION 'Session presentation history is append only' USING ERRCODE='23514';
END;
$$
"""

_VISIBLE = """tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid
 AND owner_id=public.scope_requester() AND public.scope_actor()=public.scope_requester()
 AND EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=agent_session_presentations.tenant_id
  AND h.id=agent_session_presentations.owner_id AND h.kind='human' AND h.active)
 AND EXISTS(SELECT 1 FROM public.agent_sessions s
  WHERE s.tenant_id=agent_session_presentations.tenant_id AND s.id=agent_session_presentations.session_id
   AND s.owner_id=agent_session_presentations.owner_id
   AND s.category_id IS NOT DISTINCT FROM nullif(current_setting('pdos.category_id',true),'')::uuid)"""

SECURITY_SQL = (
    INSERT_GUARD_SQL,
    IMMUTABLE_SQL,
    "CREATE TRIGGER session_presentation_insert BEFORE INSERT ON public.agent_session_presentations "
    "FOR EACH ROW EXECUTE FUNCTION public.guard_session_presentation_insert()",
    "CREATE TRIGGER session_presentation_immutable BEFORE UPDATE OR DELETE ON public.agent_session_presentations "
    "FOR EACH ROW EXECUTE FUNCTION public.reject_session_presentation_mutation()",
    "ALTER TABLE public.agent_session_presentations ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.agent_session_presentations FORCE ROW LEVEL SECURITY",
    "CREATE POLICY owner_internal ON public.agent_session_presentations TO pdos_next_owner USING(true) WITH CHECK(true)",
    f"CREATE POLICY presentation_read ON public.agent_session_presentations FOR SELECT TO pdos_next_app USING({_VISIBLE})",
    f"CREATE POLICY presentation_insert ON public.agent_session_presentations FOR INSERT TO pdos_next_app WITH CHECK({_VISIBLE})",
    "REVOKE ALL ON public.agent_session_presentations FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch",
    "GRANT SELECT,INSERT ON public.agent_session_presentations TO pdos_next_app",
    "REVOKE ALL ON FUNCTION public.guard_session_presentation_insert() FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch",
    "REVOKE ALL ON FUNCTION public.reject_session_presentation_mutation() FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch",
)

SCHEMA_SQL = (*TABLE_SQL, *SECURITY_SQL)
DOWNGRADE_SQL = (
    "DROP TRIGGER session_presentation_immutable ON public.agent_session_presentations",
    "DROP TRIGGER session_presentation_insert ON public.agent_session_presentations",
    "DROP FUNCTION public.reject_session_presentation_mutation()",
    "DROP FUNCTION public.guard_session_presentation_insert()",
    "DROP TABLE public.agent_session_presentations",
)
