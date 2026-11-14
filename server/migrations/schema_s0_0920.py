"""Guards on memory proposals (P121 第 8 项): suppression fingerprints, discussion voids.

占位号：s0_0920 是并行工作区的占位号，集成时按真实 head 重排（revision、down_revision
与本快照文件名一起改）。

``memory_suppressions``: written only by the human owner acting for themself, in the
same transaction as the purge of a note (遗忘). A row holds a salted digest of the
purged statement and references to the Runs whose words it came from. It never holds
text. The owner (and the Run's server path reading for the requester) can read it;
only the owner acting for themself can remove it, which happens when they confirm
the same statement again.

``memory_proposal_voids``: one content-free row per conversation Run in which the
owner said "这只是讨论，不算决定". Stored like a candidate: by the server path of that
Run, only for the Run's own human requester, only while the Run is still active.
Append-only.
"""

# ruff: noqa: E501 -- Reviewed applied SQL literals remain byte-identical.

# Filled from the exact reviewed ORM tables (pdos_next.agent.memory.models).
TABLE_SQL = (
    "\nCREATE TABLE memory_suppressions (\n\towner_id UUID NOT NULL, \n\tnote_id UUID NOT NULL, \n\tsalt VARCHAR(32) NOT NULL, \n\tfingerprint VARCHAR(64) NOT NULL, \n\tsource_spans JSONB NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, note_id, fingerprint), \n\tFOREIGN KEY(tenant_id, note_id) REFERENCES memory_notes (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT memory_suppression_digest CHECK (salt ~ '^[0-9a-f]{32}$' AND fingerprint ~ '^[0-9a-f]{64}$'), \n\tCONSTRAINT memory_suppression_spans CHECK (jsonb_typeof(source_spans)='array')\n)\n\n",
    'CREATE INDEX ix_memory_suppressions_owner ON memory_suppressions (tenant_id, owner_id, created_at)',
    'CREATE INDEX ix_memory_suppressions_tenant_id ON memory_suppressions (tenant_id)',
    '\nCREATE TABLE memory_proposal_voids (\n\towner_id UUID NOT NULL, \n\tsession_id UUID NOT NULL, \n\trun_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, run_id), \n\tFOREIGN KEY(tenant_id, run_id) REFERENCES agent_runs (tenant_id, id), \n\tFOREIGN KEY(tenant_id, session_id) REFERENCES agent_sessions (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id)\n)\n\n',
    'CREATE INDEX ix_memory_proposal_voids_session ON memory_proposal_voids (tenant_id, session_id, created_at)',
    'CREATE INDEX ix_memory_proposal_voids_tenant_id ON memory_proposal_voids (tenant_id)',
)

TABLES = ("memory_suppressions", "memory_proposal_voids")

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

# A suppression belongs to a note of the same owner that this owner has purged.
_PURGED_NOTE = """ AND EXISTS(SELECT 1 FROM public.memory_notes n
   WHERE n.tenant_id=memory_suppressions.tenant_id AND n.id=memory_suppressions.note_id
   AND n.owner_id=memory_suppressions.owner_id)"""

# A void is stored only while its own conversation Run is still active and only
# for that Run's human requester, exactly as a candidate is (s0_0865).
_VOID_RUN = """ AND EXISTS(SELECT 1 FROM public.agent_runs r WHERE r.tenant_id=memory_proposal_voids.tenant_id
   AND r.id=memory_proposal_voids.run_id AND r.requester_id=memory_proposal_voids.owner_id
   AND r.session_id=memory_proposal_voids.session_id AND r.trigger='conversation'
   AND r.state IN ('queued','running','waiting_input'))
 AND EXISTS(SELECT 1 FROM public.agent_sessions s WHERE s.tenant_id=memory_proposal_voids.tenant_id
   AND s.id=memory_proposal_voids.session_id AND s.owner_id=memory_proposal_voids.owner_id)"""

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
    "CREATE TRIGGER memory_proposal_voids_append_only BEFORE DELETE ON public.memory_proposal_voids "
    "FOR EACH ROW EXECUTE FUNCTION public.kernel_append_only()",
    f"CREATE POLICY memory_suppressions_append ON public.memory_suppressions FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_owner('memory_suppressions')}{_HUMAN_SELF}{_PURGED_NOTE})",
    f"CREATE POLICY memory_suppressions_lift ON public.memory_suppressions FOR DELETE TO pdos_next_app "
    f"USING({_owner('memory_suppressions')}{_HUMAN_SELF})",
    "GRANT SELECT,INSERT,DELETE ON public.memory_suppressions TO pdos_next_app",
    f"CREATE POLICY memory_proposal_voids_admit ON public.memory_proposal_voids FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_owner('memory_proposal_voids')}{_VOID_RUN})",
    "GRANT SELECT,INSERT ON public.memory_proposal_voids TO pdos_next_app",
)

SCHEMA_SQL = (*TABLE_SQL, *SECURITY_SQL)

DOWNGRADE_SQL = (
    *(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY" for table in TABLES),
    """DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.memory_suppressions)
     OR EXISTS(SELECT 1 FROM public.memory_proposal_voids) THEN
     RAISE EXCEPTION 'Memory proposal guards require s0_0920'; END IF; END $$""",
    "DROP TABLE public.memory_proposal_voids",
    "DROP TABLE public.memory_suppressions",
)
