"""Personal episodic memory (M1, P84/P85): episodes, marks, keyword index, mode, policy.

Episodes are inserted only by a deferred SECURITY DEFINER projection of the
committed run work-state version, so the Run's terminal state and result are
final when the row is built. No runtime role has INSERT on memory_episodes: an
application or AI identity cannot write, change or delete an episode. Marks,
index rows and the session switch accept only the actual human owner acting for
themself (scope_actor = scope_requester); the AI writer identity is refused.
"""

# ruff: noqa: E501 -- Reviewed applied SQL literals remain byte-identical.

# Filled from the exact reviewed ORM tables (pdos_next.agent.memory.models).
TABLE_SQL = (
    "\nCREATE TABLE memory_episodes (\n\towner_id UUID NOT NULL, \n\tsession_id UUID NOT NULL, \n\trun_id UUID NOT NULL, \n\twork_state_id UUID NOT NULL, \n\twork_state_revision INTEGER NOT NULL, \n\tcategory_id UUID, \n\tproduct_id UUID, \n\tproposal_id UUID, \n\tproject_id UUID, \n\tentry VARCHAR(16) NOT NULL, \n\tstatus VARCHAR(32) NOT NULL, \n\tgoal TEXT NOT NULL, \n\tbody JSONB NOT NULL, \n\tprojection_version VARCHAR(40) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, run_id), \n\tFOREIGN KEY(tenant_id, session_id) REFERENCES agent_sessions (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, run_id) REFERENCES agent_runs (tenant_id, id), \n\tFOREIGN KEY(tenant_id, work_state_id) REFERENCES agent_work_states (tenant_id, id), \n\tCONSTRAINT memory_episode_revision CHECK (work_state_revision > 0), \n\tCONSTRAINT memory_episode_entry CHECK (entry IN ('web','dingtalk')), \n\tCONSTRAINT memory_episode_body CHECK (jsonb_typeof(body)='object')\n)\n\n",
    "CREATE INDEX ix_memory_episodes_owner_recent ON memory_episodes (tenant_id, owner_id, created_at)",
    "CREATE INDEX ix_memory_episodes_tenant_id ON memory_episodes (tenant_id)",
    "\nCREATE TABLE memory_episode_marks (\n\towner_id UUID NOT NULL, \n\tsession_id UUID NOT NULL, \n\tepisode_id UUID NOT NULL, \n\tkind VARCHAR(16) NOT NULL, \n\tbody JSONB NOT NULL, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, owner_id, request_key), \n\tFOREIGN KEY(tenant_id, episode_id) REFERENCES memory_episodes (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT memory_mark_kind CHECK (kind IN ('pin','unpin','hide','unhide','correction')), \n\tCONSTRAINT memory_mark_body CHECK (jsonb_typeof(body)='object'), \n\tCONSTRAINT memory_mark_request_sha256 CHECK (request_sha256 ~ '^[0-9a-f]{64}$')\n)\n\n",
    "CREATE INDEX ix_memory_episode_marks_episode ON memory_episode_marks (tenant_id, episode_id)",
    "CREATE INDEX ix_memory_episode_marks_tenant_id ON memory_episode_marks (tenant_id)",
    "\nCREATE TABLE memory_index (\n\towner_id UUID NOT NULL, \n\tsession_id UUID NOT NULL, \n\tepisode_id UUID NOT NULL, \n\tsource_kind VARCHAR(16) NOT NULL, \n\tsource_version INTEGER NOT NULL, \n\tprofile_version VARCHAR(80) NOT NULL, \n\tidempotency_key VARCHAR(64) NOT NULL, \n\tterms TSVECTOR NOT NULL, \n\tterm_counts JSONB NOT NULL, \n\tcodes TEXT[] NOT NULL, \n\ttoken_count INTEGER NOT NULL, \n\ttokenizer_version VARCHAR(160) NOT NULL, \n\tcode_rule_version VARCHAR(160) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, idempotency_key), \n\tFOREIGN KEY(tenant_id, episode_id) REFERENCES memory_episodes (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT memory_index_source_kind CHECK (source_kind IN ('episode')), \n\tCONSTRAINT memory_index_counts CHECK (source_version > 0 AND token_count >= 0), \n\tCONSTRAINT memory_index_key CHECK (idempotency_key ~ '^[0-9a-f]{64}$')\n)\n\n",
    "CREATE INDEX ix_memory_index_codes ON memory_index USING gin (codes)",
    "CREATE INDEX ix_memory_index_owner ON memory_index (tenant_id, owner_id, tokenizer_version)",
    "CREATE INDEX ix_memory_index_tenant_id ON memory_index (tenant_id)",
    "CREATE INDEX ix_memory_index_terms ON memory_index USING gin (terms)",
    "\nCREATE TABLE memory_session_settings (\n\towner_id UUID NOT NULL, \n\tsession_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tmemory_off BOOLEAN NOT NULL, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, session_id, revision), \n\tUNIQUE (tenant_id, owner_id, request_key), \n\tFOREIGN KEY(tenant_id, session_id) REFERENCES agent_sessions (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT memory_setting_revision CHECK (revision > 0), \n\tCONSTRAINT memory_setting_request_sha256 CHECK (request_sha256 ~ '^[0-9a-f]{64}$')\n)\n\n",
    "CREATE INDEX ix_memory_session_settings_tenant_id ON memory_session_settings (tenant_id)",
    "\nCREATE TABLE memory_tenant_policies (\n\trevision INTEGER NOT NULL, \n\twork_state_idle_days INTEGER NOT NULL, \n\tset_by UUID NOT NULL, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, revision), \n\tUNIQUE (tenant_id, request_key), \n\tFOREIGN KEY(tenant_id, set_by) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT memory_policy_revision CHECK (revision > 0), \n\tCONSTRAINT memory_policy_idle_days CHECK (work_state_idle_days BETWEEN 1 AND 365), \n\tCONSTRAINT memory_policy_request_sha256 CHECK (request_sha256 ~ '^[0-9a-f]{64}$')\n)\n\n",
    "CREATE INDEX ix_memory_tenant_policies_tenant_id ON memory_tenant_policies (tenant_id)",
)

OWNER_TABLES = ("memory_episodes", "memory_episode_marks", "memory_index", "memory_session_settings")
TABLES = (*OWNER_TABLES, "memory_tenant_policies")


def _owner_scope(table):
    """Same condition as agent_work_states: the human owner's own rows in a readable Session."""
    return f"""tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid
 AND owner_id=public.scope_requester()
 AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id={table}.tenant_id
   AND p.id=public.scope_actor() AND p.active)
 AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id={table}.tenant_id
   AND p.id=public.scope_requester() AND p.kind='human' AND p.active)
 AND EXISTS(SELECT 1 FROM public.agent_sessions s WHERE s.tenant_id={table}.tenant_id
   AND s.id={table}.session_id AND s.owner_id={table}.owner_id
   AND (s.category_id IS NULL OR public.category_access(s.tenant_id,s.category_id)))"""


# The owner acts for themself. The AI writer identity never satisfies this.
_HUMAN_SELF = " AND public.scope_actor()=public.scope_requester()"


def _episode_parent(table):
    return f""" AND EXISTS(SELECT 1 FROM public.memory_episodes e WHERE e.tenant_id={table}.tenant_id
   AND e.id={table}.episode_id AND e.owner_id={table}.owner_id AND e.session_id={table}.session_id)"""


_POLICY_READ = """tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid
 AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=memory_tenant_policies.tenant_id
   AND p.id=public.scope_actor() AND p.active)"""
_POLICY_WRITE = _POLICY_READ + """ AND public.scope_actor()=public.scope_requester()
 AND set_by=public.scope_actor()
 AND EXISTS(SELECT 1 FROM public.tenant_administrators a JOIN public.principals p
   ON p.tenant_id=a.tenant_id AND p.id=a.principal_id
   WHERE a.tenant_id=memory_tenant_policies.tenant_id AND a.principal_id=public.scope_actor()
    AND a.active AND p.active AND p.kind='human')"""

PROJECTION_SQL = """
CREATE FUNCTION public.memory_project_episode() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog, public, pg_temp AS $memory$
DECLARE
 r public.agent_runs%ROWTYPE;
 rid text;
 memory_off boolean;
 retrieval text;
 projected jsonb;
BEGIN
 IF NEW.origin<>'run' OR NEW.run_id IS NULL THEN RETURN NULL; END IF;
 SELECT * INTO r FROM public.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;
 IF r.id IS NULL OR r.trigger<>'conversation' OR r.session_id<>NEW.session_id
  OR r.requester_id<>NEW.owner_id THEN RETURN NULL; END IF;
 rid := r.id::text;
 IF NEW.body#>>'{current_goal,run_id}' IS DISTINCT FROM rid THEN RETURN NULL; END IF;
 -- The Run freezes its mode at start; a Run that never started reads the switch.
 memory_off := coalesce((r.versions#>>'{memory_mode,off}')::boolean,
  (SELECT m.memory_off FROM public.memory_session_settings m
    WHERE m.tenant_id=NEW.tenant_id AND m.session_id=NEW.session_id
    ORDER BY m.revision DESC LIMIT 1), false);
 IF memory_off THEN RETURN NULL; END IF;
 SELECT CASE
   WHEN bool_or(c.result#>>'{semantic,status}'='unavailable') THEN 'keyword_only'
   WHEN bool_or(c.result#>>'{semantic,status}'='queried') THEN 'hybrid'
   WHEN count(*)>0 THEN 'keyword'
   ELSE 'none' END INTO retrieval
  FROM public.agent_tool_calls c
  WHERE c.tenant_id=NEW.tenant_id AND c.run_id=r.id AND c.tool='assistant.search'
   AND c.state='completed';
 projected := jsonb_build_object(
  'focus_objects', coalesce((SELECT jsonb_agg(jsonb_build_object(
     'kind',f->>'kind','id',f->>'id','version',f->'version') ORDER BY n)
    FROM jsonb_array_elements(coalesce(NEW.body->'focus_objects','[]'::jsonb))
     WITH ORDINALITY AS x(f,n) WHERE f->>'run_id'=rid),'[]'::jsonb),
  'receipts', coalesce((SELECT jsonb_agg(jsonb_build_object(
     'receipt_id',f->>'receipt_id','operation',f->>'operation') ORDER BY n)
    FROM jsonb_array_elements(coalesce(NEW.body->'completed','[]'::jsonb))
     WITH ORDINALITY AS x(f,n) WHERE f->>'run_id'=rid),'[]'::jsonb),
  'candidates', coalesce((SELECT jsonb_agg(jsonb_build_object('event_id',f->>'event_id') ORDER BY n)
    FROM jsonb_array_elements(coalesce(NEW.body->'candidates','[]'::jsonb))
     WITH ORDINALITY AS x(f,n) WHERE f->>'run_id'=rid),'[]'::jsonb),
  'skills', coalesce((SELECT jsonb_agg(jsonb_build_object(
     'key',f->>'key','version',f->>'version') ORDER BY n)
    FROM jsonb_array_elements(coalesce(NEW.body->'skills','[]'::jsonb))
     WITH ORDINALITY AS x(f,n) WHERE f->>'run_id'=rid),'[]'::jsonb),
  'citations', coalesce((SELECT jsonb_agg(jsonb_build_object('citation_id',f->>'citation_id') ORDER BY n)
    FROM jsonb_array_elements(coalesce(NEW.body->'citations','[]'::jsonb))
     WITH ORDINALITY AS x(f,n) WHERE f->>'run_id'=rid),'[]'::jsonb),
  'model_notes', jsonb_build_object(
   'unfinished', CASE WHEN jsonb_typeof(r.result->'unfinished')='array'
     THEN r.result->'unfinished' ELSE '[]'::jsonb END,
   'questions', CASE WHEN jsonb_typeof(r.result->'questions')='array'
     THEN r.result->'questions' ELSE '[]'::jsonb END),
  'usage', jsonb_build_object(
   'episodes', CASE WHEN jsonb_typeof(r.versions#>'{memory_usage,episodes}')='array'
     THEN r.versions#>'{memory_usage,episodes}' ELSE '[]'::jsonb END,
   'sessions', CASE WHEN jsonb_typeof(r.versions#>'{memory_usage,sessions}')='array'
     THEN r.versions#>'{memory_usage,sessions}' ELSE '[]'::jsonb END),
  'retrieval', jsonb_build_object(
   'enterprise', retrieval,
   'memory', coalesce(r.versions#>'{memory_usage,retrieval}','null'::jsonb)));
 INSERT INTO public.memory_episodes(id,tenant_id,created_at,owner_id,session_id,run_id,
   work_state_id,work_state_revision,category_id,product_id,proposal_id,project_id,
   entry,status,goal,body,projection_version)
 VALUES (gen_random_uuid(),NEW.tenant_id,NEW.created_at,NEW.owner_id,NEW.session_id,r.id,
   NEW.id,NEW.revision,r.category_id,r.product_id,r.proposal_id,r.project_id,
   CASE WHEN coalesce(r.versions->'dingtalk','null'::jsonb) IN
     ('null'::jsonb,'false'::jsonb,'{}'::jsonb,'[]'::jsonb,'""'::jsonb) THEN 'web' ELSE 'dingtalk' END,
   r.state,coalesce(NEW.body#>>'{current_goal,text}',''),projected,'memory-episode/v1')
 ON CONFLICT (tenant_id,run_id) DO NOTHING;
 RETURN NULL;
END;
$memory$
"""

PENDING_SQL = """
CREATE FUNCTION public.memory_pending_index_references(t uuid,tokenizer text,page_limit integer)
RETURNS TABLE(tenant_id uuid,owner_id uuid,episode_id uuid)
LANGUAGE sql SECURITY DEFINER SET search_path TO pg_catalog, public, pg_temp AS $memory$
 SELECT e.tenant_id,e.owner_id,e.id FROM public.memory_episodes e
 WHERE e.tenant_id=t AND t=nullif(current_setting('pdos.tenant_id',true),'')::uuid
  AND NOT EXISTS(SELECT 1 FROM public.memory_index i WHERE i.tenant_id=e.tenant_id
   AND i.episode_id=e.id AND i.tokenizer_version=tokenizer)
 ORDER BY e.created_at,e.id LIMIT LEAST(GREATEST(page_limit,1),200);
$memory$
"""

# Session presentation rows are readable only by the human owner acting for
# themself. A Run reading for that owner may learn one boolean per own Session:
# whether its latest presentation is archived (P85 第 4 项: archived Sessions
# leave recall). Nothing else about the presentation is disclosed.
ARCHIVED_SQL = """
CREATE FUNCTION public.memory_session_archived(t uuid,sid uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO pg_catalog, public, pg_temp AS $memory$
 SELECT coalesce((SELECT p.archived FROM public.agent_session_presentations p
   WHERE p.tenant_id=t AND t=nullif(current_setting('pdos.tenant_id',true),'')::uuid
    AND p.session_id=sid AND p.owner_id=public.scope_requester()
   ORDER BY p.revision DESC LIMIT 1),false);
$memory$
"""

_REVOKED = "PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"

SECURITY_SQL = (
    PROJECTION_SQL,
    PENDING_SQL,
    ARCHIVED_SQL,
    "CREATE CONSTRAINT TRIGGER memory_episode_projection AFTER INSERT ON public.agent_work_states "
    "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.origin='run') "
    "EXECUTE FUNCTION public.memory_project_episode()",
    *(statement for table in TABLES for statement in (
        f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY owner_internal ON public.{table} TO pdos_next_owner USING(true) WITH CHECK(true)",
        f"REVOKE ALL ON public.{table} FROM {_REVOKED}",
        f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON public.{table} "
        "FOR EACH ROW EXECUTE FUNCTION public.kernel_append_only()",
    )),
    f"CREATE POLICY memory_episode_read ON public.memory_episodes FOR SELECT TO pdos_next_app "
    f"USING({_owner_scope('memory_episodes')})",
    "GRANT SELECT ON public.memory_episodes TO pdos_next_app",
    f"CREATE POLICY memory_mark_read ON public.memory_episode_marks FOR SELECT TO pdos_next_app "
    f"USING({_owner_scope('memory_episode_marks')})",
    f"CREATE POLICY memory_mark_append ON public.memory_episode_marks FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_owner_scope('memory_episode_marks')}{_HUMAN_SELF}"
    f"{_episode_parent('memory_episode_marks')})",
    "GRANT SELECT,INSERT ON public.memory_episode_marks TO pdos_next_app",
    f"CREATE POLICY memory_index_read ON public.memory_index FOR SELECT TO pdos_next_app "
    f"USING({_owner_scope('memory_index')})",
    f"CREATE POLICY memory_index_append ON public.memory_index FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_owner_scope('memory_index')}{_HUMAN_SELF}{_episode_parent('memory_index')})",
    "GRANT SELECT,INSERT ON public.memory_index TO pdos_next_app",
    f"CREATE POLICY memory_setting_read ON public.memory_session_settings FOR SELECT TO pdos_next_app "
    f"USING({_owner_scope('memory_session_settings')})",
    f"CREATE POLICY memory_setting_append ON public.memory_session_settings FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_owner_scope('memory_session_settings')}{_HUMAN_SELF})",
    "GRANT SELECT,INSERT ON public.memory_session_settings TO pdos_next_app",
    f"CREATE POLICY memory_policy_read ON public.memory_tenant_policies FOR SELECT TO pdos_next_app "
    f"USING({_POLICY_READ})",
    f"CREATE POLICY memory_policy_append ON public.memory_tenant_policies FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_POLICY_WRITE})",
    "GRANT SELECT,INSERT ON public.memory_tenant_policies TO pdos_next_app",
    f"REVOKE ALL ON FUNCTION public.memory_project_episode() FROM {_REVOKED}",
    f"REVOKE ALL ON FUNCTION public.memory_pending_index_references(uuid,text,integer) FROM {_REVOKED}",
    "GRANT EXECUTE ON FUNCTION public.memory_pending_index_references(uuid,text,integer) "
    "TO pdos_next_dispatch",
    f"REVOKE ALL ON FUNCTION public.memory_session_archived(uuid,uuid) FROM {_REVOKED}",
    "GRANT EXECUTE ON FUNCTION public.memory_session_archived(uuid,uuid) TO pdos_next_app",
)

SCHEMA_SQL = (*TABLE_SQL, *SECURITY_SQL)

DOWNGRADE_SQL = (
    *(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY" for table in TABLES),
    """DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.memory_episodes)
     OR EXISTS(SELECT 1 FROM public.memory_episode_marks)
     OR EXISTS(SELECT 1 FROM public.memory_session_settings)
     OR EXISTS(SELECT 1 FROM public.memory_tenant_policies) THEN
     RAISE EXCEPTION 'Personal memory history requires s0_0855'; END IF; END $$""",
    "DROP TRIGGER memory_episode_projection ON public.agent_work_states",
    "DROP FUNCTION public.memory_session_archived(uuid,uuid)",
    "DROP FUNCTION public.memory_pending_index_references(uuid,text,integer)",
    "DROP FUNCTION public.memory_project_episode()",
    "DROP TABLE public.memory_index",
    "DROP TABLE public.memory_episode_marks",
    "DROP TABLE public.memory_episodes",
    "DROP TABLE public.memory_session_settings",
    "DROP TABLE public.memory_tenant_policies",
)
