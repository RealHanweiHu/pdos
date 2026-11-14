"""Owner deletes a Session; episode usage lists the personal notes used (P121 第 8 项, D475).

PLACEHOLDER NUMBER: written in a parallel worktree on head s0_0887, now on s0_0888.
At integration the revision, down_revision and this file's name move together to
the real head (不可协商项 3). If another branch also rewrites
``memory_project_episode``, merge the function bodies: this file derives its body
from the s0_0855 text by anchors (unchanged through s0_0888, checked 2026-11-14).

Deleting a Session removes its episodes, episode marks, keyword index rows (both
the ``episode`` and the ``answer`` row of s0_0888; the delete is by Session, not by
``source_kind``) and episode vectors, plus proposals from it that the owner never
adopted. One row without content stays in ``memory_session_deletions``. Run
records, action receipts and audit are not touched (I17, P83 D193).

Those tables stay append-only. The only way to delete from them is
``memory_delete_session``, which checks: the caller acts for themself
(scope_actor = scope_requester), is an active human, and owns the Session. An AI
writer identity acting for the owner, or anyone else, is refused. The row guard
on each table lets a DELETE through only for a Session that has a deletion
record, and nobody but that function can write one.

Nothing comes back: index rows, vectors and marks need their episode (foreign
key and insert policy), and the episode projection skips a deleted Session.
"""

# ruff: noqa: E501 -- Reviewed applied SQL literals remain byte-identical.

from migrations.schema_s0_0855 import PROJECTION_SQL as _AT_S0_0855

# Filled from the exact reviewed ORM table (pdos_next.agent.memory.models).
TABLE_SQL = (
    "\nCREATE TABLE memory_session_deletions (\n\towner_id UUID NOT NULL, \n\tsession_id UUID NOT NULL, \n\tpurged_episodes INTEGER NOT NULL, \n\tpurged_marks INTEGER NOT NULL, \n\tpurged_index_rows INTEGER NOT NULL, \n\tpurged_vectors INTEGER NOT NULL, \n\tpurged_candidates INTEGER NOT NULL, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, session_id), \n\tUNIQUE (tenant_id, owner_id, request_key), \n\tFOREIGN KEY(tenant_id, session_id) REFERENCES agent_sessions (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT memory_session_deletion_counts CHECK (purged_episodes >= 0 AND purged_marks >= 0 AND purged_index_rows >= 0 AND purged_vectors >= 0 AND purged_candidates >= 0), \n\tCONSTRAINT memory_session_deletion_request_sha256 CHECK (request_sha256 ~ '^[0-9a-f]{64}$')\n)\n\n",
    "CREATE INDEX ix_memory_session_deletions_owner ON memory_session_deletions (tenant_id, owner_id, created_at)",
    "CREATE INDEX ix_memory_session_deletions_tenant_id ON memory_session_deletions (tenant_id)",
)

TABLE = "memory_session_deletions"
# (table, the append-only trigger it already has)
GUARDED = (
    ("memory_episodes", "memory_episodes_append_only"),
    ("memory_episode_marks", "memory_episode_marks_append_only"),
    ("memory_index", "memory_index_append_only"),
    ("memory_episode_vectors", "memory_episode_vectors_append_only"),
)

_LOCK = "hashtextextended('memory-session-delete:'||{tenant}::text||':'||{session}::text,0)"

# The owner, or a Run reading for that owner, sees that a Session was deleted.
_READ = """tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid
 AND owner_id=public.scope_requester()
 AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=memory_session_deletions.tenant_id
   AND p.id=public.scope_actor() AND p.active)
 AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=memory_session_deletions.tenant_id
   AND p.id=public.scope_requester() AND p.kind='human' AND p.active)"""

GUARD_SQL = """
CREATE FUNCTION public.memory_session_purge_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path TO pg_catalog, public, pg_temp AS $memory$
BEGIN
 IF TG_OP='DELETE' AND EXISTS(SELECT 1 FROM public.memory_session_deletions d
   WHERE d.tenant_id=OLD.tenant_id AND d.session_id=OLD.session_id
    AND d.owner_id=OLD.owner_id) THEN
  RETURN OLD;
 END IF;
 RAISE EXCEPTION 'Kernel evidence is append-only';
END;
$memory$
"""

DELETE_SQL = f"""
CREATE FUNCTION public.memory_delete_session(t uuid,sid uuid,request uuid,fingerprint text)
RETURNS public.memory_session_deletions
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog, public, pg_temp AS $memory$
DECLARE
 me uuid := public.scope_requester();
 target public.agent_sessions%ROWTYPE;
 done public.memory_session_deletions%ROWTYPE;
 episodes integer; marks integer; index_rows integer; vectors integer; candidates integer;
 removed integer;
BEGIN
 -- The human owner acting for themself. An AI writer identity acting for the
 -- owner has scope_actor <> scope_requester and stops here.
 IF t IS NULL OR sid IS NULL OR request IS NULL OR fingerprint IS NULL
  OR t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
  OR me IS NULL OR public.scope_actor() IS DISTINCT FROM me
  OR NOT EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=t AND p.id=me
   AND p.kind='human' AND p.active) THEN
  RAISE EXCEPTION 'Only the human owner deletes their own Session' USING ERRCODE='42501';
 END IF;
 PERFORM pg_advisory_xact_lock({_LOCK.format(tenant="t", session="sid")});
 SELECT * INTO target FROM public.agent_sessions a WHERE a.tenant_id=t AND a.id=sid;
 IF target.id IS NULL OR target.owner_id IS DISTINCT FROM me
  OR NOT (target.category_id IS NULL OR public.category_access(t,target.category_id)) THEN
  RAISE EXCEPTION 'Only the human owner deletes their own Session' USING ERRCODE='42501';
 END IF;
 SELECT * INTO done FROM public.memory_session_deletions d
  WHERE d.tenant_id=t AND d.session_id=sid;
 IF done.id IS NOT NULL THEN
  IF done.request_key=request AND done.request_sha256=fingerprint THEN RETURN done; END IF;
  RAISE EXCEPTION 'Session is already deleted' USING ERRCODE='23505';
 END IF;
 IF EXISTS(SELECT 1 FROM public.agent_runs r WHERE r.tenant_id=t AND r.session_id=sid
   AND r.state IN ('queued','running','waiting_input')) THEN
  RAISE EXCEPTION 'Session has a Run in progress' USING ERRCODE='55006';
 END IF;
 -- Index rows, vectors and marks reference their episode; holding the episodes
 -- makes a concurrent background insert wait and then fail on the missing parent.
 PERFORM 1 FROM public.memory_episodes e WHERE e.tenant_id=t AND e.session_id=sid FOR UPDATE;
 SELECT count(*) INTO episodes FROM public.memory_episodes e
  WHERE e.tenant_id=t AND e.session_id=sid;
 SELECT count(*) INTO marks FROM public.memory_episode_marks m
  WHERE m.tenant_id=t AND m.session_id=sid;
 SELECT count(*) INTO index_rows FROM public.memory_index i
  WHERE i.tenant_id=t AND i.session_id=sid;
 SELECT count(*) INTO vectors FROM public.memory_episode_vectors v
  WHERE v.tenant_id=t AND v.session_id=sid;
 -- Proposals from this Session the owner never adopted. An adopted one is the
 -- source record of a note the owner confirmed, and goes when that note goes.
 SELECT count(*) INTO candidates FROM public.memory_candidates c
  WHERE c.tenant_id=t AND c.session_id=sid AND NOT EXISTS(
   SELECT 1 FROM public.memory_candidate_decisions d WHERE d.tenant_id=c.tenant_id
    AND d.candidate_id=c.id AND d.decision='adopted');
 INSERT INTO public.memory_session_deletions(id,tenant_id,created_at,owner_id,session_id,
   purged_episodes,purged_marks,purged_index_rows,purged_vectors,purged_candidates,
   request_key,request_sha256)
 VALUES (gen_random_uuid(),t,clock_timestamp(),me,sid,episodes,marks,index_rows,vectors,
   candidates,request,fingerprint)
 RETURNING * INTO done;
 DELETE FROM public.memory_episode_vectors v WHERE v.tenant_id=t AND v.session_id=sid;
 GET DIAGNOSTICS removed = ROW_COUNT;
 IF removed<>vectors THEN RAISE EXCEPTION 'Episode vectors changed during deletion'; END IF;
 DELETE FROM public.memory_index i WHERE i.tenant_id=t AND i.session_id=sid;
 GET DIAGNOSTICS removed = ROW_COUNT;
 IF removed<>index_rows THEN RAISE EXCEPTION 'Memory index changed during deletion'; END IF;
 DELETE FROM public.memory_episode_marks m WHERE m.tenant_id=t AND m.session_id=sid;
 GET DIAGNOSTICS removed = ROW_COUNT;
 IF removed<>marks THEN RAISE EXCEPTION 'Episode marks changed during deletion'; END IF;
 DELETE FROM public.memory_candidate_decisions d USING public.memory_candidates c
  WHERE c.tenant_id=t AND c.session_id=sid AND d.tenant_id=c.tenant_id
   AND d.candidate_id=c.id AND d.decision<>'adopted';
 DELETE FROM public.memory_candidates c WHERE c.tenant_id=t AND c.session_id=sid
  AND NOT EXISTS(SELECT 1 FROM public.memory_candidate_decisions d
   WHERE d.tenant_id=c.tenant_id AND d.candidate_id=c.id);
 GET DIAGNOSTICS removed = ROW_COUNT;
 IF removed<>candidates THEN RAISE EXCEPTION 'Memory proposals changed during deletion'; END IF;
 DELETE FROM public.memory_episodes e WHERE e.tenant_id=t AND e.session_id=sid;
 GET DIAGNOSTICS removed = ROW_COUNT;
 IF removed<>episodes THEN RAISE EXCEPTION 'Episodes changed during deletion'; END IF;
 RETURN done;
END;
$memory$
"""

# ---------------------------------------------------------------------------
# Episode projection: skip a deleted Session; list the personal notes used.

_HEAD = "\nCREATE FUNCTION public.memory_project_episode() RETURNS trigger"
_OFF = " IF memory_off THEN RETURN NULL; END IF;\n"
_DELETED = f""" -- A Run finishing while its Session is being deleted waits here, then sees the record.
 PERFORM pg_advisory_xact_lock_shared({_LOCK.format(tenant="NEW.tenant_id", session="NEW.session_id")});
 IF EXISTS(SELECT 1 FROM public.memory_session_deletions d
   WHERE d.tenant_id=NEW.tenant_id AND d.session_id=NEW.session_id) THEN RETURN NULL; END IF;
"""
_USAGE = """   'sessions', CASE WHEN jsonb_typeof(r.versions#>'{memory_usage,sessions}')='array'
     THEN r.versions#>'{memory_usage,sessions}' ELSE '[]'::jsonb END),
"""
# D475 第 1 条: the notes this Run used, by ID, version and zone. Never their text.
_NOTES = """   'sessions', CASE WHEN jsonb_typeof(r.versions#>'{memory_usage,sessions}')='array'
     THEN r.versions#>'{memory_usage,sessions}' ELSE '[]'::jsonb END,
   'notes', coalesce((SELECT jsonb_agg(jsonb_build_object(
      'note_id',f->>'note_id','revision',f->'revision','zone',f->>'zone') ORDER BY n)
     FROM jsonb_array_elements(CASE
       WHEN jsonb_typeof(r.versions#>'{memory_usage,notes}')='array'
       THEN r.versions#>'{memory_usage,notes}' ELSE '[]'::jsonb END)
      WITH ORDINALITY AS x(f,n)
     WHERE jsonb_typeof(f)='object' AND f->>'note_id' IS NOT NULL),'[]'::jsonb)),
"""
_VERSION = "projected,'memory-episode/v1')"

for _anchor in (_HEAD, _OFF, _USAGE, _VERSION):
    if _AT_S0_0855.count(_anchor) != 1:
        raise RuntimeError("s0_0855 episode projection anchor changed")

PREVIOUS_PROJECTION = _AT_S0_0855.replace(_HEAD, _HEAD.replace("CREATE", "CREATE OR REPLACE"))
PROJECTION_SQL = (
    PREVIOUS_PROJECTION
    .replace(_OFF, _OFF + _DELETED)
    .replace(_USAGE, _NOTES)
    .replace(_VERSION, "projected,'memory-episode/v2')")
)

_REVOKED = "PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"

SECURITY_SQL = (
    f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY",
    f"ALTER TABLE public.{TABLE} FORCE ROW LEVEL SECURITY",
    f"CREATE POLICY owner_internal ON public.{TABLE} TO pdos_next_owner USING(true) WITH CHECK(true)",
    f"REVOKE ALL ON public.{TABLE} FROM {_REVOKED}",
    f"CREATE TRIGGER {TABLE}_append_only BEFORE UPDATE OR DELETE ON public.{TABLE} "
    "FOR EACH ROW EXECUTE FUNCTION public.kernel_append_only()",
    f"CREATE POLICY {TABLE}_read ON public.{TABLE} FOR SELECT TO pdos_next_app USING({_READ})",
    # No INSERT grant or policy: only memory_delete_session writes a deletion record.
    f"GRANT SELECT ON public.{TABLE} TO pdos_next_app",
    GUARD_SQL,
    f"REVOKE ALL ON FUNCTION public.memory_session_purge_guard() FROM {_REVOKED}",
    *(statement for table, trigger in GUARDED for statement in (
        f"DROP TRIGGER {trigger} ON public.{table}",
        f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON public.{table} "
        "FOR EACH ROW EXECUTE FUNCTION public.memory_session_purge_guard()",
    )),
    DELETE_SQL,
    f"REVOKE ALL ON FUNCTION public.memory_delete_session(uuid,uuid,uuid,text) FROM {_REVOKED}",
    "GRANT EXECUTE ON FUNCTION public.memory_delete_session(uuid,uuid,uuid,text) TO pdos_next_app",
    PROJECTION_SQL,
)

SCHEMA_SQL = (*TABLE_SQL, *SECURITY_SQL)

DOWNGRADE_SQL = (
    f"ALTER TABLE public.{TABLE} NO FORCE ROW LEVEL SECURITY",
    f"""DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.{TABLE}) THEN
     RAISE EXCEPTION 'Session deletion records require s0_0940'; END IF; END $$""",
    PREVIOUS_PROJECTION,
    "DROP FUNCTION public.memory_delete_session(uuid,uuid,uuid,text)",
    *(statement for table, trigger in GUARDED for statement in (
        f"DROP TRIGGER {trigger} ON public.{table}",
        f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON public.{table} "
        "FOR EACH ROW EXECUTE FUNCTION public.kernel_append_only()",
    )),
    "DROP FUNCTION public.memory_session_purge_guard()",
    f"DROP TABLE public.{TABLE}",
)
