"""Run-bound citations authored by actual completed search reads, never model JSON."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

from pdos_next.agent_kernel.deterministic_proofs import _historical_read, archived_citation_read
from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.errors import DomainError
from pdos_next.service import digest

ROOT_TOOLS = frozenset({"assistant.search", "assistant.materials.read"})
TOOLS = ROOT_TOOLS | {"assistant.extract", "assistant.citations.read", "assistant.compare"}


def deny(reason):
    raise DomainError(
        "FORBIDDEN_SCOPE",
        "引用须来自本次运行的实际读取账本。",
        403,
        detail={"reason_key": "assistant_" + reason},
    )


def citation_id(run_id, call_id, item):
    fixed = {key: value for key, value in item.items() if key != "citation_id"}
    return str(uuid5(NAMESPACE_URL, digest([str(run_id), str(call_id), fixed])))


def completed(session, scope, tools=TOOLS, *, archive=False):
    calls = session.scalars(
        select(AgentToolCall)
        .where(
            AgentToolCall.tenant_id == scope.tenant_id,
            AgentToolCall.run_id == scope.run_id,
            AgentToolCall.tool.in_(tools),
            AgentToolCall.state == "completed",
        )
        .order_by(AgentToolCall.created_at, AgentToolCall.id)
    ).all()
    result = []
    for call in calls:
        if archive:
            _run, actual, binding, arguments = archived_citation_read(
                session, scope, call.id, deny=deny
            )
        else:
            _run, actual, binding, arguments = _historical_read(
                session, scope, call.id, "ordinary/v1", deny=deny
            )
        if binding.isolation != "main" or actual.tool not in tools:
            deny("isolation_invalid")
        result.append(
            (
                SimpleNamespace(id=actual.id, tool=actual.tool, result=deepcopy(actual.result)),
                deepcopy(arguments),
            )
        )
    return result


def search_issued(session, scope, *, archive=False):
    result = {}
    for call, _arguments in completed(session, scope, ROOT_TOOLS, archive=archive):
        for item in call.result.get("items", []):
            if not isinstance(item, dict) or item.get("citation_id") != citation_id(
                scope.run_id, call.id, item
            ):
                deny("citation_invalid")
            identity = str(UUID(item["citation_id"]))
            result[identity] = deepcopy(item)
    return result


def issued(session, scope, *, archive=False):
    from pdos_next.agent_kernel.models import AgentRun

    from .assistant_inheritance import expand

    result = search_issued(session, scope, archive=archive)
    run = session.get(AgentRun, scope.run_id)
    if run is None:
        deny("run_unreadable")
    frozen = run.versions.get("work_state", {})
    refs = list(frozen.get("citations", []))
    if refs and digest(frozen) != run.versions.get("work_state_digest"):
        deny("work_state_changed")
    for call, _args in completed(session, scope, {"assistant.citations.read"}, archive=archive):
        refs.extend(call.result["items"])
    if refs:
        result.update(expand(session, run, refs))
    return result


def select_issued(session, scope, identities):
    actual = issued(session, scope)
    selected = {str(identity): actual.get(str(identity)) for identity in identities}
    if any(value is None for value in selected.values()):
        deny("citation_not_issued")
    return selected


def carried(session, scope):
    from pdos_next.agent_kernel.execution import scope_for_run
    from pdos_next.agent_kernel.models import AgentRun
    from pdos_next.agent_kernel.work_state_models import AgentWorkState

    run = session.get(AgentRun, scope.run_id)
    if run is None:
        deny("run_unreadable")
    interrupted = run.state in {"failed", "cancelled"}
    own = issued(session, scope, archive=interrupted)
    origins = set()
    frozen = run.versions.get("conversation_memory", {})
    pages = [frozen]
    # Page descriptors freeze cursors and digests, not the returned history. Use
    # the immutable, execution-bound read result that actually entered context.
    pages.extend(call.result for call, _args in completed(
        session, scope, {"conversation.history"}, archive=interrupted
    ))
    for page in pages:
        origins.update(
            UUID(turn["run_id"])
            for turn in page.get("turns", [])
            if turn.get("historical_outcome") is not None
        )
    state = run.versions.get("work_state", {})
    if state.get("revision"):
        stored = session.scalar(
            select(AgentWorkState).where(
                AgentWorkState.session_id == run.session_id,
                AgentWorkState.revision == state["revision"],
            )
        )
        if state.get("unfinished") or state.get("questions"):
            if stored is None:
                deny("work_state_unreadable")
            origins.add(UUID(stored.body["current_goal"]["run_id"]))
    historical = {}
    rows = (
        session.scalars(
            select(AgentRun).where(
                AgentRun.id.in_(origins),
                AgentRun.session_id == run.session_id,
                AgentRun.requester_id == run.requester_id,
            )
        ).all()
        if origins
        else []
    )
    if {row.id for row in rows} != origins:
        deny("history_unreadable")
    for origin in rows:
        historical.update(issued(session, scope_for_run(origin), archive=True))
    # Reissued refs are new IDs for historical, fixed reads. A later source
    # update must not invalidate their frozen metadata; extraction still requires
    # the exact original body. Revocation/withdrawal/scan checks remain current.
    inherited = {cid for cid, item in own.items() if "origin_run_id" in item}
    return {**historical, **own}, (set(historical) - set(own)) | inherited
