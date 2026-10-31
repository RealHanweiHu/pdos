"""COMMON T1 owner: saving is metadata-only; no embedding call occurs here."""

from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from pdos_next.clock import now
from pdos_next.errors import DomainError
from pdos_next.model_configuration.commands import CurrentAdministrator
from pdos_next.model_configuration.ports import ManagementContext, SecretBinding
from pdos_next.model_configuration.service import secret_digest
from pdos_next.request_proof import command_inputs_once
from pdos_next.service import digest

from .embedding_identity import canonical_provider
from .embedding_models import (
    EmbeddingBudget,
    EmbeddingProfile,
    EmbeddingProfileHead,
)
from .embedding_schemas import (
    EmbeddingMetadata,
    ReconcileEmbeddingCall,
    SaveEmbeddingProfile,
)

PAYLOADS = {
    "embedding.profile.save": SaveEmbeddingProfile,
    "embedding.call.reconcile": ReconcileEmbeddingCall,
}


def admin(session, ctx):
    if not CurrentAdministrator(session, ctx).is_current_human_admin(
        ManagementContext(ctx.tenant_id, ctx.actor_id),
    ):
        raise DomainError("FORBIDDEN_SCOPE", "Embedding 配置仅由当前本人租户管理员确认。", 403)


def active(session, tenant_id, version_id, *, lock=False):
    profile = session.get(EmbeddingProfile, version_id)
    if not profile or profile.tenant_id != tenant_id:
        raise DomainError("SOURCE_UNAVAILABLE", "Embedding profile 不可用。")
    query = (
        select(EmbeddingProfileHead)
        .where(
            EmbeddingProfileHead.tenant_id == tenant_id,
            EmbeddingProfileHead.profile_id == profile.profile_id,
        )
        .execution_options(populate_existing=True)
    )
    head = session.scalar(query.with_for_update() if lock else query)
    if not head or not head.enabled or not profile.enabled or head.revision != profile.revision:
        raise DomainError("SOURCE_UNAVAILABLE", "Embedding profile 已停用或换版。")
    return profile, EmbeddingMetadata.model_validate(profile.metadata_json)


def bound_secret(port, tenant_id, metadata, *, required):
    try:
        value = port.current_embedding(tenant_id, metadata) if port is not None else None
    except Exception:  # noqa: BLE001 -- provider/KMS errors must be redacted
        if not required:
            return None  # Stopping indexing must not depend on an available key service.
        raise DomainError("SOURCE_UNAVAILABLE", "独立 Embedding 凭据接口暂不可用。") from None
    if value is not None and (
        not isinstance(value, SecretBinding)
        or value.tenant_id != tenant_id
        or value.protocol != "openai-compatible"
    ):
        raise DomainError("FORBIDDEN_SCOPE", "Embedding 独立凭据不匹配。")
    if required and (value is None or not value.available):
        raise DomainError("SOURCE_UNAVAILABLE", "尚未配置独立的 Embedding 凭据。")
    return value


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


@command_inputs_once
def prepared(session, ctx, command, scope, payload):
    admin(session, ctx)
    if command.product_id is not None or command.source_read_set:
        raise DomainError("FORBIDDEN_SCOPE", "Embedding 管理仅接受租户元数据。")
    if command.expected_revision != scope.revision:
        raise DomainError("VERSION_CONFLICT", "当前品类范围已变化。")
    if isinstance(payload, ReconcileEmbeddingCall):
        from .embedding_runtime import reconciliation_plan

        return reconciliation_plan(session, ctx, payload)
    # Locks are tenant-wide and allocated with native ON CONFLICT, not process locks.
    session.execute(
        insert(EmbeddingBudget).values(tenant_id=ctx.tenant_id).on_conflict_do_nothing()
    )
    budget = session.scalar(
        select(EmbeddingBudget)
        .where(
            EmbeddingBudget.tenant_id == ctx.tenant_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    session.execute(
        insert(EmbeddingProfileHead)
        .values(
            tenant_id=ctx.tenant_id,
            profile_id=payload.profile_id,
            revision=0,
            enabled=False,
        )
        .on_conflict_do_nothing()
    )
    head = session.scalar(
        select(EmbeddingProfileHead)
        .where(
            EmbeddingProfileHead.tenant_id == ctx.tenant_id,
            EmbeddingProfileHead.profile_id == payload.profile_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        head.revision != payload.expected_revision
        or budget.revision != payload.expected_budget_revision
    ):
        raise DomainError("VERSION_CONFLICT", "Profile 或租户索引预算已变化。")
    if payload.index_budget_micro_usd < budget.spent_micro_usd + budget.held_micro_usd:
        raise DomainError("VALIDATION_FAILED", "索引预算不能低于已发生及保守占账费用。")
    secret = bound_secret(
        session.info.get("embedding_secrets"),
        ctx.tenant_id,
        payload.metadata,
        required=payload.enabled,
    )
    provider = canonical_provider(
        session.info.get("embedding_secrets"), ctx.tenant_id, payload.metadata,
        required=payload.enabled,
    )
    from .embedding_runtime import wire_bytes
    from .embedding_sources import categories, readable_chunks
    from .schemas import SearchInput

    pricing = session.info.get("embedding_pricing")
    try:
        card = pricing(ctx.tenant_id, payload.metadata) if pricing else None
        if card is not None:
            card.validate(
                provider,
                SimpleNamespace(
                    model=payload.metadata.model,
                    version=payload.metadata.model_version,
                ),
            )
    except Exception:  # noqa: BLE001 -- stopping does not depend on pricing availability
        if payload.enabled:
            raise DomainError("SOURCE_UNAVAILABLE", "独立 Embedding 计量暂不可用。") from None
        card = None
    if payload.enabled and card is None:
        raise DomainError("SOURCE_UNAVAILABLE", "启用前须配置并核对独立 Embedding 计量。")
    rows = (
        list(
            session.execute(
                readable_chunks(
                    session, ctx, SearchInput(query="embedding enable estimate"), include_text=True
                ).limit(5001)
            ).mappings()
        )
        if payload.enabled
        else []
    )
    covered = [
        row for row in rows[:5000] if categories(row) <= set(payload.metadata.data_categories)
    ]
    estimate = (
        len({(row["source_type"], row["source_id"]) for row in covered})
        if payload.enabled
        else None
    )
    # Conservatively price each chunk as its own request; an actual packed batch
    # is bounded/charged independently, never against this preview estimate.
    amount = (
        sum(
            card.reserve(card.input_upper_bound(wire_bytes(payload.metadata, (row["text"],))), 0)
            for row in covered
        )
        if card is not None and payload.enabled
        else None
    )
    return {
        "provider": provider,
        "head": head,
        "budget": budget,
        "secret": secret,
        "expected_sources": estimate,
        "estimate_scope": "current_requester_readable",
        "estimated_cost_micro_usd": amount,
        "estimate_truncated": len(rows) > 5000,
        "pricing_digest": card.snapshot()["digest"] if card else None,
    }


def validate(session, ctx, command, scope, payload):
    prepared(session, ctx, command, scope, payload)


def preview_view(session, ctx, command, scope, payload):
    plan = prepared(session, ctx, command, scope, payload)
    if isinstance(payload, ReconcileEmbeddingCall):
        return plan["public"]
    # No source text or credential IDs enter the COMMON preview or receipt.
    return {
        "provider": plan["provider"],
        "profile_id": str(payload.profile_id),
        "next_revision": payload.expected_revision + 1,
        "next_budget_revision": payload.expected_budget_revision + 1,
        "metadata": payload.metadata.model_dump(mode="json"),
        "enabled": payload.enabled,
        "expected_sources": plan["expected_sources"],
        "estimate_scope": plan["estimate_scope"],
        "estimated_cost_micro_usd": plan["estimated_cost_micro_usd"],
        "estimate_truncated": plan["estimate_truncated"],
        "pricing_digest": plan["pricing_digest"],
        "index_budget_micro_usd": payload.index_budget_micro_usd,
        "credential_status": "bound" if plan["secret"] and plan["secret"].available else "missing",
        "binding_digest": digest(
            [semantic(payload), secret_digest(plan["secret"]), plan["provider"]]
        ),
        "effect": "保存不发起出站；确认启用后由固定批次进行，默认检索仍为关键词。",
    }


def apply(session, ctx, command, scope, payload):
    plan = prepared(session, ctx, command, scope, payload)
    if isinstance(payload, ReconcileEmbeddingCall):
        from .embedding_runtime import reconcile

        row = reconcile(plan, payload)
        return row, "embedding_call", "private"
    secret = plan["secret"]
    value = semantic(payload)
    row = EmbeddingProfile(
        id=uuid5(NAMESPACE_URL, f"embedding-profile:{ctx.tenant_id}:{command.command_id}"),
        tenant_id=ctx.tenant_id,
        profile_id=payload.profile_id,
        revision=payload.expected_revision + 1,
        budget_revision=payload.expected_budget_revision + 1,
        metadata_json=payload.metadata.model_dump(mode="json"),
        enabled=payload.enabled,
        binding_digest=digest([value, secret_digest(secret), plan["provider"]]),
        secret_json={
            "tenant_id": str(secret.tenant_id),
            "reference": str(secret.reference),
            "version": str(secret.version),
            "protocol": secret.protocol,
            "available": secret.available,
        }
        if secret
        else None,
        created_by=ctx.requester_id,
        created_at=now(),
    )
    session.add(row)
    plan["head"].revision, plan["head"].enabled = row.revision, row.enabled
    plan["budget"].revision += 1
    plan["budget"].limit_micro_usd = payload.index_budget_micro_usd
    # The deferred confirmed-profile atom retires this logical profile's vectors
    # across categories without granting this UOW broader source-read permission.
    row.action_result = {
        "profile_id": str(row.profile_id),
        "profile_version_id": str(row.id),
        "enabled": row.enabled,
        "default_retrieval": "keyword",
    }
    return row, "embedding_profile", "private"
