"""Trusted host import transaction; never registered as a public command or AI tool."""

from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import select

from pdos_next.contracts import Command
from pdos_next.errors import DomainError
from pdos_next.models import Product, Receipt, RequestKey, TestResourceFact
from pdos_next.service import append_receipt, digest, receipt_view, remember_key, require_access


def import_test_resource_fact(
    s, ctx, product_id, issuer, payload, *, request_key: str, command_id: UUID
):
    from pdos_next.domain.test_resources.schemas import TestResourceFactInput as FactInput
    from pdos_next.domain.test_resources.service import trusted_import

    data = FactInput.model_validate(payload)
    if ctx.actor_id != ctx.requester_id or ctx.run_id is not None:
        raise DomainError(
            "NAMED_DECISION_REQUIRED", "测试资源签发导入必须由可信具名入口办理。", 403
        )
    product = require_access(s, ctx, product_id)
    command = Command(
        category_id=product.category_id,
        command_id=command_id,
        idempotency_key=request_key,
        operation="test.resources.import",
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
    old = (
        s.get(Receipt, key.receipt_id)
        if key
        else s.scalar(
            select(Receipt).where(
                Receipt.tenant_id == ctx.tenant_id,
                Receipt.product_id == product.id,
                Receipt.actor_id == ctx.actor_id,
                Receipt.operation == command.operation,
                Receipt.intent_digest == fingerprint,
            )
        )
    )
    if old is not None:
        remember_key(s, ctx, request_key, fingerprint, old)
        return receipt_view(old)
    if key:
        raise DomainError("FORBIDDEN_SCOPE", "原导入回执不在当前可读范围。", 403)
    product = s.scalar(select(Product).where(Product.id == product.id).with_for_update())
    require_access(s, ctx, product.id, write=True, lock=True)
    imported = trusted_import(s, ctx, product_id, issuer, data)
    fact = s.get(TestResourceFact, UUID(imported["id"]))
    if fact is None:
        raise DomainError("INTEGRITY_MISMATCH", "导入结果无法绑定持久测试资源事实。")
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
                "series_id": str(fact.series_id),
            },
        )
        old = append_receipt(
            s,
            ctx,
            command,
            "test_resource_fact",
            subject,
            fingerprint,
            fingerprint,
            fact.visibility,
        )
    remember_key(s, ctx, request_key, fingerprint, old)
    return receipt_view(old)
