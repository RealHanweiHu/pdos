"""Optional episode vectors for M2a (P85 第 3 项): "本人会话记录" category only.

Episode vectors are written by the episode owner's own background work (scope
actor = requester = owner); the AI writer identity cannot write them. Each
outbound embedding call leaves a receipt row with the server-decided provider,
data categories, P26 decision and cost, and no text. The dispatch role learns
only UUIDs of episodes still lacking a vector for the active profile version,
through a mirror of each saved profile version's switch kept by a trigger.

Kept its number at the 11-09 integration (chain s0_0864 -> s0_0865 -> s0_0866).
"""

# ruff: noqa: E501 -- Reviewed applied SQL literals remain byte-identical.

# Filled from the exact reviewed ORM tables (pdos_next.agent.memory.models).
TABLE_SQL = (
    "\nCREATE TABLE memory_embedding_calls (\n\towner_id UUID NOT NULL, \n\tprofile_version_id UUID NOT NULL, \n\tstate VARCHAR(24) NOT NULL, \n\trevision INTEGER NOT NULL, \n\tepisode_ids JSONB NOT NULL, \n\tcharacter_count INTEGER NOT NULL, \n\tinput_digest VARCHAR(64) NOT NULL, \n\tdata_categories JSONB NOT NULL, \n\tegress JSONB NOT NULL, \n\tpricing JSONB NOT NULL, \n\treserved_tokens BIGINT NOT NULL, \n\treserved_micro_usd BIGINT NOT NULL, \n\tcharged_micro_usd BIGINT NOT NULL, \n\tinput_tokens BIGINT, \n\tprovider_request_id VARCHAR(200), \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, profile_version_id) REFERENCES enterprise_embedding_profiles (tenant_id, id), \n\tCONSTRAINT memory_embedding_call_state CHECK (state IN ('started','completed','unknown','unknown_usage')), \n\tCONSTRAINT memory_embedding_call_counts CHECK (revision > 0 AND character_count >= 0 AND reserved_tokens >= 0 AND reserved_micro_usd >= 0 AND charged_micro_usd >= 0 AND (input_tokens IS NULL OR input_tokens >= 0)), \n\tCONSTRAINT memory_embedding_call_categories CHECK (jsonb_typeof(episode_ids)='array' AND jsonb_typeof(data_categories)='array' AND data_categories ? 'owner_session')\n)\n\n",
    'CREATE INDEX ix_memory_embedding_calls_owner ON memory_embedding_calls (tenant_id, owner_id, created_at)',
    'CREATE INDEX ix_memory_embedding_calls_tenant_id ON memory_embedding_calls (tenant_id)',
    "\nCREATE TABLE memory_episode_vectors (\n\towner_id UUID NOT NULL, \n\tsession_id UUID NOT NULL, \n\tepisode_id UUID NOT NULL, \n\tprofile_version_id UUID NOT NULL, \n\tcall_id UUID NOT NULL, \n\ttext_digest VARCHAR(64) NOT NULL, \n\tdimensions INTEGER NOT NULL, \n\tvector vector NOT NULL, \n\tnorm FLOAT NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, episode_id, profile_version_id), \n\tFOREIGN KEY(tenant_id, episode_id) REFERENCES memory_episodes (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, call_id) REFERENCES memory_embedding_calls (tenant_id, id), \n\tFOREIGN KEY(tenant_id, profile_version_id) REFERENCES enterprise_embedding_profiles (tenant_id, id), \n\tCONSTRAINT memory_episode_vector_shape CHECK (dimensions BETWEEN 1 AND 2000 AND vector_dims(vector)=dimensions AND norm=1), \n\tCONSTRAINT memory_episode_vector_digest CHECK (text_digest ~ '^[0-9a-f]{64}$')\n)\n\n",
    'CREATE INDEX ix_memory_episode_vectors_owner ON memory_episode_vectors (tenant_id, owner_id, profile_version_id)',
    'CREATE INDEX ix_memory_episode_vectors_tenant_id ON memory_episode_vectors (tenant_id)',

    "\nCREATE TABLE memory_vector_profiles (\n\tprofile_id UUID NOT NULL, \n\tprofile_version_id UUID NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tcategories JSONB NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, profile_version_id), \n\tFOREIGN KEY(tenant_id, profile_version_id) REFERENCES enterprise_embedding_profiles (tenant_id, id), \n\tCONSTRAINT memory_vector_profile_categories CHECK (jsonb_typeof(categories)='array')\n)\n\n",
    'CREATE INDEX ix_memory_vector_profiles_latest ON memory_vector_profiles (tenant_id, profile_id, created_at)',
    'CREATE INDEX ix_memory_vector_profiles_tenant_id ON memory_vector_profiles (tenant_id)',
)

TABLES = ("memory_embedding_calls", "memory_episode_vectors")

_TENANT = "tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid"
_HUMAN_SELF = " AND public.scope_actor()=public.scope_requester()"


def _owner(table):
    return f"""{_TENANT}
 AND owner_id=public.scope_requester()
 AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id={table}.tenant_id
   AND p.id=public.scope_actor() AND p.active)
 AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id={table}.tenant_id
   AND p.id=public.scope_requester() AND p.kind='human' AND p.active)"""


# A current human administrator reads receipts (provider, categories, cost) only.
_ADMIN_READ = f"""{_TENANT} AND public.scope_actor()=public.scope_requester()
 AND EXISTS(SELECT 1 FROM public.tenant_administrators a JOIN public.principals p
   ON p.tenant_id=a.tenant_id AND p.id=a.principal_id
   WHERE a.tenant_id=memory_embedding_calls.tenant_id AND a.principal_id=public.scope_actor()
    AND a.active AND p.active AND p.kind='human')"""

_EPISODE_PARENT = """ AND EXISTS(SELECT 1 FROM public.memory_episodes e
   WHERE e.tenant_id=memory_episode_vectors.tenant_id AND e.id=memory_episode_vectors.episode_id
    AND e.owner_id=memory_episode_vectors.owner_id AND e.session_id=memory_episode_vectors.session_id)
 AND EXISTS(SELECT 1 FROM public.memory_embedding_calls c
   WHERE c.tenant_id=memory_episode_vectors.tenant_id AND c.id=memory_episode_vectors.call_id
    AND c.owner_id=memory_episode_vectors.owner_id
    AND c.profile_version_id=memory_episode_vectors.profile_version_id
    AND c.state IN ('completed','unknown_usage'))"""

# Each saved profile version mirrors its “本人会话记录” switch (P85 第 3 项). The
# trigger runs in the administrator's own save transaction; nobody else writes it.
MIRROR_SQL = """
CREATE FUNCTION public.memory_mirror_vector_profile() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog, public, pg_temp AS $memory$
BEGIN
 INSERT INTO public.memory_vector_profiles(id,tenant_id,created_at,profile_id,profile_version_id,
   enabled,categories)
 VALUES (gen_random_uuid(),NEW.tenant_id,clock_timestamp(),NEW.profile_id,NEW.id,
   NEW.enabled AND coalesce(NEW.metadata_json->'data_categories','[]'::jsonb) ? 'owner_session',
   coalesce(NEW.metadata_json->'data_categories','[]'::jsonb))
 ON CONFLICT (tenant_id,profile_version_id) DO NOTHING;
 RETURN NULL;
END;
$memory$
"""

PENDING_SQL = """
CREATE FUNCTION public.memory_pending_vector_references(t uuid,page_limit integer)
RETURNS TABLE(tenant_id uuid,owner_id uuid,episode_id uuid,profile_version_id uuid)
LANGUAGE sql SECURITY DEFINER SET search_path TO pg_catalog, public, pg_temp AS $memory$
 WITH latest AS (
  SELECT DISTINCT ON (m.profile_id) m.profile_version_id, m.enabled, m.categories, m.created_at
  FROM public.memory_vector_profiles m WHERE m.tenant_id=t
  ORDER BY m.profile_id, m.created_at DESC, m.id DESC),
 profile AS (
  SELECT latest.profile_version_id AS id, latest.categories FROM latest WHERE latest.enabled
  ORDER BY latest.created_at DESC LIMIT 1)
 SELECT e.tenant_id,e.owner_id,e.id,profile.id FROM public.memory_episodes e
 CROSS JOIN profile
 JOIN public.agent_runs r ON r.tenant_id=e.tenant_id AND r.id=e.run_id
 WHERE e.tenant_id=t AND t=nullif(current_setting('pdos.tenant_id',true),'')::uuid
  AND NOT r.private_context
  AND (profile.categories ? 'customer' OR NOT (r.data_categories ? 'customer'
   OR jsonb_array_length(coalesce(r.customer_identities,'[]'::jsonb))>0))
  AND (profile.categories ? 'customer_original' OR NOT r.data_categories ? 'customer_original')
  AND NOT EXISTS(SELECT 1 FROM public.memory_episode_vectors v WHERE v.tenant_id=e.tenant_id
   AND v.episode_id=e.id AND v.profile_version_id=profile.id)
 ORDER BY e.created_at,e.id LIMIT LEAST(GREATEST(page_limit,1),200);
$memory$
"""

_REVOKED = "PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"

SECURITY_SQL = (
    *(statement for table in TABLES for statement in (
        f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY owner_internal ON public.{table} TO pdos_next_owner USING(true) WITH CHECK(true)",
        f"REVOKE ALL ON public.{table} FROM {_REVOKED}",
        f"CREATE POLICY {table}_read ON public.{table} FOR SELECT TO pdos_next_app USING({_owner(table)})",
    )),
    "CREATE TRIGGER memory_episode_vectors_append_only BEFORE UPDATE OR DELETE ON public.memory_episode_vectors "
    "FOR EACH ROW EXECUTE FUNCTION public.kernel_append_only()",
    "CREATE TRIGGER memory_embedding_calls_no_delete BEFORE DELETE ON public.memory_embedding_calls "
    "FOR EACH ROW EXECUTE FUNCTION public.kernel_append_only()",
    f"CREATE POLICY memory_embedding_calls_admin_read ON public.memory_embedding_calls FOR SELECT TO pdos_next_app USING({_ADMIN_READ})",
    f"CREATE POLICY memory_embedding_calls_start ON public.memory_embedding_calls FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_owner('memory_embedding_calls')}{_HUMAN_SELF} AND state='started')",
    # Settlement only: the owner's own started call moves to a terminal state once.
    f"CREATE POLICY memory_embedding_calls_settle ON public.memory_embedding_calls FOR UPDATE TO pdos_next_app "
    f"USING({_owner('memory_embedding_calls')}{_HUMAN_SELF} AND state='started') "
    f"WITH CHECK({_owner('memory_embedding_calls')}{_HUMAN_SELF} AND state<>'started')",
    "GRANT SELECT,INSERT,UPDATE ON public.memory_embedding_calls TO pdos_next_app",
    f"CREATE POLICY memory_episode_vectors_append ON public.memory_episode_vectors FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_owner('memory_episode_vectors')}{_HUMAN_SELF}{_EPISODE_PARENT})",
    "GRANT SELECT,INSERT ON public.memory_episode_vectors TO pdos_next_app",
    "ALTER TABLE public.memory_vector_profiles ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.memory_vector_profiles FORCE ROW LEVEL SECURITY",
    "CREATE POLICY owner_internal ON public.memory_vector_profiles TO pdos_next_owner USING(true) WITH CHECK(true)",
    f"REVOKE ALL ON public.memory_vector_profiles FROM {_REVOKED}",
    "CREATE TRIGGER memory_vector_profiles_append_only BEFORE UPDATE OR DELETE ON public.memory_vector_profiles "
    "FOR EACH ROW EXECUTE FUNCTION public.kernel_append_only()",
    MIRROR_SQL,
    f"REVOKE ALL ON FUNCTION public.memory_mirror_vector_profile() FROM {_REVOKED}",
    "CREATE TRIGGER memory_vector_profile_mirror AFTER INSERT ON public.enterprise_embedding_profiles "
    "FOR EACH ROW EXECUTE FUNCTION public.memory_mirror_vector_profile()",
    # No backfill: “本人会话记录” is new here, so no earlier profile version selects it.
    PENDING_SQL,
    f"REVOKE ALL ON FUNCTION public.memory_pending_vector_references(uuid,integer) FROM {_REVOKED}",
    "GRANT EXECUTE ON FUNCTION public.memory_pending_vector_references(uuid,integer) "
    "TO pdos_next_dispatch",
)

SCHEMA_SQL = (*TABLE_SQL, *SECURITY_SQL)

DOWNGRADE_SQL = (
    *(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY" for table in TABLES),
    """DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.memory_embedding_calls) THEN
     RAISE EXCEPTION 'Episode vector receipts require s0_0866'; END IF; END $$""",
    "DROP FUNCTION public.memory_pending_vector_references(uuid,integer)",
    "DROP TRIGGER memory_vector_profile_mirror ON public.enterprise_embedding_profiles",
    "DROP FUNCTION public.memory_mirror_vector_profile()",
    "ALTER TABLE public.memory_vector_profiles NO FORCE ROW LEVEL SECURITY",
    "DROP TABLE public.memory_vector_profiles",
    "DROP TABLE public.memory_episode_vectors",
    "DROP TABLE public.memory_embedding_calls",
)
