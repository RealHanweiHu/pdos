"""Personal memory notes for M2a (P86): notes, versions, purge tombstones, candidates.

Only the human owner acting for themself (scope_actor = scope_requester) can
write a note, a version, a purge tombstone, a candidate decision or the owner's
proactive switch; the AI writer identity is refused by the database. A note's
content lives only in its versions: the owner's purge deletes every version and
the candidate it came from, and leaves a tombstone with no content (design §5
第 5 条). Versions are never updated.

Candidates are not memory: the server stores them after a Run's deterministic
admission, only for that Run's own human requester, while the conversation Run
is still active. The administrator can close notes and proposals tenant-wide
and can read only counts (P86 第 9 项), through memory_note_statistics.

Kept its number at the 11-09 integration (chain s0_0864 -> s0_0865 -> s0_0866).
"""

# ruff: noqa: E501 -- Reviewed applied SQL literals remain byte-identical.

# Filled from the exact reviewed ORM tables (pdos_next.agent.memory.models).
TABLE_SQL = (
    '\nCREATE TABLE memory_notes (\n\towner_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id)\n)\n\n',
    'CREATE INDEX ix_memory_notes_owner ON memory_notes (tenant_id, owner_id)',
    'CREATE INDEX ix_memory_notes_tenant_id ON memory_notes (tenant_id)',
    "\nCREATE TABLE memory_note_versions (\n\towner_id UUID NOT NULL, \n\tnote_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tkind VARCHAR(16) NOT NULL, \n\ttext TEXT NOT NULL, \n\tscope_kind VARCHAR(16) NOT NULL, \n\tscope_id UUID, \n\tcategory_id UUID, \n\talias_term VARCHAR(40), \n\talias_canonical VARCHAR(80), \n\ttarget_kind VARCHAR(16), \n\ttarget_id UUID, \n\ttarget_version INTEGER, \n\tstatus VARCHAR(16) NOT NULL, \n\tvalid_until TIMESTAMP WITH TIME ZONE, \n\treplaced_by UUID, \n\torigin VARCHAR(16) NOT NULL, \n\tcandidate_id UUID, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, note_id, revision), \n\tUNIQUE (tenant_id, note_id, request_key), \n\tFOREIGN KEY(tenant_id, note_id) REFERENCES memory_notes (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT memory_note_revision CHECK (revision > 0), \n\tCONSTRAINT memory_note_kind CHECK (kind IN ('convention','background','alias')), \n\tCONSTRAINT memory_note_text CHECK (char_length(text) BETWEEN 1 AND 200), \n\tCONSTRAINT memory_note_scope CHECK (scope_kind IN ('global','category','product','proposal','project') AND ((scope_kind='global') = (scope_id IS NULL)) AND ((scope_kind='global') = (category_id IS NULL))), \n\tCONSTRAINT memory_note_alias CHECK (((kind='alias') = (alias_term IS NOT NULL)) AND (kind<>'alias' OR ((alias_canonical IS NOT NULL) <> (target_id IS NOT NULL)))), \n\tCONSTRAINT memory_note_target CHECK ((target_id IS NULL) = (target_kind IS NULL) AND (target_id IS NULL) = (target_version IS NULL) AND (target_kind IS NULL OR target_kind IN ('category','product','proposal','project'))), \n\tCONSTRAINT memory_note_status CHECK (status IN ('active','replaced')), \n\tCONSTRAINT memory_note_origin CHECK (origin IN ('manual','candidate','merge')), \n\tCONSTRAINT memory_note_request_sha256 CHECK (request_sha256 ~ '^[0-9a-f]{64}$')\n)\n\n",
    'CREATE INDEX ix_memory_note_versions_owner ON memory_note_versions (tenant_id, owner_id, note_id, revision)',
    'CREATE INDEX ix_memory_note_versions_tenant_id ON memory_note_versions (tenant_id)',
    "\nCREATE TABLE memory_note_deletions (\n\towner_id UUID NOT NULL, \n\tnote_id UUID NOT NULL, \n\tpurged_versions INTEGER NOT NULL, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, note_id), \n\tUNIQUE (tenant_id, owner_id, request_key), \n\tFOREIGN KEY(tenant_id, note_id) REFERENCES memory_notes (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT memory_note_deletion_count CHECK (purged_versions >= 0), \n\tCONSTRAINT memory_note_deletion_request_sha256 CHECK (request_sha256 ~ '^[0-9a-f]{64}$')\n)\n\n",
    'CREATE INDEX ix_memory_note_deletions_tenant_id ON memory_note_deletions (tenant_id)',
    "\nCREATE TABLE memory_candidates (\n\towner_id UUID NOT NULL, \n\tsession_id UUID NOT NULL, \n\trun_id UUID NOT NULL, \n\tcandidate_key VARCHAR(64) NOT NULL, \n\torigin VARCHAR(16) NOT NULL, \n\tkind VARCHAR(16) NOT NULL, \n\ttext TEXT NOT NULL, \n\tscope_kind VARCHAR(16) NOT NULL, \n\tscope_id UUID, \n\tcategory_id UUID, \n\talias_term VARCHAR(40), \n\talias_canonical VARCHAR(80), \n\tconflicts JSONB NOT NULL, \n\ttrigger JSONB NOT NULL, \n\tprompt_version VARCHAR(40) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, candidate_key), \n\tFOREIGN KEY(tenant_id, run_id) REFERENCES agent_runs (tenant_id, id), \n\tFOREIGN KEY(tenant_id, session_id) REFERENCES agent_sessions (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT memory_candidate_origin CHECK (origin IN ('explicit','proactive')), \n\tCONSTRAINT memory_candidate_kind CHECK (kind IN ('convention','background','alias')), \n\tCONSTRAINT memory_candidate_text CHECK (char_length(text) BETWEEN 1 AND 200), \n\tCONSTRAINT memory_candidate_scope CHECK (scope_kind IN ('global','category','product','proposal','project') AND ((scope_kind='global') = (scope_id IS NULL)) AND ((scope_kind='global') = (category_id IS NULL))), \n\tCONSTRAINT memory_candidate_alias CHECK (((kind='alias') = (alias_term IS NOT NULL)) AND ((kind='alias') = (alias_canonical IS NOT NULL))), \n\tCONSTRAINT memory_candidate_json CHECK (jsonb_typeof(conflicts)='array' AND jsonb_typeof(trigger)='array'), \n\tCONSTRAINT memory_candidate_key CHECK (candidate_key ~ '^[0-9a-f]{64}$')\n)\n\n",
    'CREATE INDEX ix_memory_candidates_owner ON memory_candidates (tenant_id, owner_id, created_at)',
    'CREATE INDEX ix_memory_candidates_session ON memory_candidates (tenant_id, session_id, origin)',
    'CREATE INDEX ix_memory_candidates_tenant_id ON memory_candidates (tenant_id)',
    "\nCREATE TABLE memory_candidate_decisions (\n\towner_id UUID NOT NULL, \n\tcandidate_id UUID NOT NULL, \n\tdecision VARCHAR(16) NOT NULL, \n\tnote_id UUID, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, candidate_id), \n\tUNIQUE (tenant_id, owner_id, request_key), \n\tFOREIGN KEY(tenant_id, candidate_id) REFERENCES memory_candidates (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT memory_candidate_decision CHECK (decision IN ('adopted','ignored') AND ((decision='adopted') = (note_id IS NOT NULL))), \n\tCONSTRAINT memory_candidate_decision_sha256 CHECK (request_sha256 ~ '^[0-9a-f]{64}$')\n)\n\n",
    'CREATE INDEX ix_memory_candidate_decisions_tenant_id ON memory_candidate_decisions (tenant_id)',
    "\nCREATE TABLE memory_owner_settings (\n\towner_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tproactive_off BOOLEAN NOT NULL, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, owner_id, revision), \n\tUNIQUE (tenant_id, owner_id, request_key), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT memory_owner_setting_revision CHECK (revision > 0), \n\tCONSTRAINT memory_owner_setting_sha256 CHECK (request_sha256 ~ '^[0-9a-f]{64}$')\n)\n\n",
    'CREATE INDEX ix_memory_owner_settings_tenant_id ON memory_owner_settings (tenant_id)',

)

TABLES = (
    "memory_notes", "memory_note_versions", "memory_note_deletions", "memory_candidates",
    "memory_candidate_decisions", "memory_owner_settings",
)
# Content tables the owner may purge; never updated.
PURGEABLE = ("memory_note_versions", "memory_candidates", "memory_candidate_decisions")

_TENANT = "tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid"


def _owner(table):
    """The requester's own rows, for an active actor and an active human requester."""
    return f"""{_TENANT}
 AND owner_id=public.scope_requester()
 AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id={table}.tenant_id
   AND p.id=public.scope_actor() AND p.active)
 AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id={table}.tenant_id
   AND p.id=public.scope_requester() AND p.kind='human' AND p.active)"""


# The owner acts for themself. The AI writer identity never satisfies this.
_HUMAN_SELF = " AND public.scope_actor()=public.scope_requester()"


def _note_parent(table):
    return f""" AND EXISTS(SELECT 1 FROM public.memory_notes n WHERE n.tenant_id={table}.tenant_id
   AND n.id={table}.note_id AND n.owner_id={table}.owner_id)"""


def _not_purged(table):
    return f""" AND NOT EXISTS(SELECT 1 FROM public.memory_note_deletions d
   WHERE d.tenant_id={table}.tenant_id AND d.note_id={table}.note_id)"""


def _scope_readable(table):
    return f" AND ({table}.category_id IS NULL OR public.category_access({table}.tenant_id,{table}.category_id))"


# A candidate is stored only while its own conversation Run is still active and
# only for that Run's human requester (P86 第 10 项: server admission in finalize).
_CANDIDATE_RUN = """ AND EXISTS(SELECT 1 FROM public.agent_runs r WHERE r.tenant_id=memory_candidates.tenant_id
   AND r.id=memory_candidates.run_id AND r.requester_id=memory_candidates.owner_id
   AND r.session_id=memory_candidates.session_id AND r.trigger='conversation'
   AND r.state IN ('queued','running','waiting_input'))
 AND EXISTS(SELECT 1 FROM public.agent_sessions s WHERE s.tenant_id=memory_candidates.tenant_id
   AND s.id=memory_candidates.session_id AND s.owner_id=memory_candidates.owner_id)"""

_CANDIDATE_PARENT = """ AND EXISTS(SELECT 1 FROM public.memory_candidates c
   WHERE c.tenant_id=memory_candidate_decisions.tenant_id
   AND c.id=memory_candidate_decisions.candidate_id AND c.owner_id=memory_candidate_decisions.owner_id)"""

STATISTICS_SQL = """
CREATE FUNCTION public.memory_note_statistics(t uuid)
RETURNS TABLE(active_notes bigint, owners bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path TO pg_catalog, public, pg_temp AS $memory$
BEGIN
 IF t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
  OR public.scope_actor() IS DISTINCT FROM public.scope_requester()
  OR NOT EXISTS(SELECT 1 FROM public.tenant_administrators a JOIN public.principals p
   ON p.tenant_id=a.tenant_id AND p.id=a.principal_id
   WHERE a.tenant_id=t AND a.principal_id=public.scope_actor() AND a.active AND p.active
    AND p.kind='human') THEN
  RAISE EXCEPTION 'Current human tenant administrator required' USING ERRCODE='42501';
 END IF;
 -- Counts only: an administrator never reads a note's text, kind or scope.
 RETURN QUERY SELECT count(*)::bigint, count(DISTINCT latest.owner_id)::bigint FROM (
   SELECT DISTINCT ON (v.note_id) v.note_id, v.owner_id, v.status, v.valid_until
   FROM public.memory_note_versions v WHERE v.tenant_id=t
   ORDER BY v.note_id, v.revision DESC) latest
  WHERE latest.status='active' AND (latest.valid_until IS NULL OR latest.valid_until>now());
END;
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
        f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON public.{table} "
        "FOR EACH ROW EXECUTE FUNCTION public.kernel_append_only()",
    )),
    *(f"CREATE TRIGGER {table}_append_only BEFORE DELETE ON public.{table} "
      "FOR EACH ROW EXECUTE FUNCTION public.kernel_append_only()"
      for table in TABLES if table not in PURGEABLE),
    f"CREATE POLICY memory_notes_append ON public.memory_notes FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_owner('memory_notes')}{_HUMAN_SELF})",
    "GRANT SELECT,INSERT ON public.memory_notes TO pdos_next_app",
    f"CREATE POLICY memory_note_versions_append ON public.memory_note_versions FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_owner('memory_note_versions')}{_HUMAN_SELF}{_note_parent('memory_note_versions')}"
    f"{_not_purged('memory_note_versions')}{_scope_readable('memory_note_versions')})",
    f"CREATE POLICY memory_note_versions_purge ON public.memory_note_versions FOR DELETE TO pdos_next_app "
    f"USING({_owner('memory_note_versions')}{_HUMAN_SELF})",
    "GRANT SELECT,INSERT,DELETE ON public.memory_note_versions TO pdos_next_app",
    f"CREATE POLICY memory_note_deletions_append ON public.memory_note_deletions FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_owner('memory_note_deletions')}{_HUMAN_SELF}{_note_parent('memory_note_deletions')})",
    "GRANT SELECT,INSERT ON public.memory_note_deletions TO pdos_next_app",
    f"CREATE POLICY memory_candidates_admit ON public.memory_candidates FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_owner('memory_candidates')}{_CANDIDATE_RUN}{_scope_readable('memory_candidates')})",
    f"CREATE POLICY memory_candidates_purge ON public.memory_candidates FOR DELETE TO pdos_next_app "
    f"USING({_owner('memory_candidates')}{_HUMAN_SELF})",
    "GRANT SELECT,INSERT,DELETE ON public.memory_candidates TO pdos_next_app",
    f"CREATE POLICY memory_candidate_decisions_append ON public.memory_candidate_decisions FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_owner('memory_candidate_decisions')}{_HUMAN_SELF}{_CANDIDATE_PARENT})",
    f"CREATE POLICY memory_candidate_decisions_purge ON public.memory_candidate_decisions FOR DELETE TO pdos_next_app "
    f"USING({_owner('memory_candidate_decisions')}{_HUMAN_SELF})",
    "GRANT SELECT,INSERT,DELETE ON public.memory_candidate_decisions TO pdos_next_app",
    f"CREATE POLICY memory_owner_settings_append ON public.memory_owner_settings FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_owner('memory_owner_settings')}{_HUMAN_SELF})",
    "GRANT SELECT,INSERT ON public.memory_owner_settings TO pdos_next_app",
    # P86 第 9 项: tenant switches on the existing append-only policy versions.
    "ALTER TABLE public.memory_tenant_policies ADD COLUMN notes_enabled BOOLEAN DEFAULT true NOT NULL",
    "ALTER TABLE public.memory_tenant_policies ADD COLUMN proposals_enabled BOOLEAN DEFAULT true NOT NULL",
    STATISTICS_SQL,
    f"REVOKE ALL ON FUNCTION public.memory_note_statistics(uuid) FROM {_REVOKED}",
    "GRANT EXECUTE ON FUNCTION public.memory_note_statistics(uuid) TO pdos_next_app",
)

SCHEMA_SQL = (*TABLE_SQL, *SECURITY_SQL)

DOWNGRADE_SQL = (
    *(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY" for table in (*TABLES, "memory_tenant_policies")),
    """DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.memory_notes)
     OR EXISTS(SELECT 1 FROM public.memory_candidates)
     OR EXISTS(SELECT 1 FROM public.memory_owner_settings)
     OR EXISTS(SELECT 1 FROM public.memory_tenant_policies
       WHERE NOT notes_enabled OR NOT proposals_enabled) THEN
     RAISE EXCEPTION 'Personal memory notes require s0_0865'; END IF; END $$""",
    "ALTER TABLE public.memory_tenant_policies FORCE ROW LEVEL SECURITY",
    "DROP FUNCTION public.memory_note_statistics(uuid)",
    "ALTER TABLE public.memory_tenant_policies DROP COLUMN proposals_enabled",
    "ALTER TABLE public.memory_tenant_policies DROP COLUMN notes_enabled",
    "DROP TABLE public.memory_candidate_decisions",
    "DROP TABLE public.memory_candidates",
    "DROP TABLE public.memory_note_versions",
    "DROP TABLE public.memory_note_deletions",
    "DROP TABLE public.memory_notes",
    "DROP TABLE public.memory_owner_settings",
)
