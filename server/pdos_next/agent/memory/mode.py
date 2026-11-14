"""The owner's per-Session "不进记忆" switch (P85 第 5 项).

Off means: no personal memory is read, no episode is recorded, no memory
proposal is made and no episode catalog is injected. Scope memos (M2b), Run
receipts and audit stay as they are. A Run freezes the mode when it is created.

“本轮不记” (P121 第 8 项) is the same effect for one Run: the Run is frozen off
with ``turn`` set and the Session's own switch is left alone.
"""

from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field
from sqlalchemy import select, text

from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import digest
from pdos_next.errors import DomainError

from .models import MemorySessionSetting


class ModeInput(StrictModel):
    expected_revision: int = Field(ge=0, strict=True)
    request_key: UUID
    memory_off: bool


def latest(session, session_id):
    return session.scalar(
        select(MemorySessionSetting)
        .where(MemorySessionSetting.session_id == session_id)
        .order_by(MemorySessionSetting.revision.desc())
        .limit(1)
    )


def view(row, session_id):
    return {
        "version": "memory-session-mode/v1",
        "session_id": str(session_id),
        "revision": row.revision if row else 0,
        "memory_off": bool(row and row.memory_off),
        "effect": "本会话不读个人记忆、不记录情景、不注入以往目录；团队备忘与审计照常。"
        if row and row.memory_off else "本会话照常记录情景，可在以后的会话里查到。",
    }


def is_off(run):
    """The frozen mode of an actual Run; a Run without it was created before M1."""
    return bool((run.versions or {}).get("memory_mode", {}).get("off"))


def _append(session, ctx, session_id, memory_off, *, key, fingerprint, revision):
    row = MemorySessionSetting(
        tenant_id=ctx.tenant_id, owner_id=ctx.requester_id, session_id=session_id,
        revision=revision, memory_off=memory_off, request_key=key, request_sha256=fingerprint,
    )
    session.add(row)
    session.flush()
    return row


def _lock(session, tenant_id, session_id):
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"memory-mode:{tenant_id}:{session_id}"},
    )


def configure_start(session, ctx, run, requested, *, new_session):
    """Bind the switch for a brand-new Session, then freeze the mode on the Run."""
    if requested is not None and not new_session:
        raise DomainError(
            "VALIDATION_FAILED", "已有会话请在会话设置里切换“不进记忆”。", 422,
            detail={"reason": "memory_mode_existing_session"},
        )
    if not requested:
        # No query on the common path. An existing Session's "off" is frozen at
        # the Run's first context assembly (recall.unavailable), and a Run
        # without a frozen mode reads the switch again when it finishes.
        return
    _lock(session, ctx.tenant_id, run.session_id)
    if latest(session, run.session_id) is None:
        key = uuid5(NAMESPACE_URL, f"pdos-memory-mode-start:{run.id}")
        _append(
            session, ctx, run.session_id, True, key=key,
            fingerprint=digest({"memory_off": True, "start_run_id": str(run.id)}), revision=1,
        )
    run.versions = {**run.versions, "memory_mode": {"off": True}}


def configure_turn(run, requested):
    """“本轮不记” (P121 第 8 项): this Run only, same effect as the Session switch.

    Nothing is written to the Session's setting, so the next turn follows the
    Session again. A Run already frozen off by the Session switch stays as it is.
    """
    if requested and not is_off(run):
        run.versions = {**run.versions, "memory_mode": {"off": True, "turn": True}}


def is_turn(run):
    """Off for this Run only, by the owner's “本轮不记”."""
    return bool((run.versions or {}).get("memory_mode", {}).get("turn"))


TURN_MESSAGE = "本轮已设为不记，未读取个人记忆，也不会留下这一轮的情景记录。"


def turn_notice(run, value):
    """Say "本轮" instead of "本会话" in a memory_off tool result of such a Run."""
    if is_turn(run) and isinstance(value, dict) and value.get("status") == "memory_off":
        return {**value, "message": TURN_MESSAGE}
    return value


def run_is_off(session, run):
    """Frozen off, or switched off since the Run started (the stricter of the two)."""
    if is_off(run):
        return True
    current = latest(session, run.session_id)
    return bool(current and current.memory_off)


def change(session, ctx, session_id, data):
    _lock(session, ctx.tenant_id, session_id)
    fingerprint = digest({"memory_off": data.memory_off})
    replay = session.scalar(
        select(MemorySessionSetting).where(
            MemorySessionSetting.owner_id == ctx.requester_id,
            MemorySessionSetting.request_key == data.request_key,
        )
    )
    if replay is not None:
        if replay.request_sha256 != fingerprint or replay.session_id != session_id:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号对应不同的记忆设置。")
        return view(replay, session_id)
    current = latest(session, session_id)
    if (current.revision if current else 0) != data.expected_revision:
        raise DomainError("VERSION_CONFLICT", "记忆设置已变化，请刷新后再改。")
    row = _append(
        session, ctx, session_id, data.memory_off, key=data.request_key,
        fingerprint=fingerprint, revision=data.expected_revision + 1,
    )
    return view(row, session_id)
