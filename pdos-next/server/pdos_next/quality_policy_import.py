"""Host-only policy publication receipt; never a public command or AI tool."""

from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import select

from pdos_next.contracts import Command
from pdos_next.domain.quality_execution.policy import _issuer, trusted_import
from pdos_next.domain.quality_execution.schemas import PolicyInput
from pdos_next.errors import DomainError
from pdos_next.models import Principal, Product, Receipt, RequestKey
from pdos_next.service import append_receipt, digest, receipt_view, require_access


def import_quality_policy_fact(s, ctx, issuer, payload, *, request_key: str, command_id: UUID):
    data = PolicyInput.model_validate(payload)
    actor = s.get(Principal, ctx.requester_id)
    if (
        ctx.actor_id != ctx.requester_id
        or ctx.run_id is not None
        or actor is None
        or actor.tenant_id != ctx.tenant_id
        or actor.kind != "human"
        or not actor.active
    ):
        raise DomainError("NAMED_PERSON_REQUIRED", "政策导入必须经可信具名宿主办理。", 403)
    require_access(s, ctx, data.product_id, write=True, lock=True)
    product = s.scalar(
        select(Product)
        .where(Product.tenant_id == ctx.tenant_id, Product.id == data.product_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if product is None:
        raise DomainError("FORBIDDEN_SCOPE", "政策产品不在当前宿主范围。", 403)
    from pdos_next.request_proof import request_proof

    request_proof(s).scope_locks.add(product.id)
    _issuer(s.get_bind(), issuer, ctx.tenant_id, product.id, data.project_id)
    command = Command(
        command_id=command_id,
        idempotency_key=request_key,
        operation="quality.policy.import",
        category_id=product.category_id,
        product_id=product.id,
        expected_revision=product.revision,
        payload=data.model_dump(mode="json"),
    )
    # The opaque issuer is validated by trusted_import before any existing
    # Receipt may be returned. This fingerprint confers no publishing authority.
    fingerprint = digest(
        {
            "operation": command.operation,
            "tenant": ctx.tenant_id,
            "product": product.id,
            "actor": ctx.requester_id,
            "issuer": [issuer.key, issuer.version, issuer.epoch],
            "payload": data.model_dump(mode="json"),
        }
    )
    key = s.scalar(
        select(RequestKey).where(
            RequestKey.tenant_id == ctx.tenant_id,
            RequestKey.actor_id == ctx.actor_id,
            RequestKey.key == request_key,
        )
    )
    if key and key.digest != fingerprint:
        raise DomainError("DUPLICATE_INTENT_CONFLICT", "同一政策导入编号对应了不同事实。")
    fact = trusted_import(s, ctx, issuer, data)
    old = s.scalar(
        select(Receipt).where(
            Receipt.tenant_id == ctx.tenant_id,
            Receipt.product_id == product.id,
            Receipt.operation == command.operation,
            Receipt.subject_type == "quality_policy_fact",
            Receipt.subject_id == fact.id,
        )
    )
    if key:
        if old is None or key.receipt_id != old.id:
            raise DomainError("INTEGRITY_MISMATCH", "政策导入回执无法核对。")
        return receipt_view(old)
    if old is None:
        old = append_receipt(
            s,
            ctx,
            command,
            "quality_policy_fact",
            SimpleNamespace(
                id=fact.id,
                revision=fact.revision,
                status=fact.status,
                action_result={
                    "nature": fact.nature,
                    "series_id": str(fact.series_id),
                    "project_id": str(fact.project_id),
                },
            ),
            fingerprint,
            fingerprint,
            fact.visibility,
        )
    s.add(
        RequestKey(
            tenant_id=ctx.tenant_id,
            category_id=product.category_id,
            actor_id=ctx.actor_id,
            key=request_key,
            digest=fingerprint,
            receipt_id=old.id,
        )
    )
    s.flush()
    return receipt_view(old)
