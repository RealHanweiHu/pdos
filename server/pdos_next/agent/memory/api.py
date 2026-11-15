"""Owner endpoints for personal memory: mode, pin/hide, usage, notes, candidates, policy.

Every write is by the human owner acting for themself (AI identities are refused
by the same database policies). Personal memory is not a business record, so
these are not T0/T1/T2 domain commands (memory design §5 第 4 条).
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
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
    notes = note_usage(session, value.get("notes") or [])
    from .scope_assemble import usage as scope_usage

    scope_notes = scope_usage(session, value.get("scope_notes") or [])
    return {
        "version": "memory-usage/v1",
        "run_id": str(run.id),
        "count": len(items) + len(sessions) + len(notes) + len(scope_notes),
        "items": items,
        "sessions": [{"session_id": item} for item in sessions],
        "notes": notes,
        # P87 第 10 项: team notes are listed apart from the owner's own memory.
        "scope_notes": scope_notes,
        "withheld": len(run_ids) - len(items),
        "retrieval": value.get("retrieval"),
        "note": "这些是你本人以往的工作记录和你确认过的记忆条目，只作背景或口径，不是回答依据。",
    }


def note_usage(session, used):
    """Personal notes this Run used, as they are now: purged ones say only that."""
    from .models import MemoryNoteDeletion
    from .notes import KIND_LABELS, _latest

    result = []
    for item in used:
        identity = UUID(item["note_id"])
        if session.scalar(select(MemoryNoteDeletion.id).where(
                MemoryNoteDeletion.note_id == identity)):
            result.append({"note_id": item["note_id"], "deleted": True, "zone": item["zone"]})
            continue
        latest = _latest(session, identity)
        if latest is None:
            continue
        result.append({"note_id": item["note_id"], "revision": item["revision"],
                       "zone": item["zone"], "kind": latest.kind,
                       "kind_label": KIND_LABELS[latest.kind], "text": latest.text,
                       "changed_since": latest.revision != item["revision"]})
    return result


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

    # P121 第 8 项: the owner deletes their own Session. GET is the confirmation
    # preview (what goes now, what stays); POST deletes.
    from . import session_deletion

    @result.get("/v1/personal/agent-sessions/{session_id}/deletion")
    @result.get("/v1/categories/{category_id}/agent-sessions/{session_id}/deletion")
    def previewing_deletion(session_id: UUID, ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            _human(session, ctx, None)
            _target(session, ctx, session_id, None)
            return session_deletion.preview(session, ctx, session_id)

    @result.post("/v1/personal/agent-sessions/{session_id}/deletion")
    @result.post("/v1/categories/{category_id}/agent-sessions/{session_id}/deletion")
    def deleting_session(session_id: UUID, data: session_deletion.DeleteSession,
                         ctx=context_dependency):
        with transaction(ctx) as session:
            _human(session, ctx, None)
            return session_deletion.delete(
                session, ctx, session_id, data,
                target=lambda identity: _target(session, ctx, identity, None, lock=True))

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

    @result.get("/v1/personal/memory-policy/statistics")
    def reading_statistics(ctx=context_dependency):
        # The administrator check takes a share lock, so this is not a read-only snapshot.
        with transaction(ctx) as session:
            _human(session, ctx, None)
            return policy.statistics(session, ctx)

    # M2a 本人记忆条目 (P86): the human owner only; AI identities are refused here
    # and by the database policies.
    from . import candidates, notes, scope_options, settings

    @result.get("/v1/personal/memory/notes")
    def reading_notes(ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            _human(session, ctx, None)
            return notes.listing(session, ctx)

    @result.get("/v1/personal/memory/scope-options")
    def reading_scope_options(data: Annotated[scope_options.ScopeOptions, Query()],
                              ctx=context_dependency):
        # D301: products and proposals the owner can pick as a note's scope.
        with transaction(ctx, read_snapshot=True) as session:
            _human(session, ctx, None)
            return scope_options.options(session, data)

    @result.get("/v1/personal/memory/notes/{note_id}/history")
    def reading_history(note_id: UUID, ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            _human(session, ctx, None)
            return notes.history(session, ctx, note_id)

    @result.post("/v1/personal/memory/notes/conflicts")
    def checking_conflicts(data: notes.NoteDraft, ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            _human(session, ctx, None)
            return notes.conflicts(session, ctx, data)

    @result.post("/v1/personal/memory/notes")
    def creating_note(data: notes.CreateNote, ctx=context_dependency):
        with transaction(ctx) as session:
            _human(session, ctx, None)
            return notes.create(session, ctx, data)

    @result.post("/v1/personal/memory/notes/{note_id}/revisions")
    def revising_note(note_id: UUID, data: notes.ReviseNote, ctx=context_dependency):
        with transaction(ctx) as session:
            _human(session, ctx, None)
            return notes.revise(session, ctx, note_id, data)

    @result.post("/v1/personal/memory/notes/{note_id}/deletion")
    def deleting_note(note_id: UUID, data: notes.DeleteNote, ctx=context_dependency):
        with transaction(ctx) as session:
            _human(session, ctx, None)
            return notes.purge(session, ctx, note_id, data)

    @result.get("/v1/personal/memory/candidates")
    def reading_candidates(ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            _human(session, ctx, None)
            return candidates.pending(session, ctx)

    @result.post("/v1/personal/memory/candidates/{candidate_id}/decision")
    def deciding_candidate(candidate_id: UUID, data: candidates.Decision,
                           ctx=context_dependency):
        with transaction(ctx) as session:
            _human(session, ctx, None)
            return candidates.decide(session, ctx, candidate_id, data)

    @result.get("/v1/personal/agent-runs/{run_id}/memory-candidates")
    @result.get("/v1/categories/{category_id}/agent-runs/{run_id}/memory-candidates")
    def reading_run_candidates(run_id: UUID, ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            _human(session, ctx, None)
            return candidates.for_run(session, ctx, session.get(AgentRun, run_id))

    @result.get("/v1/personal/memory/settings")
    def reading_settings(ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            _human(session, ctx, None)
            return settings.view(settings.latest(session, ctx.requester_id), session)

    @result.post("/v1/personal/memory/settings")
    def changing_settings(data: settings.SettingInput, ctx=context_dependency):
        with transaction(ctx) as session:
            _human(session, ctx, None)
            return settings.change(session, ctx, data)

    @result.post("/v1/personal/memory-policy")
    def changing_policy(data: policy.PolicyInput, ctx=context_dependency):
        with transaction(ctx) as session:
            _human(session, ctx, None)
            return policy.change(session, ctx, data)

    return result
