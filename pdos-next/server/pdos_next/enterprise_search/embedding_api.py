"""Metadata-only administrator view over the original COMMON T1/indexing ledger."""

from uuid import UUID

from fastapi import Query
from sqlalchemy import and_, func, select

from pdos_next.agent_kernel.models import TenantAdministrator
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import Principal
from pdos_next.service import require_access

from .embedding_models import (
    EmbeddingBatch,
    EmbeddingBudget,
    EmbeddingCall,
    EmbeddingProfile,
    EmbeddingProfileHead,
)


def profile_view(profile, head):
    return {
        "profile_id": str(profile.profile_id),
        "profile_version_id": str(profile.id),
        "revision": profile.revision,
        "budget_revision": profile.budget_revision,
        "metadata": profile.metadata_json,
        "enabled": profile.enabled and head.enabled,
        "credential_status": "bound"
        if profile.secret_json and profile.secret_json.get("available")
        else "missing",
    }


def call_view(call, batch):
    return {
        "call_id": str(call.id),
        "revision": call.revision,
        "batch_id": str(batch.id),
        "profile_version_id": str(batch.profile_version_id),
        "attempt": call.attempt,
        "state": call.state,
        "batch_state": batch.state,
        "last_error": batch.last_error,
        "provider": call.egress.get("provider"),
        "data_categories": call.data_categories,
        "source_count": call.source_count,
        "character_count": call.character_count,
        "reserved_micro_usd": call.reserved_micro_usd,
        "charged_micro_usd": call.charged_micro_usd,
        "input_tokens": call.input_tokens,
        "usage_known": call.input_tokens is not None,
        "created_at": call.created_at.isoformat(),
    }


def reading(session, ctx, *, after=None, page_size=20):
    category = require_access(session, ctx, None)
    # The command guard locks the current administrator for a write UOW. This
    # GET uses an ordinary read-only snapshot and needs the same facts, no locks.
    current = session.scalar(
        select(TenantAdministrator.id)
        .join(
            Principal,
            and_(
                Principal.tenant_id == TenantAdministrator.tenant_id,
                Principal.id == TenantAdministrator.principal_id,
            ),
        )
        .where(
            TenantAdministrator.tenant_id == ctx.tenant_id,
            TenantAdministrator.principal_id == ctx.actor_id,
            TenantAdministrator.active.is_(True),
            Principal.active.is_(True),
            Principal.kind == "human",
        )
    )
    if ctx.actor_id != ctx.requester_id or ctx.run_id or ctx.agent_run_id or current is None:
        raise DomainError("FORBIDDEN_SCOPE", "Embedding 配置仅由当前本人租户管理员读取。", 403)
    budget = session.get(EmbeddingBudget, ctx.tenant_id)
    profiles = session.execute(
        select(EmbeddingProfile, EmbeddingProfileHead)
        .join(
            EmbeddingProfileHead,
            and_(
                EmbeddingProfileHead.tenant_id == EmbeddingProfile.tenant_id,
                EmbeddingProfileHead.profile_id == EmbeddingProfile.profile_id,
                EmbeddingProfileHead.revision == EmbeddingProfile.revision,
            ),
        )
        .where(EmbeddingProfile.tenant_id == ctx.tenant_id)
        .order_by(EmbeddingProfile.profile_id)
        .limit(101)
    ).all()
    states = session.execute(
        select(EmbeddingBatch.state, func.count())
        .where(
            EmbeddingBatch.tenant_id == ctx.tenant_id,
            EmbeddingBatch.category_id == ctx.category_id,
        )
        .group_by(EmbeddingBatch.state)
    ).all()
    query = (
        select(EmbeddingCall, EmbeddingBatch)
        .join(
            EmbeddingBatch,
            and_(
                EmbeddingBatch.id == EmbeddingCall.batch_id,
                EmbeddingBatch.tenant_id == EmbeddingCall.tenant_id,
            ),
        )
        .where(
            EmbeddingCall.tenant_id == ctx.tenant_id, EmbeddingCall.category_id == ctx.category_id
        )
    )
    if after is not None:
        cursor = session.get(EmbeddingCall, after)
        if (
            cursor is None
            or cursor.tenant_id != ctx.tenant_id
            or cursor.category_id != ctx.category_id
        ):
            raise DomainError("SOURCE_UNAVAILABLE", "当前分页游标不可用。")
        query = query.where(EmbeddingCall.id > cursor.id)
    rows = session.execute(query.order_by(EmbeddingCall.id).limit(page_size + 1)).all()
    return {
        "category_revision": category.revision,
        "default_retrieval": "keyword",
        "scope": "current_requester_readable",
        "budget": {
            "revision": budget.revision,
            "limit_micro_usd": budget.limit_micro_usd,
            "held_micro_usd": budget.held_micro_usd,
            "spent_micro_usd": budget.spent_micro_usd,
        }
        if budget
        else None,
        "profiles": [profile_view(profile, head) for profile, head in profiles[:100]],
        "profiles_truncated": len(profiles) > 100,
        "batch_counts": {state: count for state, count in states},
        "calls": [call_view(call, batch) for call, batch in rows[:page_size]],
        "next_cursor": str(rows[page_size - 1][0].id) if len(rows) > page_size else None,
    }


def register_routes(app, engine, auth_dependency):
    @app.get("/v1/categories/{category_id}/embedding-profile")
    def current_embedding_profile(
        after: UUID | None = None,
        page_size: int = Query(default=20, ge=1, le=100),
        ctx=auth_dependency,
    ):
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        ) as session:
            return reading(session, ctx, after=after, page_size=page_size)
