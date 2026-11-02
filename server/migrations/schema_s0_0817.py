"""Immutable, human-authored member messages and private reading history."""
# ruff: noqa: E501

TABLE_SQL = ('\nCREATE TABLE inbox_conversations (\n\tcategory_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tmember_ids UUID[] NOT NULL, \n\ttitle VARCHAR(160) NOT NULL, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, owner_id, request_key), \n\tFOREIGN KEY(tenant_id, category_id) REFERENCES categories (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT inbox_title CHECK (char_length(btrim(title)) BETWEEN 1 AND 160), \n\tCONSTRAINT inbox_members CHECK (cardinality(member_ids) BETWEEN 2 AND 20 AND owner_id=ANY(member_ids))\n)\n\n', 'CREATE INDEX ix_inbox_conversations_tenant_id ON inbox_conversations (tenant_id)', '\nCREATE TABLE inbox_messages (\n\tconversation_id UUID NOT NULL, \n\tsender_id UUID NOT NULL, \n\tsequence INTEGER NOT NULL, \n\tbody TEXT NOT NULL, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, conversation_id, sequence), \n\tUNIQUE (tenant_id, sender_id, request_key), \n\tFOREIGN KEY(tenant_id, conversation_id) REFERENCES inbox_conversations (tenant_id, id), \n\tFOREIGN KEY(tenant_id, sender_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT inbox_message_sequence CHECK (sequence > 0), \n\tCONSTRAINT inbox_message_body CHECK (char_length(btrim(body)) BETWEEN 1 AND 8000)\n)\n\n', 'CREATE INDEX ix_inbox_messages_tenant_id ON inbox_messages (tenant_id)', "\nCREATE TABLE inbox_states (\n\towner_id UUID NOT NULL, \n\tkind VARCHAR(16) NOT NULL, \n\ttarget_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tread_through VARCHAR(64) NOT NULL, \n\tarchived BOOLEAN NOT NULL, \n\tfollowed BOOLEAN NOT NULL, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, owner_id, kind, target_id, revision), \n\tUNIQUE (tenant_id, owner_id, request_key), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT inbox_state_kind CHECK (kind IN ('conversation','run')), \n\tCONSTRAINT inbox_state_revision CHECK (revision > 0)\n)\n\n", 'CREATE INDEX ix_inbox_states_tenant_id ON inbox_states (tenant_id)')

HUMAN = """tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid
 AND public.scope_actor()=public.scope_requester()
 AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid
 AND p.id=public.scope_actor() AND p.active AND p.kind='human')"""
CONVERSATION = f"{HUMAN} AND public.category_access(tenant_id,category_id) AND public.scope_requester()=ANY(member_ids)"
MESSAGE = f"{HUMAN} AND EXISTS(SELECT 1 FROM public.inbox_conversations c WHERE c.tenant_id=inbox_messages.tenant_id AND c.id=inbox_messages.conversation_id)"
STATE = f"""{HUMAN} AND owner_id=public.scope_requester() AND (
 (kind='conversation' AND EXISTS(SELECT 1 FROM public.inbox_conversations c WHERE c.tenant_id=inbox_states.tenant_id AND c.id=inbox_states.target_id)) OR
 (kind='run' AND EXISTS(SELECT 1 FROM public.agent_runs r WHERE r.tenant_id=inbox_states.tenant_id AND r.id=inbox_states.target_id AND r.requester_id=public.scope_requester() AND (r.proposal_id IS NULL OR EXISTS(SELECT 1 FROM public.proposals p WHERE p.tenant_id=r.tenant_id AND p.id=r.proposal_id)))))"""

GUARD = """
CREATE FUNCTION public.guard_inbox_insert() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE latest integer; current_token text;
BEGIN
 IF TG_TABLE_NAME='inbox_conversations' THEN
  IF NEW.owner_id IS DISTINCT FROM scope_actor()
   OR (SELECT count(DISTINCT u) FROM unnest(NEW.member_ids) u)<>cardinality(NEW.member_ids)
   OR EXISTS(SELECT 1 FROM unnest(NEW.member_ids) member_id WHERE NOT EXISTS(
    SELECT 1 FROM principals p JOIN grants g ON g.tenant_id=p.tenant_id AND g.principal_id=p.id
     WHERE p.tenant_id=NEW.tenant_id AND p.id=member_id AND p.kind='human' AND p.active
      AND g.category_id=NEW.category_id AND (g.expires_at IS NULL OR g.expires_at>statement_timestamp()))) THEN
    RAISE EXCEPTION 'Inbox participants require current category access' USING ERRCODE='42501';
  END IF;
 ELSIF TG_TABLE_NAME='inbox_messages' THEN
  IF NEW.sender_id IS DISTINCT FROM scope_actor() THEN
   RAISE EXCEPTION 'Sender must be actual human' USING ERRCODE='42501';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('inbox-message:'||NEW.tenant_id::text||':'||NEW.conversation_id::text,0));
  SELECT coalesce(max(sequence),0) INTO latest FROM inbox_messages WHERE tenant_id=NEW.tenant_id AND conversation_id=NEW.conversation_id;
  IF NEW.sequence<>latest+1 THEN RAISE EXCEPTION 'Message sequence must append' USING ERRCODE='23514'; END IF;
 ELSE
  PERFORM pg_advisory_xact_lock(hashtextextended('inbox-state:'||NEW.tenant_id::text||':'||NEW.owner_id::text||':'||NEW.kind||':'||NEW.target_id::text,0));
  SELECT coalesce(max(revision),0) INTO latest FROM inbox_states WHERE tenant_id=NEW.tenant_id AND owner_id=NEW.owner_id AND kind=NEW.kind AND target_id=NEW.target_id;
  IF NEW.revision<>latest+1 THEN RAISE EXCEPTION 'Reading state must append' USING ERRCODE='23514'; END IF;
  IF NEW.read_through<>'' THEN
   IF NEW.kind='conversation' THEN
    SELECT max(sequence)::text INTO current_token FROM inbox_messages WHERE tenant_id=NEW.tenant_id AND conversation_id=NEW.target_id;
    IF NEW.read_through !~ '^[1-9][0-9]*$' OR NEW.read_through::bigint>coalesce(current_token::bigint,0) THEN
     RAISE EXCEPTION 'Cannot mark unseen future message read' USING ERRCODE='23514'; END IF;
   ELSE
    SELECT state||':'||cancel_epoch::text INTO current_token FROM agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.target_id AND requester_id=scope_requester();
    IF NEW.read_through IS DISTINCT FROM current_token THEN
     RAISE EXCEPTION 'Run reading state changed' USING ERRCODE='23514'; END IF;
   END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$
"""
IMMUTABLE = """CREATE FUNCTION public.reject_inbox_mutation() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 RAISE EXCEPTION 'Inbox history is append only' USING ERRCODE='23514'; END $$"""
SECURITY_SQL = [GUARD, IMMUTABLE]
for table, predicate, insert_predicate in (
    ('inbox_conversations',CONVERSATION,CONVERSATION+' AND owner_id=public.scope_actor()'),
    ('inbox_messages',MESSAGE,MESSAGE+' AND sender_id=public.scope_actor()'),
    ('inbox_states',STATE,STATE),
):
    SECURITY_SQL.extend((
      f'ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY',
      f'ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY',
      f'CREATE POLICY owner_internal ON public.{table} TO pdos_next_owner USING(true) WITH CHECK(true)',
      f'CREATE POLICY inbox_read ON public.{table} FOR SELECT TO pdos_next_app USING({predicate})',
      f'CREATE POLICY inbox_insert ON public.{table} FOR INSERT TO pdos_next_app WITH CHECK({insert_predicate})',
      f'REVOKE ALL ON public.{table} FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
      f'GRANT SELECT,INSERT ON public.{table} TO pdos_next_app',
      f'CREATE TRIGGER inbox_insert BEFORE INSERT ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.guard_inbox_insert()',
      f'CREATE TRIGGER inbox_immutable BEFORE UPDATE OR DELETE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.reject_inbox_mutation()',
    ))
SECURITY_SQL.extend((
 'REVOKE ALL ON FUNCTION public.guard_inbox_insert() FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'REVOKE ALL ON FUNCTION public.reject_inbox_mutation() FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
))
SCHEMA_SQL = (*TABLE_SQL,*SECURITY_SQL)
DOWNGRADE_SQL = ('DROP TABLE public.inbox_states','DROP TABLE public.inbox_messages','DROP TABLE public.inbox_conversations',
 'DROP FUNCTION public.guard_inbox_insert()','DROP FUNCTION public.reject_inbox_mutation()')
