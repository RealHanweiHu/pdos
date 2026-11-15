"""Read-tool adapter for memory.search; the person and range come from the Run."""

from sqlalchemy import exists, select

from pdos_next.agent.kernel.tool_arguments import tool_arguments
from pdos_next.core.service import digest

from .recall import MemorySearchInput, search, unavailable


def _started_call(session, run, arguments):
    """The single started memory.search call these exact arguments belong to."""
    from pdos_next.agent.kernel.models import AgentToolCall

    rows = session.scalars(select(AgentToolCall.id).where(
        AgentToolCall.run_id == run.id, AgentToolCall.tool == "memory.search",
        AgentToolCall.state == "started",
        AgentToolCall.input_digest == digest(["memory.search", arguments]),
    )).all()
    return rows[0] if len(rows) == 1 else None


def semantic_query(store, embedder, scope, arguments):
    """Query vector for the owner's episode vectors, run-accounted (P30, P85 第 3 项).

    None when “本人会话记录” is not selected: then nothing goes out. Otherwise the
    status says why recall stays keyword-only, never a silent empty result.
    """
    from .models import MemoryEpisodeVector
    from .policy import episode_vectors

    with store.transaction(scope, lock=True) as (session, run):
        if unavailable(run, session) is not None:
            return None
        enabled = episode_vectors(session)
        if not enabled["enabled"]:
            return None
        if embedder is None or scope.isolation != "main":
            return {"status": "query_port_unavailable"}
        if not session.scalar(select(exists().where(
                MemoryEpisodeVector.owner_id == run.requester_id,
                MemoryEpisodeVector.profile_version_id == enabled["profile_version_id"]))):
            return {"status": "not_indexed_yet"}
        snapshot = embedder.frozen_profile(session, scope, run)
        if snapshot is None or str(snapshot.profile_version_id) != enabled["profile_version_id"]:
            return {"status": "query_profile_mismatch"}
        call_id = _started_call(session, run, arguments)
    if call_id is None:
        return {"status": "query_unavailable"}
    result = embedder.prepare(scope, call_id, arguments)
    if result.status != "ready" or result.vector is None:
        return {"status": result.status}
    return {"status": "ready", "vector": result.vector,
            "profile_version_id": snapshot.profile_version_id}


def memory_search(store, query_embedding=None):
    def handler(scope, arguments):
        payload = tool_arguments(MemorySearchInput, arguments)
        embedder = query_embedding() if callable(query_embedding) else query_embedding
        semantic = (semantic_query(store, embedder, scope, arguments)
                    if "episode" in payload.kinds else None)
        with store.transaction(scope, lock=True) as (session, run):
            from .mode import turn_notice

            return turn_notice(run, search(session, run, payload, semantic=semantic))

    return handler
