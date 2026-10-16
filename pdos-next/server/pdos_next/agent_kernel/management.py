"""Named administrator agreement registration shares Receipt/Audit/Outbox transaction."""

from datetime import datetime
from uuid import uuid4

from pydantic import Field
from sqlalchemy import select, text

from pdos_next.clock import now
from pdos_next.database import require_context
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Outbox, Principal, Receipt
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest, receipt_view

from .models import ProviderDataAgreement


class AgreementInput(StrictModel):
    provider: str = Field(min_length=1, max_length=160)
    expected_revision: int = Field(ge=0)
    signed_on: datetime
    data_categories: list[str] = Field(min_length=1)
    retention_terms: str = Field(min_length=3)
    training_terms: str = Field(min_length=3)
    expires_at: datetime
    active: bool = True
    decision: str
    idempotency_key: str = Field(min_length=8, max_length=160)


def agreement_receipt(session, ctx, data):
    """Inspect only this person's exact original request; never register an agreement."""
    require_context(session, ctx)
    existing = session.scalar(
        select(Receipt).where(
            Receipt.tenant_id == ctx.tenant_id,
            Receipt.actor_id == ctx.actor_id,
            Receipt.operation == "provider.agreement.register",
            Receipt.intent_digest
            == digest(["provider.agreement.register", ctx.actor_id, data.idempotency_key]),
        )
    )
    if existing:
        if existing.request_digest != digest(data.model_dump(mode="json")):
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号绑定了不同协议。")
        return receipt_view(existing)
    return None


def register_agreement(session, ctx, data: AgreementInput):
    require_context(session, ctx)
    actor = session.get(Principal, ctx.actor_id)
    admin = session.scalar(text("SELECT kernel_admin_authorized()"))
    if (
        not actor
        or actor.kind != "human"
        or not actor.active
        or not admin
        or ctx.run_id
        or getattr(ctx, "agent_run_id", None)
        or ctx.actor_id != ctx.requester_id
        or data.decision != "批准"
    ):
        raise DomainError("NAMED_DECISION_REQUIRED", "须当前租户管理员本人批准协议登记。")
    # Serialize first registrations too, where no head row exists to lock.
    key = int(digest(["provider-agreement", ctx.tenant_id, data.provider])[:16], 16)
    session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {
            "key": key if key < 2**63 else key - 2**64,
        },
    )
    existing = agreement_receipt(session, ctx, data)
    if existing:
        return existing
    if (
        not data.signed_on.tzinfo
        or not data.expires_at.tzinfo
        or data.signed_on > now()
        or data.expires_at <= now()
        or data.expires_at <= data.signed_on
    ):
        raise DomainError("VALIDATION_FAILED", "协议日期与有效期无效。")
    head = session.scalar(
        select(ProviderDataAgreement)
        .where(
            ProviderDataAgreement.tenant_id == ctx.tenant_id,
            ProviderDataAgreement.provider == data.provider,
        )
        .order_by(ProviderDataAgreement.revision.desc())
        .limit(1)
    )
    semantic = digest(data.model_dump(mode="json"))
    if (head.revision if head else 0) != data.expected_revision:
        raise DomainError("VERSION_CONFLICT", "服务商协议已更新，请读取当前登记。")
    identity, receipt_id, command_id = uuid4(), uuid4(), uuid4()
    receipt = Receipt(
        id=receipt_id,
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=None,
        command_id=command_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        operation="provider.agreement.register",
        subject_type="provider_agreement",
        subject_id=identity,
        subject_revision=data.expected_revision + 1,
        visibility="private",
        request_digest=semantic,
        intent_digest=digest(["provider.agreement.register", ctx.actor_id, data.idempotency_key]),
        result={
            "id": str(identity),
            "provider": data.provider,
            "revision": data.expected_revision + 1,
            "tier": "T2",
            "decided_by": str(ctx.actor_id),
            "decision": "批准",
        },
    )
    session.add(receipt)
    session.flush()
    row = ProviderDataAgreement(
        id=identity,
        tenant_id=ctx.tenant_id,
        provider=data.provider,
        revision=data.expected_revision + 1,
        signed_on=data.signed_on,
        data_categories=list(dict.fromkeys(data.data_categories)),
        retention_terms=data.retention_terms,
        training_terms=data.training_terms,
        expires_at=data.expires_at,
        registered_by=ctx.actor_id,
        active=data.active,
        receipt_id=receipt_id,
    )
    session.add_all(
        [
            row,
            Audit(
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                receipt_id=receipt_id,
                actor_id=ctx.actor_id,
                operation=receipt.operation,
            ),
            Outbox(
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                receipt_id=receipt_id,
                actor_id=ctx.actor_id,
                type="provider.agreement_registered",
                subject_id=identity,
                subject_revision=row.revision,
                correlation_id=command_id,
            ),
        ]
    )
    session.flush()
    return receipt_view(receipt)
