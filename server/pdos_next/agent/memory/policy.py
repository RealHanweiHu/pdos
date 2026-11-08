"""Tenant memory policy: the work-state idle limit (P85 第 6 项, 30 days by default)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import Field
from sqlalchemy import select, text

from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import digest
from pdos_next.errors import DomainError

from .models import MemoryTenantPolicy

DEFAULT_IDLE_DAYS = 30


class PolicyInput(StrictModel):
    expected_revision: int = Field(ge=0, strict=True)
    request_key: UUID
    work_state_idle_days: int = Field(ge=1, le=365, strict=True)


def current(session):
    return session.scalar(
        select(MemoryTenantPolicy).order_by(MemoryTenantPolicy.revision.desc()).limit(1)
    )


def idle_days(session):
    row = current(session)
    return row.work_state_idle_days if row else DEFAULT_IDLE_DAYS


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
        "default": row is None,
    }


def change(session, ctx, data):
    from pdos_next.agent.kernel.mcp_management import administrator

    administrator(session, ctx)
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                    {"key": f"memory-policy:{ctx.tenant_id}"})
    fingerprint = digest({"work_state_idle_days": data.work_state_idle_days})
    replay = session.scalar(
        select(MemoryTenantPolicy).where(MemoryTenantPolicy.request_key == data.request_key)
    )
    if replay is not None:
        if replay.request_sha256 != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号对应不同的记忆策略。")
        return view(replay)
    latest = current(session)
    if (latest.revision if latest else 0) != data.expected_revision:
        raise DomainError("VERSION_CONFLICT", "记忆策略已变化，请刷新后再改。")
    row = MemoryTenantPolicy(
        tenant_id=ctx.tenant_id, revision=data.expected_revision + 1,
        work_state_idle_days=data.work_state_idle_days, set_by=ctx.actor_id,
        request_key=data.request_key, request_sha256=fingerprint,
    )
    session.add(row)
    session.flush()
    return view(row)
