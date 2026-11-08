"""The owner's per-Session "不进记忆" switch (P85 第 5 项).

Off means: no personal memory is read, no episode is recorded, no memory
proposal is made and no episode catalog is injected. Scope memos (M2b), Run
receipts and audit stay as they are. A Run freezes the mode when it is created.
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
    _lock(session, ctx.tenant_id, run.session_id)
    current = latest(session, run.session_id)
    if requested and current is None:
        key = uuid5(NAMESPACE_URL, f"pdos-memory-mode-start:{run.id}")
        current = _append(
            session, ctx, run.session_id, True, key=key,
            fingerprint=digest({"memory_off": True, "start_run_id": str(run.id)}), revision=1,
        )
    if current is not None and current.memory_off:
        # Only "off" is frozen. A Run without it reads the switch again when it
        # finishes, so turning memory off mid-run also stops its episode.
        run.versions = {**run.versions, "memory_mode": {"off": True}}


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
