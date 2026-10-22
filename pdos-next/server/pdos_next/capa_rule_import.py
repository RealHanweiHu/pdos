"""Host-only rule publication using the existing shared atom and transaction.

No public route/PAYLOADS entry, standalone commit, T2 proof or future Fact SHA.
The calling host must pass this engine's exact configured publisher identity.
"""

# ruff: noqa: I001
from pdos_next.service import append_receipt, digest, receipt_view, require_access

from sqlalchemy import select

from pdos_next.contracts import Command
from pdos_next.domain.capa_effectiveness import fact_commands as commands, fact_service, fact_write
from pdos_next.domain.capa_effectiveness import anchor, fact_atom_storage as guards
from pdos_next.errors import DomainError
from pdos_next.models import Product, Receipt, RequestKey


def publish_rule(s, ctx, command, *, publisher):
    if not isinstance(command, Command) or command.operation != commands.RULE_OPERATION:
        raise DomainError("FACT_RULE_HOST_ONLY", "规则发布须由可信服务器入口办理。", 403)
    runtime = fact_service._runtime(s)
    if publisher is None or runtime.host.owner.publisher is not publisher:
        raise DomainError("FACT_RULE_HOST_ONLY", "缺本运行配置的实际可信规则签发入口。", 403)
    payload = commands.payload_for("rule", command.payload)
    product = s.scalar(
        select(Product)
        .where(Product.id == command.product_id, Product.tenant_id == ctx.tenant_id)
        .with_for_update()
    )
    if product is None:
        raise DomainError("FORBIDDEN_SCOPE", "规则不在当前型号范围。", 403)
    require_access(s, ctx, product.id, write=True, lock=True)
    uow, caller = guards._uow(s), digest(vars(ctx))
    request_digest = digest(
        {
            "operation": command.operation,
            "product_id": command.product_id,
            "expected_revision": command.expected_revision,
            "source_read_set": [v.model_dump(mode="json") for v in command.source_read_set],
            "payload": payload.model_dump(mode="json"),
        }
    )
    intent = digest(
        {
            "operation": command.operation,
            "category": command.category_id,
            "product": product.id,
            "payload": commands.semantic(payload),
            "named_actor": ctx.requester_id,
            "source_revision": None,
            "private_owner": ctx.requester_id if payload.visibility == "private" else None,
        }
    )
    key = s.scalar(
        select(RequestKey).where(
            RequestKey.tenant_id == ctx.tenant_id,
            RequestKey.actor_id == ctx.actor_id,
            RequestKey.key == command.idempotency_key,
        )
    )
    old = s.scalar(
        select(Receipt).where(
            Receipt.tenant_id == ctx.tenant_id,
            Receipt.product_id == product.id,
            Receipt.intent_digest == intent,
        )
    )
    with s.no_autoflush:
        prepared = fact_write.prepare_fact(
            s, ctx, product.id, payload, host=runtime.host, new_write=key is None and old is None
        )
        try:
            if anchor.canonical_reads(command.source_read_set) != anchor.canonical_reads(
                prepared.required_source_read_set
            ):
                raise DomainError("MISSING_REQUIRED_EVIDENCE", "规则发布须核对完整固定来源。", 409)
            if key is not None:
                if key.digest != request_digest:
                    raise DomainError("DUPLICATE_INTENT_CONFLICT", "原发布编号对应不同材料。", 409)
                saved = s.get(Receipt, key.receipt_id)
                if (
                    saved is None
                    or saved.intent_digest != intent
                    or saved.operation != command.operation
                ):
                    raise DomainError("INTEGRITY_MISMATCH", "规则原回执不能精确核对。", 409)
                return receipt_view(saved)
            if old is not None:
                s.add(
                    RequestKey(
                        tenant_id=ctx.tenant_id,
                        actor_id=ctx.actor_id,
                        key=command.idempotency_key,
                        digest=request_digest,
                        receipt_id=old.id,
                    )
                )
                return receipt_view(old)
            row = fact_write.append_prepared_rule(
                s,
                ctx,
                command,
                product,
                payload,
                prepared,
                host=runtime.host,
                module=runtime.module,
                common_intent_digest=intent,
            )
        finally:
            fact_service._discard(runtime, prepared)
    guards._same_uow(s, uow, ctx, caller)
    if fact_service._runtime(s) is not runtime or runtime.host.owner.publisher is not publisher:
        raise DomainError("SOURCE_STALE", "发布期间可信入口已改变。", 409)
    # Immediate Current guards must see their immutable fact first. Both flushes
    # belong to this same transaction; the reciprocal atom guards stay deferred.
    s.flush([row])
    s.flush()
    receipt = append_receipt(
        s, ctx, command, commands.SPECS["rule"][2], row, request_digest, intent, row.visibility
    )
    s.add(
        RequestKey(
            tenant_id=ctx.tenant_id,
            actor_id=ctx.actor_id,
            key=command.idempotency_key,
            digest=request_digest,
            receipt_id=receipt.id,
        )
    )
    s.flush()
    return receipt_view(receipt)
