"""The owner's own memory setting: turn off 小Pai's proactive proposals (P86 第 3 项)."""

from uuid import UUID

from pydantic import Field
from sqlalchemy import select, text

from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import digest
from pdos_next.errors import DomainError

from .models import MemoryOwnerSetting


class SettingInput(StrictModel):
    expected_revision: int = Field(ge=0, strict=True)
    request_key: UUID
    proactive_off: bool


def latest(session, owner_id):
    return session.scalar(select(MemoryOwnerSetting).where(MemoryOwnerSetting.owner_id == owner_id)
                          .order_by(MemoryOwnerSetting.revision.desc()).limit(1))


def proactive_off(session, owner_id):
    row = latest(session, owner_id)
    return bool(row and row.proactive_off)


def view(row, session):
    from . import policy

    tenant = policy.current(session)
    return {
        "version": "memory-owner-settings/v1",
        "revision": row.revision if row else 0,
        "proactive_off": bool(row and row.proactive_off),
        "notes_enabled": policy.notes_enabled(tenant),
        "proposals_enabled": policy.proposals_enabled(tenant),
        "episode_vectors": policy.episode_vectors(session)["enabled"],
        "effect": "你说“记住……”时小Pai 仍会提议；只关闭它在你多次纠正后的主动提议。"
        if row and row.proactive_off
        else "同一会话里你对同一件事纠正两次以上时，小Pai 最多提议一次。",
    }


def change(session, ctx, data):
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                    {"key": f"memory-owner-settings:{ctx.tenant_id}:{ctx.requester_id}"})
    fingerprint = digest({"proactive_off": data.proactive_off})
    replay = session.scalar(select(MemoryOwnerSetting).where(
        MemoryOwnerSetting.owner_id == ctx.requester_id,
        MemoryOwnerSetting.request_key == data.request_key))
    if replay is not None:
        if replay.request_sha256 != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号对应不同的记忆设置。")
        return view(replay, session)
    current = latest(session, ctx.requester_id)
    if (current.revision if current else 0) != data.expected_revision:
        raise DomainError("VERSION_CONFLICT", "记忆设置已变化，请刷新后再改。")
    row = MemoryOwnerSetting(
        tenant_id=ctx.tenant_id, owner_id=ctx.requester_id, revision=data.expected_revision + 1,
        proactive_off=data.proactive_off, request_key=data.request_key,
        request_sha256=fingerprint,
    )
    session.add(row)
    session.flush()
    return view(row, session)
