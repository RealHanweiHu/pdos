"""Private metadata for an explicit carried-source exclusion; no ranking side effect."""

from uuid import UUID, uuid4

from sqlalchemy import func, select

from pdos_next.enterprise_search import assistant_ledger as ledger
from pdos_next.errors import DomainError

from .execution import scope_for_run
from .models import AgentEvent, AgentRun
from .run_reconciliation import owner

KIND = "retrieval_feedback"


def _unavailable():
    raise DomainError("SOURCE_UNAVAILABLE", "原资料的反馈来源无法核对。")


def _source(item):
    """Only fixed identity metadata; never copy query, titles, text, quotes or locators."""
    try:
        version = item["source_revision"]
        if type(version) is not int or version < 1:
            raise ValueError
        return {
            "source_type": item["source_type"],
            "source_id": str(UUID(item["source_id"])),
            "object_id": str(UUID(item["object_id"])),
            "source_revision": version,
            "content_hash": item.get("content_hash"),
        }
    except (KeyError, TypeError, ValueError):
        _unavailable()


def _from_call(origin, call, item):
    if item.get("citation_id") != ledger.citation_id(origin.id, call.id, item):
        _unavailable()
    searched = call.tool == "assistant.search"
    ranking = call.result.get("ranking_version") if searched else None
    rank = item.get("rank") if searched else None
    return {
        "origin": "search" if searched else "materials",
        "origin_run_id": str(origin.id),
        "origin_call_id": str(call.id),
        "citation_id": item["citation_id"],
        "source": _source(item),
        "candidate": {
            "chunk_id": item.get("chunk_id") if searched else None,
            "rank": rank if type(rank) is int and rank > 0 else None,
            "ranking_version": ranking if isinstance(ranking, str) and ranking else None,
        },
    }


def provenance(session, run, entry, body):
    """Resolve a server-accepted selection through the actual root read or bound read-set."""
    identity = entry["id"]
    if entry["kind"] == "citation":
        from pdos_next.enterprise_search.assistant_inheritance import _aliases, registry

        roots, rows = registry(session, run, include_self=True)
        root = roots.get(_aliases(session, rows, roots).get(identity))
        if root is None:
            _unavailable()
        origin = session.get(AgentRun, UUID(root[0]))
        if origin is None:
            _unavailable()
        for call, _arguments in ledger.completed(
            session, scope_for_run(origin), ledger.ROOT_TOOLS, archive=True
        ):
            for item in call.result.get("items", []):
                if item == root[1]:
                    return _from_call(origin, call, item)
        _unavailable()
    if entry["kind"] != "artifact":
        _unavailable()
    selected = next(
        (
            item
            for item in body["focus_objects"]
            if item["kind"] == "artifact" and item["id"] == identity
        ),
        None,
    )
    if selected is None:
        _unavailable()
    origin = session.get(AgentRun, UUID(selected["run_id"]))
    if (
        origin is None
        or origin.session_id != run.session_id
        or origin.requester_id != run.requester_id
        or not any(
            ref["artifact_id"] == identity and ref["expected_revision"] == selected["version"]
            for ref in origin.read_sources
        )
    ):
        _unavailable()
    calls = ledger.completed(session, scope_for_run(origin), ledger.ROOT_TOOLS, archive=True)
    # An artifact selection can have several real reads. Keep the last actual
    # matching read in its binding Run; no browser rank or current ranking constant.
    for call, _arguments in reversed(calls):
        for item in reversed(call.result.get("items", [])):
            if (
                item.get("source_type") == "artifact"
                and item.get("source_id") == identity
                and item.get("source_revision") == selected["version"]
            ):
                return _from_call(origin, call, item)
    # A selected but unsearched material is already a valid exclusion today.
    # Do not invent a candidate or add a search requirement merely for feedback.
    return {
        "origin": "bound_source",
        "origin_run_id": str(origin.id),
        "origin_call_id": None,
        "citation_id": None,
        "source": {
            "source_type": "artifact",
            "source_id": identity,
            "object_id": identity,
            "source_revision": selected["version"],
            "content_hash": None,
        },
        "candidate": {"chunk_id": None, "rank": None, "ranking_version": None},
    }


def record(session, ctx, run, state, identity):
    """Caller holds Run FOR UPDATE before the work-state advisory lock, in the same UOW."""
    owner(session, ctx, run)
    entry = next((item for item in state.body["exclusions"] if item["id"] == identity), None)
    if (
        entry is None
        or state.origin != "human"
        or state.request_key is None
        or state.session_id != run.session_id
        or state.owner_id != ctx.requester_id
    ):
        _unavailable()
    previous = session.scalar(
        select(AgentEvent).where(
            AgentEvent.run_id == run.id,
            AgentEvent.body["type"].astext == KIND,
            AgentEvent.body["request_key"].astext == str(state.request_key),
        )
    )
    if previous is not None:
        if previous.body.get("request_digest") != state.request_sha256 or previous.body.get(
            "work_state_id"
        ) != str(state.id):
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "原请求编号对应不同的检索反馈。")
        return previous.id
    proof = provenance(session, run, entry, state.body)
    identity = uuid4()
    sequence = (
        session.scalar(
            select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                AgentEvent.run_id == run.id,
            )
        )
        + 1
    )
    event = AgentEvent(
        id=identity,
        tenant_id=run.tenant_id,
        run_id=run.id,
        sequence=sequence,
        body={
            "type": KIND,
            "version": "retrieval-feedback/v1",
            "feedback_id": str(identity),
            "recorded_by": str(ctx.requester_id),
            "request_key": str(state.request_key),
            "request_digest": state.request_sha256,
            "work_state_id": str(state.id),
            "work_state_revision": state.revision,
            "action": "not_relevant",
            "selection": {"kind": entry["kind"], "id": entry["id"]},
            **proof,
        },
    )
    session.add(event)
    session.flush()
    return event.id
