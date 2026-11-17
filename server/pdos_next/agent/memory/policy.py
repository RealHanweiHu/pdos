"""Tenant memory policy (P85 第 6 项, P86 第 9 项, P87 第 4 项).

The work-state idle limit (30 days by default), the administrator's switches
for free-text notes and 小Pai's memory proposals, and the scope-note review
period (90 days by default; D504). Episode vectorization is
switched by the tenant embedding profile's "本人会话记录" category (P85 第 3 项).
An administrator sees switch states and counts only, never a note's content.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import Field
from sqlalchemy import select, text

from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import digest
from pdos_next.errors import DomainError

from .models import MemoryTenantPolicy

DEFAULT_IDLE_DAYS = 30
DEFAULT_REVIEW_DAYS = 90  # P87 第 4 项 复核期限由租户配置，缺省 90 天
OWNER_SESSION = "owner_session"  # 数据类别“本人会话记录” (P85 第 3 项)


class PolicyInput(StrictModel):
    expected_revision: int = Field(ge=0, strict=True)
    request_key: UUID
    work_state_idle_days: int = Field(ge=1, le=365, strict=True)
    notes_enabled: bool | None = None
    proposals_enabled: bool | None = None
    scope_note_review_days: int | None = Field(default=None, ge=1, le=365, strict=True)


def current(session):
    return session.scalar(
        select(MemoryTenantPolicy).order_by(MemoryTenantPolicy.revision.desc()).limit(1)
    )


def idle_days(session):
    row = current(session)
    return row.work_state_idle_days if row else DEFAULT_IDLE_DAYS


def review_days(session):
    """The scope-note review period in force now (D504)."""
    row = current(session)
    return row.scope_note_review_days if row else DEFAULT_REVIEW_DAYS


def notes_enabled(row):
    return True if row is None else bool(row.notes_enabled)


def proposals_enabled(row):
    return True if row is None else bool(row.proposals_enabled)


def require_notes(session):
    if not notes_enabled(current(session)):
        raise DomainError(
            "FORBIDDEN_SCOPE", "管理员已在本租户关闭自由文本记忆；已有条目仍可查看和删除。", 403,
            detail={"reason_key": "memory_notes_disabled"},
        )


def idle(session, last_activity, *, now=None):
    """Whole idle days since the latest work-state version, and whether it is stale."""
    now = now or datetime.now(UTC)
    limit = idle_days(session)
    days = max(int((now - last_activity) / timedelta(days=1)), 0)
    return days, days >= limit, limit


def view(row):
    return {
        "version": "memory-tenant-policy/v1",
        "revision": row.revision if row else 0,
        "work_state_idle_days": row.work_state_idle_days if row else DEFAULT_IDLE_DAYS,
        "notes_enabled": notes_enabled(row),
        "proposals_enabled": proposals_enabled(row),
        "scope_note_review_days": row.scope_note_review_days if row else DEFAULT_REVIEW_DAYS,
        "default": row is None,
    }


def episode_vectors(session):
    """Whether the active embedding profile selects "本人会话记录" (no content read)."""
    from sqlalchemy import and_

    from pdos_next.agent.enterprise_search.embedding_models import (
        EmbeddingProfile,
        EmbeddingProfileHead,
    )

    rows = session.scalars(
        select(EmbeddingProfile).join(EmbeddingProfileHead, and_(
            EmbeddingProfileHead.tenant_id == EmbeddingProfile.tenant_id,
            EmbeddingProfileHead.profile_id == EmbeddingProfile.profile_id,
            EmbeddingProfileHead.revision == EmbeddingProfile.revision,
            EmbeddingProfileHead.enabled, EmbeddingProfile.enabled,
        ))
    ).all()
    for row in rows:
        if OWNER_SESSION in (row.metadata_json or {}).get("data_categories", []):
            return {"enabled": True, "profile_version_id": str(row.id)}
    return {"enabled": False, "profile_version_id": None}


def statistics(session, ctx):
    """Administrator view: switch states and counts only (P86 第 9 项)."""
    from pdos_next.agent.kernel.mcp_management import administrator

    administrator(session, ctx)
    counts = session.execute(text("SELECT * FROM public.memory_note_statistics(:t)"),
                             {"t": ctx.tenant_id}).mappings().one()
    return {
        "version": "memory-tenant-statistics/v1",
        "policy": view(current(session)),
        "active_notes": counts["active_notes"],
        "owners_with_notes": counts["owners"],
        "episode_vectors": episode_vectors(session),
        "note": "只显示启用状态和条目数量；管理员看不到任何条目内容。",
    }


def change(session, ctx, data):
    from pdos_next.agent.kernel.mcp_management import administrator

    administrator(session, ctx)
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                    {"key": f"memory-policy:{ctx.tenant_id}"})
    latest = current(session)
    notes = notes_enabled(latest) if data.notes_enabled is None else data.notes_enabled
    proposals = (proposals_enabled(latest) if data.proposals_enabled is None
                 else data.proposals_enabled)
    review = (latest.scope_note_review_days if latest else DEFAULT_REVIEW_DAYS) if (
        data.scope_note_review_days is None) else data.scope_note_review_days
    # An M1-shaped request (idle days only) keeps its original fingerprint, and an
    # M2a-shaped one (with the two switches) keeps its own.
    shape = {"work_state_idle_days": data.work_state_idle_days}
    if data.notes_enabled is not None or data.proposals_enabled is not None:
        shape.update(notes_enabled=data.notes_enabled, proposals_enabled=data.proposals_enabled)
    if data.scope_note_review_days is not None:
        shape.update(scope_note_review_days=data.scope_note_review_days)
    fingerprint = digest(shape)
    replay = session.scalar(
        select(MemoryTenantPolicy).where(MemoryTenantPolicy.request_key == data.request_key)
    )
    if replay is not None:
        if replay.request_sha256 != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号对应不同的记忆策略。")
        return view(replay)
    if (latest.revision if latest else 0) != data.expected_revision:
        raise DomainError("VERSION_CONFLICT", "记忆策略已变化，请刷新后再改。")
    row = MemoryTenantPolicy(
        tenant_id=ctx.tenant_id, revision=data.expected_revision + 1,
        work_state_idle_days=data.work_state_idle_days, notes_enabled=notes,
        proposals_enabled=proposals, scope_note_review_days=review, set_by=ctx.actor_id,
        request_key=data.request_key, request_sha256=fingerprint,
    )
    session.add(row)
    session.flush()
    return view(row)
