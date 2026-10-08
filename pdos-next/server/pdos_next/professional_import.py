"""Trusted host import transaction; never registered as a public command or AI tool."""

from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import select

from pdos_next.contracts import Command
from pdos_next.errors import DomainError
from pdos_next.models import Product, ProfessionalFact, Receipt, RequestKey
from pdos_next.service import append_receipt, digest, receipt_view, require_access


def import_professional_fact(s, ctx, issuer, payload, *, request_key: str, command_id: UUID):
    from pdos_next.domain.professional_authority.schemas import FactInput
    from pdos_next.domain.professional_authority.service import trusted_import

    data = FactInput.model_validate(payload)
    if ctx.actor_id != ctx.requester_id or ctx.run_id is not None:
        raise DomainError("NAMED_DECISION_REQUIRED", "专业签发导入必须由可信具名入口办理。", 403)
    product = s.scalar(
        select(Product)
        .where(Product.id == data.product_id, Product.tenant_id == ctx.tenant_id)
        .with_for_update()
    )
    if product is None:
        raise DomainError("FORBIDDEN_SCOPE", "专业签发范围不可用。", 403)
    require_access(s, ctx, product.id, write=True, lock=True)
    command = Command(
        command_id=command_id,
        idempotency_key=request_key,
        operation="professional.authority.import",
        product_id=product.id,
        expected_revision=product.revision,
        payload=data.model_dump(mode="json"),
    )
    fingerprint = digest(
        {
            "operation": command.operation,
            "product": product.id,
            "actor": ctx.requester_id,
            "issuer": [issuer.key, issuer.version, issuer.nature],
            "payload": data.model_dump(mode="json"),
        }
    )
    key = s.scalar(
        select(RequestKey).where(RequestKey.actor_id == ctx.actor_id, RequestKey.key == request_key)
    )
    if key and key.digest != fingerprint:
        raise DomainError("DUPLICATE_INTENT_CONFLICT", "同一导入编号对应了不同的签发事实。")
    # Revalidates the opaque issuer, current human scope and source read-set on replay too.
    imported = trusted_import(s, ctx, issuer, data)
    fact = s.get(ProfessionalFact, UUID(imported["id"]))
    if fact is None:
        raise DomainError("INTEGRITY_MISMATCH", "导入结果无法绑定持久专业事实。")
    old = s.scalar(
        select(Receipt).where(
            Receipt.product_id == product.id,
            Receipt.operation == command.operation,
            Receipt.subject_id == fact.id,
        )
    )
    if key:
        if old is None or key.receipt_id != old.id:
            raise DomainError("INTEGRITY_MISMATCH", "签发导入回执无法核对。")
        return receipt_view(old)
    if old is None:
        subject = SimpleNamespace(
            id=fact.id,
            revision=fact.revision,
            status=fact.state,
            action_result={
                "nature": fact.nature,
                "kind": fact.kind,
                "series_id": str(fact.series_id),
            },
        )
        old = append_receipt(
            s,
            ctx,
            command,
            "professional_authority_fact",
            subject,
            fingerprint,
            fingerprint,
            fact.visibility,
        )
    s.add(
        RequestKey(
            tenant_id=ctx.tenant_id,
            actor_id=ctx.actor_id,
            key=request_key,
            digest=fingerprint,
            receipt_id=old.id,
        )
    )
    s.flush()
    return receipt_view(old)
