"""Tenant skill T1 toggles share the COMMON proof, receipt and atomic transaction."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import select, text

from pdos_next.errors import DomainError
from pdos_next.model_configuration.commands import CurrentAdministrator
from pdos_next.model_configuration.ports import ManagementContext
from pdos_next.models import Category, Grant, Receipt, RequestKey
from pdos_next.request_proof import command_inputs_once
from pdos_next.schema_base import StrictModel

from .models import TenantAdministrator, TenantSkillEnablement
from .skills import SkillCatalog


class EnableSkill(StrictModel):
    skill_key: str = Field(min_length=1, max_length=160)
    expected_revision: int = Field(ge=0)
    skill_version: str | None = Field(default=None, min_length=1, max_length=160)
    skill_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    enabled: bool
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)


@dataclass
class Prepared:
    row: TenantSkillEnablement | None
    review: dict
    confirmation_id: UUID | None = None


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


@command_inputs_once
def prepared(session, ctx, command, scope, payload):
    from pdos_next.service import digest

    if command.product_id is not None or command.source_read_set:
        raise DomainError("FORBIDDEN_SCOPE", "技能启用只接受当前租户的技能配置。", 403)
    if command.expected_revision != scope.revision:
        raise DomainError("VERSION_CONFLICT", "当前品类范围已变化，请刷新。")
    if not CurrentAdministrator(session, ctx).is_current_human_admin(
        ManagementContext(ctx.tenant_id, ctx.actor_id)
    ):
        raise DomainError(
            "NAMED_DECISION_REQUIRED", "请由当前租户管理员本人确认技能启用或停用。", 403
        )
    key = int(digest(["skill-enablement", ctx.tenant_id, payload.skill_key])[:16], 16)
    session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": key if key < 2**63 else key - 2**64}
    )
    row = session.scalar(
        select(TenantSkillEnablement)
        .where(
            TenantSkillEnablement.tenant_id == ctx.tenant_id,
            TenantSkillEnablement.skill_key == payload.skill_key,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (row.revision if row else 0) != payload.expected_revision:
        raise DomainError("VERSION_CONFLICT", "技能启用状态已变化，请核对当前版本。")
    skill = SkillCatalog().configuration(payload.skill_key)
    if skill is None and (payload.enabled or row is None):
        raise DomainError("SOURCE_UNAVAILABLE", "技能包未登记或已从当前配置中移除。")
    version, content = (skill.version, skill.digest) if skill else (None, None)
    if (version, content) != (payload.skill_version, payload.skill_digest):
        raise DomainError("VERSION_CONFLICT", "技能包配置已变化，请重新读取和预览。")
    return Prepared(
        row,
        {
            "skill_key": payload.skill_key,
            "skill_version": version,
            "skill_digest": content,
            "previous_revision": payload.expected_revision,
            "next_revision": payload.expected_revision + 1,
            "previous_enabled": bool(row and row.enabled),
            "enabled": payload.enabled,
            "scope": "tenant",
            "qualification_changed": False,
        },
    )


def validate(session, ctx, command, scope, payload):
    return prepared(session, ctx, command, scope, payload)


def preview_view(session, ctx, command, scope, payload):
    return prepared(session, ctx, command, scope, payload).review


def apply_validated(session, ctx, command, scope, payload, plan):
    row = plan.row or TenantSkillEnablement(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        skill_key=payload.skill_key,
    )
    row.enabled, row.revision = payload.enabled, payload.expected_revision + 1
    row.receipt_id = row.prepared_receipt_id = uuid4()
    row.confirmation_id = plan.confirmation_id
    row.status = "enabled" if payload.enabled else "disabled"
    row.action_result = plan.review
    return row, "skill_enablement", "private"


def reading(session, ctx):
    catalog = SkillCatalog()
    rows = {
        row.skill_key: row
        for row in session.scalars(
            select(TenantSkillEnablement).where(
                TenantSkillEnablement.tenant_id == ctx.tenant_id,
            )
        )
    }
    keys = sorted({item["key"] for item in catalog.index} | rows.keys())
    admin = session.scalar(
        select(TenantAdministrator.id).where(
            TenantAdministrator.principal_id == ctx.actor_id,
            TenantAdministrator.active.is_(True),
        )
    )
    write = session.scalar(
        select(Grant.can_write).where(
            Grant.principal_id == ctx.actor_id,
            Grant.category_id == ctx.category_id,
        )
    )
    category = session.get(Category, ctx.category_id)
    items = []
    for key in keys:
        skill, row = catalog.configuration(key), rows.get(key)
        items.append(
            {
                "skill_key": key,
                "purpose": skill.purpose if skill else "技能包已从当前配置中移除",
                "skill_version": skill.version if skill else None,
                "skill_digest": skill.digest if skill else None,
                "available": skill is not None,
                "operations": sorted(skill.operations) if skill else [],
                "enabled": bool(row and row.enabled),
                "revision": row.revision if row else 0,
                "receipt_id": str(row.receipt_id) if row and row.receipt_id else None,
                "qualification_record": "revoked"
                if row and row.qualification_revoked
                else "recorded"
                if row and row.reviewed_by and row.reviewed_at
                else "not_recorded",
            }
        )
    return {
        "items": items,
        "can_edit": bool(admin and write),
        "category_revision": category.revision,
    }


def recover(session, ctx, command):
    from pdos_next.service import command_digest, receipt_view

    if (
        command.operation != "ai.skill.enable"
        or command.product_id is not None
        or command.source_read_set
    ):
        raise DomainError("VALIDATION_FAILED", "这里只核对原技能启用请求。", 422)
    if command.category_id is not None and command.category_id != ctx.category_id:
        raise DomainError("FORBIDDEN_SCOPE", "原请求与当前品类不一致。", 403)
    EnableSkill.model_validate(command.payload)
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
        raise DomainError("DUPLICATE_INTENT_CONFLICT", "原请求编号已绑定不同内容。")
    row = session.get(Receipt, key.receipt_id)
    if row is None or row.operation != command.operation or row.category_id != ctx.category_id:
        raise DomainError("FORBIDDEN_SCOPE", "原回执不在当前可读范围。", 403)
    return receipt_view(row)
