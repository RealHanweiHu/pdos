"""Human category metadata; identities, audiences and materials stay unchanged."""

from uuid import uuid4

from pydantic import Field, field_validator
from sqlalchemy import select

from pdos_next.category_scope import category_scope
from pdos_next.contracts import StrictModel
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Category, Grant, Outbox, Receipt, RequestKey
from pdos_next.service import digest, receipt_view

from .access import human


class CategoryMetadata(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    purpose: str = Field(min_length=1, max_length=4000)
    expected_revision: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=160)

    @field_validator("name", "purpose")
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError("名称和主要场景不能为空")
        return value.strip()


def read(session, ctx):
    human(session, ctx)
    category_scope(session, ctx)
    category = session.get(Category, ctx.category_id)
    grant = session.scalar(
        select(Grant).where(Grant.category_id == category.id, Grant.principal_id == ctx.actor_id)
    )
    return {
        "id": str(category.id),
        "name": category.name,
        "purpose": category.purpose,
        "revision": category.revision,
        "can_edit": bool(grant and grant.can_write and category.status == "active"),
    }


def update(session, ctx, data):
    human(session, ctx)
    category_scope(session, ctx, write=True, lock=True)
    category = session.scalar(
        select(Category)
        .where(Category.id == ctx.category_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if category.status != "active":
        raise DomainError("FORBIDDEN_SCOPE", "已归档品类不能修改，请先恢复。", 403)
    semantic = digest(["category.metadata.update", str(category.id), data.model_dump(mode="json")])
    prior = session.scalar(
        select(RequestKey).where(
            RequestKey.actor_id == ctx.actor_id, RequestKey.key == data.idempotency_key
        )
    )
    if prior:
        if prior.digest != semantic:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号已绑定其他内容。")
        return receipt_view(session.get(Receipt, prior.receipt_id))
    if category.revision != data.expected_revision:
        raise DomainError("VERSION_CONFLICT", "品类已更新，编辑内容已保留，请重新读取后核对。")
    before = {"name": category.name, "purpose": category.purpose, "revision": category.revision}
    category.name, category.purpose = data.name, data.purpose
    category.revision += 1
    receipt = Receipt(
        tenant_id=ctx.tenant_id,
        category_id=category.id,
        product_id=None,
        command_id=uuid4(),
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        operation="category.metadata.update",
        subject_type="category",
        subject_id=category.id,
        subject_revision=category.revision,
        visibility="category",
        request_digest=semantic,
        intent_digest=digest(["category.metadata.update", str(category.id), semantic]),
        result={
            "before": before,
            "name": category.name,
            "purpose": category.purpose,
            "edited_by": str(ctx.actor_id),
        },
    )
    session.add(receipt)
    session.flush()
    session.add_all(
        [
            Audit(
                tenant_id=ctx.tenant_id,
                category_id=category.id,
                receipt_id=receipt.id,
                actor_id=ctx.actor_id,
                operation=receipt.operation,
            ),
            Outbox(
                tenant_id=ctx.tenant_id,
                category_id=category.id,
                receipt_id=receipt.id,
                actor_id=ctx.actor_id,
                type="category.metadata_updated",
                subject_id=category.id,
                subject_revision=category.revision,
                correlation_id=receipt.command_id,
            ),
            RequestKey(
                tenant_id=ctx.tenant_id,
                category_id=category.id,
                actor_id=ctx.actor_id,
                key=data.idempotency_key,
                digest=semantic,
                receipt_id=receipt.id,
            ),
        ]
    )
    session.flush()
    return receipt_view(receipt)
