"""Owner endpoints for M1 memory: mode switch, pin/hide, usage, tenant policy.

Every write is by the human owner acting for themself (AI identities are refused
by the same database policies). Personal memory is not a business record, so
these are not T0/T1/T2 domain commands (memory design §5 第 4 条).
"""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select, text

from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import digest
from pdos_next.errors import DomainError

from .models import MemoryEpisode, MemoryEpisodeMark


class MarkInput(StrictModel):
    request_key: UUID
    kind: Literal["pin", "unpin", "hide", "unhide"]


def _episode(session, run_id):
    row = session.scalar(select(MemoryEpisode).where(MemoryEpisode.run_id == run_id))
    if row is None:
        raise DomainError("NOT_FOUND", "这次工作没有情景记录，或不在本人可读范围。", 404)
    return row


def mark(session, ctx, run_id, data):
    from pdos_next.agent.kernel.session_views import _human

    _human(session, ctx, None)
    row = _episode(session, run_id)
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                    {"key": f"memory-mark:{ctx.tenant_id}:{row.id}"})
    fingerprint = digest({"episode_id": row.id, "kind": data.kind})
    replay = session.scalar(select(MemoryEpisodeMark).where(
        MemoryEpisodeMark.owner_id == ctx.requester_id,
        MemoryEpisodeMark.request_key == data.request_key,
    ))
    if replay is not None:
        if replay.request_sha256 != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号对应不同的记忆标记。")
    else:
        session.add(MemoryEpisodeMark(
            tenant_id=ctx.tenant_id, owner_id=row.owner_id, session_id=row.session_id,
            episode_id=row.id, kind=data.kind, body={}, request_key=data.request_key,
            request_sha256=fingerprint,
        ))
        session.flush()
    from .recall import marks

    state = marks(session, [row.id]).get(row.id, {})
    return {"run_id": str(run_id), "pinned": bool(state.get("pinned")),
            "hidden": bool(state.get("hidden"))}


def record_correction(session, ctx, run, feedback):
    """Append the owner's run feedback to the episode (§14.9 纠正分流, destinations only)."""
    episode = session.scalar(select(MemoryEpisode).where(MemoryEpisode.run_id == run.id))
    if episode is None:
        return
    categories = list(feedback["categories"])
    fact = {"wrong_object", "wrong_value", "missing_source"}
    destination = "fact_owner" if set(categories) & fact else "skill_revision"
    key = UUID(feedback["idempotency_key"])
    existing = session.scalar(select(MemoryEpisodeMark).where(
        MemoryEpisodeMark.owner_id == ctx.requester_id, MemoryEpisodeMark.request_key == key))
    if existing is not None:
        return
    session.add(MemoryEpisodeMark(
        tenant_id=ctx.tenant_id, owner_id=episode.owner_id, session_id=episode.session_id,
        episode_id=episode.id, kind="correction",
        body={"categories": categories, "comment": feedback.get("comment", "")[:2000],
              "destination": destination, "status": "recorded"},
        request_key=key, request_sha256=digest({"episode_id": episode.id, **feedback}),
    ))
    session.flush()


def usage(session, ctx, run):
    """Which memory records this Run actually used, rechecked for the owner now."""
    from pdos_next.agent.kernel.run_reconciliation import owner

    from .recall import first_sentence, recheck

    owner(session, ctx, run)
    value = run.versions.get("memory_usage") or {}
    run_ids = [UUID(item) for item in value.get("episodes", [])]
    rows = session.scalars(
        select(MemoryEpisode).where(MemoryEpisode.run_id.in_(run_ids))
    ).all() if run_ids else []
    by_run = {row.run_id: row for row in rows}
    ordered = [by_run[item] for item in run_ids if item in by_run]
    kept, _access = recheck(session, run, ordered, limit=len(ordered) or 1)
    items = [{"run_id": str(row.run_id), "session_id": str(row.session_id),
              "as_of": row.created_at.isoformat(), "goal": first_sentence(row.goal),
              "scope": scope, "kind": "episode",
              "in_catalog": str(row.run_id) in value.get("catalog", [])}
             for row, _state, scope, _receipts in kept]
    sessions = [item for item in value.get("sessions", [])]
    return {
        "version": "memory-usage/v1",
        "run_id": str(run.id),
        "count": len(items) + len(sessions),
        "items": items,
        "sessions": [{"session_id": item} for item in sessions],
        "withheld": len(run_ids) - len(items),
        "retrieval": value.get("retrieval"),
        "note": "这些是你本人以往的工作记录，只作背景，不是回答依据。",
    }


def router(*, transaction, context_dependency):
    from pdos_next.agent.kernel.models import AgentRun
    from pdos_next.agent.kernel.session_presentation import _target
    from pdos_next.agent.kernel.session_views import _human

    from . import mode, policy

    result = APIRouter()

    @result.get("/v1/personal/agent-sessions/{session_id}/memory-mode")
    @result.get("/v1/categories/{category_id}/agent-sessions/{session_id}/memory-mode")
    def reading_mode(session_id: UUID, ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            _human(session, ctx, None)
            _target(session, ctx, session_id, None)
            return mode.view(mode.latest(session, session_id), session_id)

    @result.post("/v1/personal/agent-sessions/{session_id}/memory-mode")
    @result.post("/v1/categories/{category_id}/agent-sessions/{session_id}/memory-mode")
    def changing_mode(session_id: UUID, data: mode.ModeInput, ctx=context_dependency):
        with transaction(ctx) as session:
            _human(session, ctx, None)
            _target(session, ctx, session_id, None, lock=True)
            return mode.change(session, ctx, session_id, data)

    @result.post("/v1/personal/memory/episodes/{run_id}/marks")
    @result.post("/v1/categories/{category_id}/memory/episodes/{run_id}/marks")
    def marking(run_id: UUID, data: MarkInput, ctx=context_dependency):
        with transaction(ctx) as session:
            return mark(session, ctx, run_id, data)

    @result.get("/v1/personal/agent-runs/{run_id}/memory-usage")
    @result.get("/v1/categories/{category_id}/agent-runs/{run_id}/memory-usage")
    def reading_usage(run_id: UUID, ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            return usage(session, ctx, session.get(AgentRun, run_id))

    @result.get("/v1/personal/memory-policy")
    def reading_policy(ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            _human(session, ctx, None)
            return policy.view(policy.current(session))

    @result.post("/v1/personal/memory-policy")
    def changing_policy(data: policy.PolicyInput, ctx=context_dependency):
        with transaction(ctx) as session:
            _human(session, ctx, None)
            return policy.change(session, ctx, data)

    return result
