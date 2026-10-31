"""Versioned private work state. Only the host application may append."""

TABLE_SQL = """CREATE TABLE public.agent_work_states (
 session_id UUID NOT NULL, owner_id UUID NOT NULL, run_id UUID,
 revision INTEGER NOT NULL, origin VARCHAR(16) NOT NULL, request_key UUID NOT NULL,
 request_sha256 VARCHAR(64) NOT NULL, body JSONB NOT NULL,
 id UUID NOT NULL, tenant_id UUID NOT NULL, created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 PRIMARY KEY (id), UNIQUE (tenant_id,id), UNIQUE (tenant_id,session_id,revision),
 UNIQUE (tenant_id,session_id,request_key), UNIQUE (tenant_id,run_id),
 FOREIGN KEY (tenant_id,session_id) REFERENCES public.agent_sessions (tenant_id,id),
 FOREIGN KEY (tenant_id,owner_id) REFERENCES public.principals (tenant_id,id),
 FOREIGN KEY (tenant_id,run_id) REFERENCES public.agent_runs (tenant_id,id),
 CONSTRAINT work_state_revision CHECK (revision > 0),
 CONSTRAINT work_state_origin CHECK (origin IN ('run','human')),
 CONSTRAINT work_state_run_origin CHECK ((origin='run') = (run_id IS NOT NULL)),
 CONSTRAINT work_state_body CHECK (jsonb_typeof(body)='object'),
 CONSTRAINT work_state_request_sha256 CHECK (request_sha256 ~ '^[0-9a-f]{64}$')
)"""

SCOPE_SQL = """tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
 AND owner_id=scope_requester()
 AND EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=agent_work_states.tenant_id
   AND p.id=scope_actor() AND p.active)
 AND EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=agent_work_states.tenant_id
   AND p.id=scope_requester() AND p.kind='human' AND p.active)
 AND EXISTS(SELECT 1 FROM agent_sessions s WHERE s.tenant_id=agent_work_states.tenant_id
   AND s.id=agent_work_states.session_id AND s.owner_id=agent_work_states.owner_id
   AND (s.category_id IS NULL OR category_access(s.tenant_id,s.category_id)))"""

SCHEMA_SQL = [
    TABLE_SQL,
    "CREATE INDEX ix_agent_work_states_tenant_id ON public.agent_work_states (tenant_id)",
    "ALTER TABLE public.agent_work_states ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.agent_work_states FORCE ROW LEVEL SECURITY",
    f"CREATE POLICY work_state_read ON public.agent_work_states FOR SELECT USING ({SCOPE_SQL})",
    f"""CREATE POLICY work_state_append ON public.agent_work_states FOR INSERT
     WITH CHECK ({SCOPE_SQL} AND (
      (origin='human' AND scope_actor()=scope_requester()) OR
      (origin='run' AND EXISTS(SELECT 1 FROM agent_runs r
       WHERE r.tenant_id=agent_work_states.tenant_id AND r.id=agent_work_states.run_id
       AND r.session_id=agent_work_states.session_id AND r.requester_id=scope_requester()
       AND (r.writer_id=scope_actor() OR scope_actor()=scope_requester())))))""",
    "REVOKE ALL ON public.agent_work_states "
    "FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch",
    "GRANT SELECT,INSERT ON public.agent_work_states TO pdos_next_app",
    """CREATE TRIGGER work_state_append_only BEFORE UPDATE OR DELETE ON public.agent_work_states
     FOR EACH ROW EXECUTE FUNCTION kernel_append_only()""",
]
DOWNGRADE_SQL = [
    "ALTER TABLE public.agent_work_states NO FORCE ROW LEVEL SECURITY",
    """DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.agent_work_states) THEN
     RAISE EXCEPTION 'Work state history requires s0_0825'; END IF; END $$""",
    "DROP TABLE public.agent_work_states",
]
