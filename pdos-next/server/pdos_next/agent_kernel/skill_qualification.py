"""Human case reviews and named pilot qualifications, never Agent self-attestation."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import select, text

from pdos_next.errors import DomainError
from pdos_next.model_configuration.commands import CurrentAdministrator
from pdos_next.model_configuration.persistence import (
    ModelConfigurationHead,
    SessionConfigurationStore,
)
from pdos_next.model_configuration.ports import ManagementContext
from pdos_next.models import Category, Grant, Principal, Receipt, RequestKey, now
from pdos_next.request_proof import command_inputs_once
from pdos_next.schema_base import StrictModel

from .models import (
    SkillQualification,
    SkillReviewBatch,
    TenantAdministrator,
    TenantPilotAdmission,
    TenantSkillEnablement,
)
from .qualification_binding import draft_operations, model_identity, tool_identity
from .skills import SkillCatalog

Assessment = Literal["acceptable", "issues", "unknown", "not_applicable"]


class ReviewCriteria(StrictModel):
    coverage: Assessment = "unknown"
    citations: Assessment = "unknown"
    units_conditions: Assessment = "unknown"
    unknowns: Assessment = "unknown"
    scope: Assessment = "unknown"
    length: Assessment = "unknown"


class ReviewCase(StrictModel):
    source_ref: str = Field(min_length=1, max_length=1000)
    material_kind: Literal["own", "synthetic"]
    conclusion: str = Field(min_length=1, max_length=2000)
    severity: Literal["unknown", "none", "minor", "major", "critical"] = "unknown"
    criteria: ReviewCriteria = Field(default_factory=ReviewCriteria)

    @model_validator(mode="after")
    def meaningful(self):
        if not self.source_ref.strip() or not self.conclusion.strip():
            raise ValueError("请填写实际材料定位与本人审阅结论。")
        return self


class BindingInput(StrictModel):
    skill_key: str = Field(min_length=1, max_length=160)
    skill_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class RecordReviews(BindingInput):
    cases: list[ReviewCase] = Field(min_length=1, max_length=20)
    personally_reviewed: Literal[True]
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def unique_cases(self):
        if len({case.source_ref.strip() for case in self.cases}) != len(self.cases):
            raise ValueError("同一批案例材料不得重复。")
        return self


class CaseReference(StrictModel):
    batch_id: UUID
    index: int = Field(ge=0, le=19)


class QualifySkill(StrictModel):
    skill_key: str = Field(min_length=1, max_length=160)
    expected_revision: int = Field(ge=0)
    decision: Literal["批准", "撤销"]
    reason: str = Field(min_length=1, max_length=4000)
    skill_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    tool_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    model_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    case_refs: list[CaseReference] = Field(default_factory=list, max_length=20)
    approval_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def decision_material(self):
        if not self.reason.strip():
            raise ValueError("请填写本人决定理由。")
        if self.decision == "批准" and (
            len(self.case_refs) < 10
            or not all((self.skill_digest, self.tool_digest, self.model_digest))
        ):
            raise ValueError("批准须选择 10–20 个本人已审阅案例并绑定当前技能及模型。")
        if self.decision == "撤销" and self.case_refs:
            raise ValueError("撤销沿用原资格记录，无需重新选择案例。")
        return self


@dataclass
class Prepared:
    row: TenantSkillEnablement | None
    review: dict
    skill: object | None = None
    model: object | None = None
    confirmation_id: UUID | None = None


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token", "approval_token"})


def registry():
    from .tools import default_registry

    return default_registry()


def current_model(session, tenant, *, lock=False):
    if lock:
        session.execute(text("SELECT kernel_model_configuration_lock(:tenant)"), {"tenant": tenant})
    head = session.get(ModelConfigurationHead, tenant)
    return SessionConfigurationStore(session).current(tenant) if head and head.revision else None


def current_binding(session, tenant, key, *, lock=False):
    skill = SkillCatalog().configuration(key)
    model = current_model(session, tenant, lock=lock)
    tools = registry()
    if not skill or not model or not model.enabled:
        raise DomainError("SOURCE_UNAVAILABLE", "请先登记并启用实际模型与技能配置。")
    binding = {
        "skill_digest": skill.digest,
        "tool_digest": tool_identity(skill, tools),
        "model_digest": model_identity(model.metadata),
    }
    return skill, model, binding, draft_operations(skill, tools)


def lock_skill(session, ctx, key):
    from pdos_next.service import digest

    number = int(digest(["skill-enablement", ctx.tenant_id, key])[:16], 16)
    session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": number if number < 2**63 else number - 2**64},
    )
    return session.scalar(
        select(TenantSkillEnablement)
        .where(
            TenantSkillEnablement.tenant_id == ctx.tenant_id, TenantSkillEnablement.skill_key == key
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def is_pilot(session, tenant, *, lock=False):
    if lock:
        return bool(session.scalar(text("SELECT kernel_pilot_active(:tenant)"), {"tenant": tenant}))
    row = session.get(TenantPilotAdmission, tenant)
    return bool(row and row.active)


@command_inputs_once
def prepared(session, ctx, command, scope, payload):
    if command.product_id is not None or command.source_read_set:
        raise DomainError("FORBIDDEN_SCOPE", "资格审阅只接受当前租户的技能配置。", 403)
    if command.expected_revision != scope.revision:
        raise DomainError("VERSION_CONFLICT", "当前品类范围已变化，请刷新。")
    if not CurrentAdministrator(session, ctx).is_current_human_admin(
        ManagementContext(ctx.tenant_id, ctx.actor_id)
    ):
        raise DomainError(
            "NAMED_DECISION_REQUIRED", "请由当前租户管理员本人办理审阅与资格决定。", 403
        )
    row = lock_skill(session, ctx, payload.skill_key)
    if isinstance(payload, QualifySkill):
        if (row.revision if row else 0) != payload.expected_revision:
            raise DomainError("VERSION_CONFLICT", "技能状态或资格已变化，请重新预览。")
        if payload.decision == "撤销":
            if not row or not row.reviewed_by:
                raise DomainError("SOURCE_UNAVAILABLE", "当前没有可撤销的资格记录。")
            return Prepared(
                row,
                {
                    "skill_key": payload.skill_key,
                    "skill_version": row.qualified_skill_version,
                    "model_version": row.qualified_model_version,
                    "model_label": "原登记模型",
                    "decision": "撤销",
                    "reason": payload.reason,
                    "previous_revision": row.revision,
                    "next_revision": row.revision + 1,
                    "case_count": len(row.review_case_refs),
                    "effect": "停止后续 T0，保留原审阅及历史；需要时仍可本人确认 T1。",
                },
            )
    skill, model, binding, writes = current_binding(
        session, ctx.tenant_id, payload.skill_key, lock=True
    )
    if any(getattr(payload, field) != actual for field, actual in binding.items()):
        raise DomainError(
            "VERSION_CONFLICT", "技能、领域工具或实际模型已变化，请重新审阅当前版本。"
        )
    common = {
        "skill_key": skill.key,
        "skill_version": skill.version,
        "model_version": model.metadata.model_version,
        "model_label": model.metadata.model,
        **binding,
    }
    if isinstance(payload, RecordReviews):
        return Prepared(
            row,
            {
                **common,
                "case_count": len(payload.cases),
                "cases": [case.model_dump() for case in payload.cases],
                "critical_count": sum(case.severity == "critical" for case in payload.cases),
                "personally_reviewed": True,
                "effect": "保存本人审阅记录；匹配现有资格的严重错误会暂停 T0，审阅本身不授予资格。",
            },
            skill,
            model,
        )
    if not is_pilot(session, ctx.tenant_id, lock=True) or not writes:
        raise DomainError(
            "QUALIFICATION_REQUIRED", "当前租户未登记为试点，或该技能不适用草稿试点资格。", 403
        )
    if not row or not row.enabled:
        raise DomainError("QUALIFICATION_REQUIRED", "请先启用当前技能，再办理试点资格。", 403)
    ids = {ref.batch_id for ref in payload.case_refs}
    batches = {
        batch.id: batch
        for batch in session.scalars(
            select(SkillReviewBatch).where(
                SkillReviewBatch.tenant_id == ctx.tenant_id,
                SkillReviewBatch.reviewed_by == ctx.actor_id,
                SkillReviewBatch.id.in_(ids),
                SkillReviewBatch.skill_key == skill.key,
            )
        )
    }
    selected = []
    for ref in payload.case_refs:
        batch = batches.get(ref.batch_id)
        if (
            not batch
            or ref.index >= len(batch.cases)
            or (row.quality_paused_at is not None and batch.created_at <= row.quality_paused_at)
            or (batch.skill_digest, batch.tool_digest, batch.model_digest)
            != tuple(binding.values())
        ):
            raise DomainError(
                "SOURCE_UNAVAILABLE", "所选材料必须是本人针对当前技能、工具和模型的已登记审阅。"
            )
        case = batch.cases[ref.index]
        if case["severity"] == "critical":
            raise DomainError(
                "QUALIFICATION_REQUIRED", "存在严重错误，请修正并重新审阅后再决定资格。"
            )
        selected.append(case)
    if len({case["source_ref"].strip() for case in selected}) != len(selected):
        raise DomainError("VALIDATION_FAILED", "所选 10–20 个案例必须来自不同材料。", 422)
    return Prepared(
        row,
        {
            **common,
            "decision": payload.decision,
            "reason": payload.reason,
            "previous_revision": row.revision,
            "next_revision": row.revision + 1,
            "case_count": len(selected),
            "case_refs": [ref.model_dump(mode="json") for ref in payload.case_refs],
            "cases": selected,
            "draft_operations": writes,
            "effect": (
                "允许当前版本草稿动作按 T0 执行；当前授权、来源、协议和预算仍逐次核对，"
                "T2 仍须具名决定。"
            ),
        },
        skill,
        model,
    )


def validate(session, ctx, command, scope, payload):
    return prepared(session, ctx, command, scope, payload)


def preview_view(session, ctx, command, scope, payload):
    return prepared(session, ctx, command, scope, payload).review


def snapshot(row):
    return {
        key: getattr(row, key)
        for key in (
            "pilot",
            "qualification_revoked",
            "qualified_skill_version",
            "qualified_model_version",
            "qualified_skill_digest",
            "qualified_tool_digest",
            "qualified_model_digest",
            "review_case_refs",
            "quality_paused",
        )
    } | {
        "quality_paused_at": row.quality_paused_at.isoformat() if row.quality_paused_at else None,
        "reviewed_by": str(row.reviewed_by) if row.reviewed_by else None,
        "qualification_id": str(row.qualification_id) if row.qualification_id else None,
        "quality_review_id": str(row.quality_review_id) if row.quality_review_id else None,
        "revision": row.revision,
    }


def apply_validated(session, ctx, command, scope, payload, plan):
    receipt = uuid4()
    if isinstance(payload, RecordReviews):
        result = SkillReviewBatch(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            created_at=now(),
            reviewed_by=ctx.actor_id,
            skill_key=payload.skill_key,
            skill_version=plan.skill.version,
            skill_digest=payload.skill_digest,
            tool_digest=payload.tool_digest,
            model_version=plan.model.metadata.model_version,
            model_digest=payload.model_digest,
            model_label=plan.model.metadata.model,
            cases=[case.model_dump() for case in payload.cases],
            receipt_id=receipt,
        )
        row = plan.row
        if (
            plan.review["critical_count"]
            and row
            and (row.qualified_skill_digest, row.qualified_tool_digest, row.qualified_model_digest)
            == (payload.skill_digest, payload.tool_digest, payload.model_digest)
        ):
            row.quality_paused, row.quality_review_id = True, result.id
            row.quality_paused_at = result.created_at
            row.revision += 1
            row.receipt_id = receipt
            session.add(row)
        result.action_result = {
            "skill_key": payload.skill_key,
            "case_count": len(payload.cases),
            "quality_paused": bool(row and row.quality_paused),
        }
        subject = "skill_review"
    else:
        row = plan.row
        result = SkillQualification(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            decided_by=ctx.actor_id,
            skill_key=payload.skill_key,
            decision=payload.decision,
            reason=payload.reason,
            receipt_id=receipt,
        )
        row.qualification_id, row.qualification_revoked = result.id, payload.decision == "撤销"
        row.revision, row.receipt_id = payload.expected_revision + 1, receipt
        if payload.decision == "批准":
            row.pilot, row.quality_paused, row.quality_review_id = True, False, None
            row.quality_paused_at = None
            row.qualified_skill_version, row.qualified_model_version = (
                plan.skill.version,
                plan.model.metadata.model_version,
            )
            row.qualified_skill_digest, row.qualified_tool_digest, row.qualified_model_digest = (
                payload.skill_digest,
                payload.tool_digest,
                payload.model_digest,
            )
            row.reviewed_by, row.reviewed_at = ctx.actor_id, now()
            row.review_case_refs = [f"{ref.batch_id}:{ref.index}" for ref in payload.case_refs]
        result.after_snapshot = snapshot(row)
        result.action_result = {
            "skill_key": payload.skill_key,
            "decision": payload.decision,
            "next_revision": row.revision,
            "case_count": len(row.review_case_refs),
            "binding": result.after_snapshot,
        }
        session.add(row)
        subject = "skill_qualification"
    result.prepared_receipt_id, result.confirmation_id = receipt, plan.confirmation_id
    return result, subject, "private"


def reading(session, ctx, key, cursor=None):
    skill = SkillCatalog().configuration(key)
    row = session.scalar(
        select(TenantSkillEnablement).where(
            TenantSkillEnablement.tenant_id == ctx.tenant_id, TenantSkillEnablement.skill_key == key
        )
    )
    if not skill and not row:
        raise DomainError("SOURCE_UNAVAILABLE", "技能包未登记。", 404)
    model = current_model(session, ctx.tenant_id)
    tools = registry()
    binding = {
        "skill_digest": skill.digest if skill else None,
        "tool_digest": tool_identity(skill, tools) if skill else None,
        "model_digest": model_identity(model.metadata) if model else None,
    }
    query = select(SkillReviewBatch).where(
        SkillReviewBatch.tenant_id == ctx.tenant_id,
        SkillReviewBatch.reviewed_by == ctx.actor_id,
        SkillReviewBatch.skill_key == key,
    )
    if cursor:
        batch = session.get(SkillReviewBatch, cursor)
        if not batch or batch.reviewed_by != ctx.actor_id or batch.skill_key != key:
            raise DomainError("VALIDATION_FAILED", "审阅分页定位已失效，请刷新。", 422)
        from sqlalchemy import tuple_

        query = query.where(
            tuple_(SkillReviewBatch.created_at, SkillReviewBatch.id) < (batch.created_at, batch.id)
        )
    batches = list(
        session.scalars(
            query.order_by(SkillReviewBatch.created_at.desc(), SkillReviewBatch.id.desc()).limit(21)
        )
    )
    admin = session.scalar(
        select(TenantAdministrator.id).where(
            TenantAdministrator.principal_id == ctx.actor_id, TenantAdministrator.active.is_(True)
        )
    )
    write = session.scalar(
        select(Grant.can_write).where(
            Grant.principal_id == ctx.actor_id, Grant.category_id == ctx.category_id
        )
    )
    current = bool(
        row
        and model
        and skill
        and row.qualified_skill_digest == binding["skill_digest"]
        and row.qualified_tool_digest == binding["tool_digest"]
        and row.qualified_model_digest == binding["model_digest"]
    )
    pilot = is_pilot(session, ctx.tenant_id)
    state = (
        "not_recorded"
        if not row or not row.reviewed_by
        else "revoked"
        if row.qualification_revoked
        else "paused"
        if row.quality_paused
        else "stale"
        if not current
        else "inactive"
        if not row.enabled or not model.enabled or not pilot
        else "qualified"
    )
    person = session.get(Principal, row.reviewed_by) if row and row.reviewed_by else None
    return {
        "skill_key": key,
        "skill_version": skill.version if skill else None,
        **binding,
        "model_version": model.metadata.model_version if model else None,
        "model_label": model.metadata.model if model else None,
        "model_enabled": bool(model and model.enabled),
        "pilot": pilot,
        "draft_operations": draft_operations(skill, tools) if skill else [],
        "enabled": bool(row and row.enabled),
        "revision": row.revision if row else 0,
        "can_edit": bool(admin and write),
        "category_revision": session.get(Category, ctx.category_id).revision,
        "qualification": {
            "state": state,
            "id": str(row.qualification_id) if row and row.qualification_id else None,
            "reviewed_by_name": person.name if person else None,
            "reviewed_at": row.reviewed_at.isoformat() if row and row.reviewed_at else None,
            "case_count": len(row.review_case_refs) if row else 0,
            "receipt_id": str(row.receipt_id) if row and row.receipt_id else None,
        },
        "reviews": [
            {
                "id": str(batch.id),
                "skill_version": batch.skill_version,
                "model_version": batch.model_version,
                "created_at": batch.created_at.isoformat(),
                "receipt_id": str(batch.receipt_id),
                "cases": batch.cases,
                "current": (batch.skill_digest, batch.tool_digest, batch.model_digest)
                == tuple(binding.values()),
            }
            for batch in batches[:20]
        ],
        "next_cursor": str(batches[19].id) if len(batches) > 20 else None,
    }


def recover(session, ctx, command):
    from pdos_next.service import command_digest, receipt_view

    cls = {"ai.skill.review.record": RecordReviews, "ai.skill.qualify": QualifySkill}.get(
        command.operation
    )
    if not cls or command.product_id is not None or command.source_read_set:
        raise DomainError("VALIDATION_FAILED", "这里只核对原案例审阅与资格请求。", 422)
    if command.category_id is not None and command.category_id != ctx.category_id:
        raise DomainError("FORBIDDEN_SCOPE", "原请求与当前品类不一致。", 403)
    cls.model_validate(command.payload)
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
    if not row or row.operation != command.operation or row.category_id != ctx.category_id:
        raise DomainError("FORBIDDEN_SCOPE", "原回执不在当前可读范围。", 403)
    return receipt_view(row)
