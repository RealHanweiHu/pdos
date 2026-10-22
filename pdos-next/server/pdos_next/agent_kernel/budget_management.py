"""Human-owned budget controls preserve the wallet's immutable limits and settlement ledger."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import and_, or_, select, text

from pdos_next.errors import DomainError
from pdos_next.model_configuration.commands import CurrentAdministrator
from pdos_next.model_configuration.ports import ManagementContext
from pdos_next.models import Category, Grant, Receipt, RequestKey
from pdos_next.request_proof import command_inputs_once
from pdos_next.schema_base import StrictModel

from .models import TenantAdministrator, ValidationBudget

MAX_INTEGER = 2_147_483_647


class Limits(StrictModel):
    limit_micro_usd: int = Field(ge=0, le=MAX_INTEGER)
    input_token_limit: int = Field(ge=1, le=MAX_INTEGER)
    output_token_limit: int = Field(ge=1, le=MAX_INTEGER)
    call_limit: int = Field(ge=1, le=MAX_INTEGER)


class ConfigureBudget(StrictModel):
    action: Literal["allocate", "stop"]
    expected_active_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    limits: Limits | None = None
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def shape(self):
        if (self.action == "allocate") != (self.limits is not None):
            raise ValueError("Only allocation carries a new set of limits")
        return self


class BudgetPage(StrictModel):
    page_size: int = Field(default=20, ge=1, le=200)
    cursor: UUID | None = None


@dataclass
class Plan:
    active: list
    review: dict
    confirmation_id: UUID | None = None


def owned(ctx):
    return (
        ValidationBudget.tenant_id == ctx.tenant_id,
        ValidationBudget.requester_id == ctx.requester_id,
    )


def control_revision(session, ctx):
    return (
        session.scalar(
            select(ValidationBudget.revision)
            .where(*owned(ctx))
            .order_by(ValidationBudget.revision.desc())
            .limit(1)
        )
        or 0
    )


def watermark(rows, revision):
    from pdos_next.service import digest

    return digest(
        {
            "control_revision": revision,
            "active": sorted([[str(row.id), row.revision] for row in rows]),
        }
    )


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


@command_inputs_once
def prepared(session, ctx, command, scope, payload):
    from pdos_next.service import digest

    if command.product_id is not None or command.source_read_set:
        raise DomainError("FORBIDDEN_SCOPE", "预算仅按本人当前租户办理。", 403)
    if command.expected_revision != scope.revision:
        raise DomainError("VERSION_CONFLICT", "当前品类范围已变化，请刷新。")
    if not CurrentAdministrator(session, ctx).is_current_human_admin(
        ManagementContext(ctx.tenant_id, ctx.actor_id)
    ):
        raise DomainError("NAMED_DECISION_REQUIRED", "预算变更须当前租户管理员本人确认。", 403)
    key = int(digest(["agent-budget-control", ctx.tenant_id, ctx.requester_id])[:16], 16)
    session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": key if key < 2**63 else key - 2**64}
    )
    rows = list(
        session.scalars(
            select(ValidationBudget)
            .where(
                *owned(ctx),
                ValidationBudget.active.is_(True),
            )
            .order_by(ValidationBudget.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    revision = control_revision(session, ctx)
    if watermark(rows, revision) != payload.expected_active_digest:
        raise DomainError("VERSION_CONFLICT", "当前活动预算已变化，请重新读取和预览。")
    if payload.action == "stop" and not rows:
        raise DomainError("VERSION_CONFLICT", "当前没有活动预算，无需重复停用。")
    return Plan(
        rows,
        {
            "action": payload.action,
            "control_revision": revision,
            "next_revision": revision + 1,
            "scope": "requester",
            "requester_id": str(ctx.requester_id),
            "expected_active_digest": payload.expected_active_digest,
            "limits": payload.limits.model_dump() if payload.limits else None,
            "retired_budgets": [
                {
                    "id": str(row.id),
                    "previous_revision": row.revision,
                    "next_revision": revision + 1,
                }
                for row in rows
            ],
            "existing_usage_preserved": True,
        },
    )


def validate(session, ctx, command, scope, payload):
    return prepared(session, ctx, command, scope, payload)


def preview_view(session, ctx, command, scope, payload):
    return prepared(session, ctx, command, scope, payload).review


def apply_validated(session, ctx, command, scope, payload, plan):
    receipt_id = uuid4()
    for row in plan.active:
        row.active, row.revision, row.receipt_id = False, plan.review["next_revision"], receipt_id
    if payload.action == "allocate":
        subject = ValidationBudget(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            requester_id=ctx.requester_id,
            active=True,
            revision=plan.review["next_revision"],
            receipt_id=receipt_id,
            **payload.limits.model_dump(),
        )
    else:
        subject = max(plan.active, key=lambda row: (row.created_at, -row.id.int))
    subject.prepared_receipt_id = receipt_id
    subject.confirmation_id = plan.confirmation_id
    subject.status = "active" if subject.active else "stopped"
    subject.action_result = {
        **plan.review,
        "allocated_budget_id": str(subject.id) if payload.action == "allocate" else None,
    }
    return subject, "agent_budget", "private"


def view(row):
    return {
        "id": str(row.id),
        "revision": row.revision,
        "active": row.active,
        "created_at": row.created_at.isoformat(),
        "receipt_id": str(row.receipt_id) if row.receipt_id else None,
        **{
            name: getattr(row, name)
            for name in (
                "limit_micro_usd",
                "input_token_limit",
                "output_token_limit",
                "call_limit",
                "calls",
                "held_micro_usd",
                "spent_micro_usd",
                "held_input_tokens",
                "used_input_tokens",
                "held_output_tokens",
                "used_output_tokens",
            )
        },
    }


def reading(session, ctx, page):
    active = list(
        session.scalars(
            select(ValidationBudget)
            .where(
                *owned(ctx),
                ValidationBudget.active.is_(True),
            )
            .order_by(ValidationBudget.created_at.desc(), ValidationBudget.id)
        )
    )
    query = select(ValidationBudget).where(*owned(ctx))
    if page.cursor:
        anchor = session.get(ValidationBudget, page.cursor)
        if (
            not anchor
            or anchor.tenant_id != ctx.tenant_id
            or anchor.requester_id != ctx.requester_id
        ):
            raise DomainError("VALIDATION_FAILED", "预算分页位置无效，请重新读取。", 422)
        query = query.where(
            or_(
                ValidationBudget.created_at < anchor.created_at,
                and_(
                    ValidationBudget.created_at == anchor.created_at,
                    ValidationBudget.id > anchor.id,
                ),
            )
        )
    rows = list(
        session.scalars(
            query.order_by(
                ValidationBudget.created_at.desc(),
                ValidationBudget.id,
            ).limit(page.page_size + 1)
        )
    )
    admin = session.scalar(
        select(TenantAdministrator.id).where(
            TenantAdministrator.tenant_id == ctx.tenant_id,
            TenantAdministrator.principal_id == ctx.actor_id,
            TenantAdministrator.active.is_(True),
        )
    )
    write = session.scalar(
        select(Grant.can_write).where(
            Grant.tenant_id == ctx.tenant_id,
            Grant.category_id == ctx.category_id,
            Grant.principal_id == ctx.actor_id,
        )
    )
    category = session.get(Category, ctx.category_id)
    revision = control_revision(session, ctx)
    return {
        "can_edit": bool(admin and write),
        "category_revision": category.revision,
        "requester_id": str(ctx.requester_id),
        "active_digest": watermark(active, revision),
        "control_revision": revision,
        "selected_budget_id": str(active[0].id) if active else None,
        "active_budgets": [view(row) for row in active],
        "items": [view(row) for row in rows[: page.page_size]],
        "next_cursor": str(rows[page.page_size - 1].id) if len(rows) > page.page_size else None,
    }


def recover(session, ctx, command):
    from pdos_next.service import command_digest, receipt_view

    if (
        command.operation != "ai.budget.configure"
        or command.product_id is not None
        or command.source_read_set
    ):
        raise DomainError("VALIDATION_FAILED", "这里只核对本人原预算请求。", 422)
    if command.category_id != ctx.category_id:
        raise DomainError("FORBIDDEN_SCOPE", "原请求与当前品类不一致。", 403)
    ConfigureBudget.model_validate(command.payload)
    key = session.scalar(
        select(RequestKey).where(
            RequestKey.tenant_id == ctx.tenant_id,
            RequestKey.actor_id == ctx.actor_id,
            RequestKey.key == command.idempotency_key,
        )
    )
    if key is None:
        return None
    if key.digest != command_digest(command):
        raise DomainError("DUPLICATE_INTENT_CONFLICT", "原预算请求编号已绑定不同内容。")
    row = session.get(Receipt, key.receipt_id)
    if row is None or row.operation != command.operation or row.category_id != ctx.category_id:
        raise DomainError("FORBIDDEN_SCOPE", "原预算回执不在当前可读范围。", 403)
    return receipt_view(row)
