"""Category authorization uses authoritative model ownership, never caller ACLs."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import select

from pdos_next.contracts import Command, StrictModel
from pdos_next.domain.preproject.category_creation import CategoryCreate as CategoryCreate
from pdos_next.domain.preproject.category_creation import create as create_category  # noqa: F401
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Category, Grant, Outbox, Principal, Receipt, RequestKey, now
from pdos_next.service import digest, receipt_view


@dataclass(frozen=True)
class CategoryScope:
    """An actual authorized category, with no invented model identity."""

    category_id: UUID
    revision: int
    owner_id: UUID
    name: str
    lifecycle_epoch: int
    id: None = None
    visibility: str = "category"


def category_scope(s, ctx, *, write=False, lock=False):
    from pdos_next.database import require_context
    from pdos_next.request_proof import request_proof

    require_context(s, ctx)
    category = s.get(Category, ctx.category_id)
    if category is None or category.tenant_id != ctx.tenant_id:
        raise DomainError("FORBIDDEN_SCOPE", "品类不在当前授权范围。", 403)
    proof = request_proof(s)
    key = (ctx.tenant_id, category.id, ctx.actor_id, ctx.requester_id)
    cached = proof.authority.get(key)
    if cached is None or (lock and not cached["locked"]):
        people = sorted({ctx.actor_id, ctx.requester_id}, key=str)
        query = (
            select(Principal, Grant)
            .join(
                Grant,
                (Grant.tenant_id == Principal.tenant_id) & (Grant.principal_id == Principal.id),
            )
            .where(
                Principal.tenant_id == ctx.tenant_id,
                Principal.id.in_(people),
                Grant.category_id == category.id,
            )
            .order_by(Principal.id)
            .execution_options(populate_existing=True)
        )
        rows = s.execute(query.with_for_update(read=True) if lock else query).all()
        if len(rows) != len(people) or any(
            not person.active or (grant.expires_at is not None and grant.expires_at <= now())
            for person, grant in rows
        ):
            raise DomainError("FORBIDDEN_SCOPE", "当前身份没有品类权限。", 403)
        cached = {
            "locked": lock,
            "can_write": all(g.can_write for _, g in rows),
            "epochs": tuple((p.id, p.access_epoch, g.access_epoch) for p, g in rows),
            "rows": rows,
        }
        proof.authority[key] = cached
    from pdos_next.request_proof import authority_current

    if not authority_current(cached["rows"], now()):
        raise DomainError("FORBIDDEN_SCOPE", "当前身份的品类授权已失效。", 403)
    if write and not cached["can_write"]:
        raise DomainError("FORBIDDEN_SCOPE", "当前身份没有品类写入权限。", 403)
    return CategoryScope(
        category.id, category.revision, category.owner_id, category.name, category.lifecycle_epoch
    )


class MemberGrant(StrictModel):
    principal_id: UUID
    can_write: bool
    expires_at: datetime | None = None
    product_manager: bool | None = None
    expected_revision: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=160)
    decision: Literal["批准"]


def grant_member(s, ctx, data):
    """Named T2 decision, with actor identity supplied only by the authenticated context."""
    from pdos_next.database import require_context

    require_context(s, ctx)
    category = s.get(Category, ctx.category_id)
    actor = s.get(Principal, ctx.actor_id)
    if (
        not category
        or not actor
        or actor.kind != "human"
        or not actor.active
        or category.owner_id != actor.id
        or ctx.run_id
        or ctx.agent_run_id
        or ctx.actor_id != ctx.requester_id
    ):
        raise DomainError("NAMED_DECISION_REQUIRED", "须品类负责人本人批准成员授权。", 403)
    semantic = digest(data.model_dump(mode="json"))
    prior = s.scalar(
        select(RequestKey).where(
            RequestKey.actor_id == ctx.actor_id, RequestKey.key == data.idempotency_key
        )
    )
    if prior:
        if prior.digest != semantic:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号已绑定其他内容。")
        return receipt_view(s.get(Receipt, prior.receipt_id))
    category = s.scalar(select(Category).where(Category.id == category.id).with_for_update())
    if category.revision != data.expected_revision:
        raise DomainError("VERSION_CONFLICT", "品类成员范围已变化，请刷新后批准。")
    member = s.get(Principal, data.principal_id)
    if not member or not member.active or member.tenant_id != ctx.tenant_id:
        raise DomainError("FORBIDDEN_SCOPE", "成员不在当前租户范围。", 403)
    if data.expires_at is not None and (data.expires_at.tzinfo is None or data.expires_at <= now()):
        raise DomainError("VALIDATION_FAILED", "授权须指定未来的带时区有效期。", 422)
    grant = s.scalar(
        select(Grant)
        .where(Grant.category_id == category.id, Grant.principal_id == member.id)
        .with_for_update()
    )
    if grant is None:
        grant = Grant(tenant_id=ctx.tenant_id, category_id=category.id, principal_id=member.id)
        s.add(grant)
    grant.can_write, grant.expires_at = data.can_write, data.expires_at
    if data.product_manager is not None:
        grant.product_manager = data.product_manager
    category.revision += 1
    s.flush()
    receipt = Receipt(
        tenant_id=ctx.tenant_id,
        category_id=category.id,
        product_id=None,
        command_id=uuid4(),
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        operation="category.member.grant",
        subject_type="category",
        subject_id=category.id,
        subject_revision=category.revision,
        visibility="category",
        request_digest=semantic,
        intent_digest=digest(["category.member.grant", category.id, semantic]),
        result={
            "member_id": str(member.id),
            "can_write": grant.can_write,
            "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
            "product_manager": grant.product_manager,
            "decision": "批准",
            "decided_by": str(ctx.actor_id),
            "tier": "T2",
        },
    )
    s.add(receipt)
    s.flush()
    s.add_all(
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
                type="category.member_granted",
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
    s.flush()
    return receipt_view(receipt)


def require_command_category(s, ctx, command: Command):
    from pdos_next.database import require_context

    require_context(s, ctx)
    category = s.get(Category, command.category_id)
    if not category or (ctx.category_id is not None and ctx.category_id != category.id):
        raise DomainError("FORBIDDEN_SCOPE", "品类不在当前范围。", 403)
    if ctx.run_id:
        from pdos_next.models import Product, Run

        run = s.get(Run, ctx.run_id)
        product = s.get(Product, run.product_id) if run else None
        if not product or product.category_id != category.id:
            raise DomainError("FORBIDDEN_SCOPE", "运行与命令品类不匹配。", 403)
    if ctx.agent_run_id:
        from pdos_next.agent_kernel.models import AgentRun

        run = s.get(AgentRun, ctx.agent_run_id)
        if not run or run.category_id != category.id or run.product_id != command.product_id:
            raise DomainError("FORBIDDEN_SCOPE", "运行与命令范围不匹配。", 403)
    return category
