"""The owner deletes one of their own Sessions (P121 第 8 项; M1 缺口 ②).

Gone at once: the Session's episodes, pin/hide/correction marks, keyword index
rows, episode vectors, and proposals from it the owner never adopted. The
Session leaves the owner's list and search, memory.search, the recent catalog
and cross-session conversation.history, and cannot be continued.

Kept: Run records, action receipts and audit (I17, P83 D193). How long Run
records keep the owner's words and the answers is a retention rule that the
pilot agreement has not set yet (D217), so the confirmation and the result say
that plainly instead of promising it.

The rows are removed only by the database function ``memory_delete_session``,
which itself checks "the human owner, acting for themself, own Session". This
module adds the readable errors, the preview and the notice.
"""

from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import digest
from pdos_next.errors import DomainError

from .models import (
    MemoryCandidate,
    MemoryCandidateDecision,
    MemoryEpisode,
    MemoryEpisodeMark,
    MemoryEpisodeVector,
    MemoryIndexEntry,
    MemorySessionDeletion,
)

VERSION = "agent-session-deletion/v1"
ACTIVE = ("queued", "running", "waiting_input")
COUNTS = ("episodes", "marks", "index_rows", "vectors", "candidates")
NOTICE = {
    # P94 的告知方式: say plainly what is gone now, what expires later, what stays.
    "now": "立即清除：这个会话的情景记录，置顶、隐藏和纠正标记，检索索引和向量，以及由它产生、"
           "你没有采纳的记忆提议。它不再出现在会话列表、搜索和小Pai 的回忆里，也不能再继续。",
    "by_retention": "按保留期清除：以往运行的检查点和执行历史里可能仍留有当时的副本，"
                    "最迟 30 天内清除。",
    "kept": "仍然保留：运行记录（含你的原话和小Pai 的回答）、操作回执和审计，不随会话删除；"
            "保留多久由试点协议规定，目前还没有定。你已采纳进“我的记忆”的条目不受影响，"
            "可以在“我的记忆”里单独删除。其他会话调取过这个会话时带入的内容，"
            "留在那些会话的运行记录里。",
}


class DeleteSession(StrictModel):
    request_key: UUID


def deleted_ids(session, session_ids):
    """Which of these Sessions the requester has deleted."""
    ids = {UUID(str(value)) for value in session_ids}
    if not ids:
        return set()
    return set(session.scalars(select(MemorySessionDeletion.session_id).where(
        MemorySessionDeletion.session_id.in_(ids))).all())


def not_deleted(session_id_column, tenant_id_column):
    """SQL condition for Session lists: no deletion record."""
    return ~select(MemorySessionDeletion.id).where(
        MemorySessionDeletion.tenant_id == tenant_id_column,
        MemorySessionDeletion.session_id == session_id_column,
    ).exists()


def require_present(session, session_id):
    if deleted_ids(session, [session_id]):
        raise DomainError("NOT_FOUND", "会话不存在或已删除。", 404)


def require_startable(session, ctx, run, *, origin_run_ids=()):
    """A Run cannot continue, or restart from, a deleted Session.

    Takes the deletion lock in shared mode, so a deletion in progress finishes
    first and a deletion that starts now waits for this Run to be committed.
    """
    from pdos_next.agent.kernel.models import AgentRun

    sessions = {run.session_id}
    origins = [value for value in origin_run_ids if value is not None]
    if origins:
        sessions.update(session.scalars(select(AgentRun.session_id).where(
            AgentRun.id.in_(origins))).all())
    for identity in sorted(sessions, key=str):
        session.execute(
            text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:key,0))"),
            {"key": f"memory-session-delete:{ctx.tenant_id}:{identity}"},
        )
    if deleted_ids(session, sessions):
        raise DomainError("NOT_FOUND", "这个会话已删除，不能继续。请新建对话。", 404)


def _counts(session, session_id):
    def count(model, *conditions):
        return session.scalar(select(func.count()).select_from(model).where(
            model.session_id == session_id, *conditions)) or 0

    adopted = select(MemoryCandidateDecision.id).where(
        MemoryCandidateDecision.candidate_id == MemoryCandidate.id,
        MemoryCandidateDecision.decision == "adopted").exists()
    return {
        "episodes": count(MemoryEpisode), "marks": count(MemoryEpisodeMark),
        "index_rows": count(MemoryIndexEntry), "vectors": count(MemoryEpisodeVector),
        "candidates": count(MemoryCandidate, ~adopted),
    }


def _kept(session, session_id):
    """What stays after deletion, as counts (P83 D193: 删除前做引用分析并预览)."""
    from pdos_next.agent.kernel.models import AgentRun
    from pdos_next.core.models import Receipt

    runs = select(AgentRun.id).where(AgentRun.session_id == session_id)
    adopted = session.scalar(
        select(func.count()).select_from(MemoryCandidateDecision)
        .join(MemoryCandidate, MemoryCandidate.id == MemoryCandidateDecision.candidate_id)
        .where(MemoryCandidate.session_id == session_id,
               MemoryCandidateDecision.decision == "adopted")) or 0
    return {
        "runs": session.scalar(select(func.count()).select_from(runs.subquery())) or 0,
        "receipts": session.scalar(select(func.count()).select_from(Receipt).where(
            Receipt.agent_run_id.in_(runs))) or 0,
        "adopted_notes": adopted,
    }


def _active(session, session_id):
    from pdos_next.agent.kernel.models import AgentRun

    return session.scalar(select(func.count()).select_from(AgentRun).where(
        AgentRun.session_id == session_id, AgentRun.state.in_(ACTIVE))) or 0


def _blocked(active):
    if not active:
        return None
    return {"reason_key": "session_run_active",
            "message": "这个会话还有进行中的运行，请先停止或等它结束再删除。"}


def preview(session, ctx, session_id):
    """Shown before the owner confirms: what goes now, what stays, what blocks."""
    return {
        "version": VERSION, "session_id": str(session_id), "deleted": False,
        "will_remove": _counts(session, session_id),
        "kept": _kept(session, session_id),
        "blocked": _blocked(_active(session, session_id)),
        "notice": NOTICE,
    }


def deletion_view(row):
    return {
        "version": VERSION, "session_id": str(row.session_id), "deleted": True,
        "deleted_at": row.created_at.isoformat(),
        "removed": {key: getattr(row, f"purged_{key}") for key in COUNTS},
        "notice": NOTICE,
    }


def _replay(session, ctx, session_id, data, fingerprint):
    row = session.scalar(select(MemorySessionDeletion).where(
        MemorySessionDeletion.owner_id == ctx.requester_id,
        MemorySessionDeletion.request_key == data.request_key))
    if row is None:
        return None
    if row.session_id != session_id or row.request_sha256 != fingerprint:
        raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号对应不同的会话操作。")
    return row


def delete(session, ctx, session_id, data, *, target):
    """``target`` loads the owner's own readable Session or raises (kernel ``_target``)."""
    fingerprint = digest({"op": "delete-session", "session_id": session_id})
    replay = _replay(session, ctx, session_id, data, fingerprint)
    if replay is not None:
        return deletion_view(replay)
    target(session_id)
    blocked = _blocked(_active(session, session_id))
    if blocked:
        raise DomainError("VERSION_CONFLICT", blocked["message"],
                          detail={"reason_key": blocked["reason_key"]})
    try:
        with session.begin_nested():
            session.execute(
                text("SELECT id FROM memory_delete_session(:t,:s,:key,:fingerprint)"),
                {"t": ctx.tenant_id, "s": session_id, "key": data.request_key,
                 "fingerprint": fingerprint},
            )
    except DBAPIError as error:
        state = getattr(error.orig, "sqlstate", None)
        if state == "55006":
            message = _blocked(1)
            raise DomainError("VERSION_CONFLICT", message["message"],
                              detail={"reason_key": message["reason_key"]}) from None
        if state == "23505":
            raise DomainError("NOT_FOUND", "会话不存在或已删除。", 404) from None
        if state == "42501":
            raise DomainError("FORBIDDEN_SCOPE", "只有本人可以删除自己的会话。", 403) from None
        raise
    session.expire_all()
    row = session.scalar(select(MemorySessionDeletion).where(
        MemorySessionDeletion.session_id == session_id))
    return deletion_view(row)


def recheck(session, run):
    """Before each model call: stop if a Session this Run drew on was deleted.

    Covers Sessions read through conversation.history and the Sessions of
    episodes that memory.search or the catalog returned. A Run that used no
    memory makes no query here. The Run's own Session needs no check: deletion
    is refused while a Run is in progress, and a start waits for a deletion.
    """
    from pdos_next.agent.kernel.models import AgentRun

    usage = (run.versions or {}).get("memory_usage") or {}
    sessions = {UUID(value) for value in usage.get("sessions", [])}
    episodes = [UUID(value) for value in usage.get("episodes", [])]
    if episodes:
        sessions.update(session.scalars(select(AgentRun.session_id).where(
            AgentRun.id.in_(episodes))).all())
    gone = deleted_ids(session, sessions)
    if gone:
        raise DomainError(
            "CONVERSATION_HISTORY_REVOKED",
            "这次运行调取过的会话已被你删除，已停止。请重新发起。",
            detail={"session_ids": sorted(map(str, gone))},
        )


def read_other_session(store, scope, payload, readers):
    """conversation.history for another Session: never one its owner deleted."""
    from .history import other_session
    from .mode import TURN_MESSAGE, is_turn

    with store.transaction(scope) as (session, run):
        if deleted_ids(session, [payload.session_id]):
            raise DomainError("FORBIDDEN_SCOPE", "该会话已删除，不能调取。", 403)
        turn = is_turn(run)
    value = other_session(store, scope, payload, readers)
    if turn and value.get("status") == "memory_off":
        value = {**value, "message": TURN_MESSAGE}
    return value
