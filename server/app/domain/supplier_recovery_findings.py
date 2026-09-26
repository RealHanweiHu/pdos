"""Persist source-bound supplier recovery candidates from successful model receipts."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, select

from app.ai.quality import FindingQualityService
from app.ai.rollout_guard import require_live_finding
from app.auth.roles import Action
from app.contracts.supplier_recovery import Selection, SupplierRecoveryAssessment
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain
from app.domain.quality_work_packages import members
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


def persist(
    c: Connection,
    *,
    row: Any,
    snapshot: dict[str, Any],
    output: SupplierRecoveryAssessment,
    invocation_id: UUID,
    created_at: datetime,
) -> UUID | None:
    from app.ai.supplier_recovery_preparation import source_state, validate_assessment
    from app.domain.findings import FINDING_PREFLIGHT_VERSION

    require_live_finding("supplier_intelligence", "supplier_recovery")
    if (
        row["agent_key"] != "supplier_intelligence"
        or row["context_version"] != "supplier-recovery-request-v1"
    ):
        raise ProductWorkError("供应恢复候选须来自原版本实际运行")
    if row["run_context"].get("supply_source") != snapshot:
        raise ProductWorkError("本次来源未固定在原运行")
    invocation = c.execute(
        select(tables.model_invocations.c.id).where(
            tables.model_invocations.c.tenant_id == row["tenant_id"],
            tables.model_invocations.c.project_id == row["project_id"],
            tables.model_invocations.c.run_id == row["id"],
            tables.model_invocations.c.id == invocation_id,
            tables.model_invocations.c.agent_key == row["agent_key"],
            tables.model_invocations.c.prompt_version
            == row["run_context"]["supply_prompt_version"],
            tables.model_invocations.c.status == "succeeded",
        )
    ).first()
    if invocation is None:
        raise ProductWorkError("缺少实际成功的供应恢复模型回执")
    current = source_state(
        c, row["tenant_id"], row["project_id"], Selection.model_validate(snapshot["selection"])
    )
    if current["digest"] != snapshot["digest"]:
        raise ProductWorkError("原供应资料已变化，请重新准备")
    validate_assessment(output, snapshot)
    if output.disposition == "insufficient_evidence":
        return None
    if not FindingQualityService.is_output_allowed_connection(
        c,
        tenant_id=row["tenant_id"],
        agent_key="supplier_intelligence",
        finding_type="supplier_recovery",
    ):
        raise ProductWorkError("供应恢复候选输出已被质量控制收窄")
    origin = "supplier-recovery:" + snapshot["digest"]
    prior = c.execute(
        select(tables.findings.c.id).where(
            tables.findings.c.tenant_id == row["tenant_id"],
            tables.findings.c.run_id == row["id"],
            tables.findings.c.origin_key == origin,
        )
    ).scalar_one_or_none()
    if prior:
        return UUID(str(prior))
    identity = uuid4()
    payload = {
        "source_digest": snapshot["digest"],
        "selection": snapshot["selection"],
        "assessment": output.model_dump(mode="json"),
        "reference_labels": {
            r["reference_id"]: r["label"] for r in snapshot["model_context"]["references"]
        },
    }
    c.execute(
        tables.findings.insert().values(
            id=identity,
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            run_id=row["id"],
            model_invocation_id=invocation_id,
            agent_key="supplier_intelligence",
            finding_type="supplier_recovery",
            origin_key=origin,
            status="pending_review",
            title="供应恢复方案待审稿",
            summary="核对实际短缺、供方依据和恢复条件；" + output.coverage_limits,
            proposed_payload=payload,
            evidence_event_ids=[],
            confidence_basis_points=0,
            preflight_version=FINDING_PREFLIGHT_VERSION,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    c.execute(
        tables.finding_actions.insert().values(
            id=uuid4(),
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            finding_id=identity,
            action="created",
            actor_user_id=None,
            to_status="pending_review",
            detail={"source": "supplier_recovery_sources", "source_digest": snapshot["digest"]},
            created_at=created_at,
        )
    )
    EventAuditWriter(
        c,
        tenant_id=row["tenant_id"],
        project_id=row["project_id"],
        actor_user_id=row["requested_by_user_id"],
    ).record(
        EventDraft(
            event_id=f"ai-finding:{identity}:created",
            event_type="AI_FINDING_CREATED",
            source="ai_runtime",
            entity_id=identity,
            occurred_at=created_at,
            payload={"finding_id": str(identity), "agent_run_id": str(row["id"])},
        ),
        AuditDraft(
            action="finding.create_supplier_recovery",
            after_snapshot={"finding_id": str(identity)},
            context={
                "source_digest": snapshot["digest"],
                "model_invocation_id": str(invocation_id),
            },
        ),
    )
    return identity


if TYPE_CHECKING:
    from app.domain.findings import FindingRecord


class RecoveryChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(min_length=1, max_length=80)
    disposition: Literal["adopt", "exclude"]
    reason: str = Field(min_length=1, max_length=4000)
    description: str = Field(default="", max_length=4000)
    verification: str = Field(default="", max_length=4000)
    completion_criteria: str = Field(default="", max_length=4000)
    missing_resolution: str = Field(default="", max_length=4000)
    owner_user_id: UUID | None = None
    stage_id: UUID | None = None
    due_date: date | None = None
    communication_draft: str = Field(default="", max_length=6000)

    @model_validator(mode="after")
    def complete(self) -> RecoveryChoice:
        if self.disposition == "adopt" and (
            not self.description
            or not self.verification
            or not self.completion_criteria
            or not self.missing_resolution
            or self.owner_user_id is None
            or self.due_date is None
        ):
            raise ValueError("采用项须补齐内容、验证、完成判据、缺项处理、实际负责人及日期")
        return self


class RecoveryReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=4000)
    scope_and_limits: str = Field(min_length=1, max_length=4000)
    choices: list[RecoveryChoice] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def complete(self) -> RecoveryReview:
        if len({c.key for c in self.choices}) != len(self.choices):
            raise ValueError("每项方案须独立核对且不可重复")
        if not any(c.disposition == "adopt" for c in self.choices):
            raise ValueError("全部不采用时请填写理由并拒绝候选")
        return self


class SupplierRecoveryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    selection: Selection
    assessment: SupplierRecoveryAssessment
    reference_labels: dict[str, str]
    review: RecoveryReview | None = None
    details_confirmed: bool = False


def review_context(c: Connection, tenant: UUID, project: UUID) -> dict[str, Any]:
    s, p = tables.stages, tables.projects
    stages = (
        c.execute(
            select(s.c.id, s.c.name)
            .join(p, (p.c.tenant_id == s.c.tenant_id) & (p.c.workflow_id == s.c.workflow_id))
            .where(p.c.tenant_id == tenant, p.c.id == project)
            .order_by(s.c.sequence, s.c.id)
        )
        .mappings()
        .all()
    )
    return {"members": members(c, tenant, project), "stages": [_plain(row) for row in stages]}


def authorize(c: Connection, finding: FindingRecord, actor: UUID) -> None:
    from app.domain.findings import FindingService

    for action in (
        Action.PRODUCT_ENGINEERING_VIEW,
        Action.PRODUCT_ENGINEERING_EDIT,
        Action.WORK_ITEM_VIEW,
        Action.WORK_ITEM_EDIT,
    ):
        FindingService._authorize_user(
            c,
            tenant_id=finding.tenant_id,
            project_id=finding.project_id,
            user_id=actor,
            action=action,
        )


def validate_review(
    c: Connection, finding: FindingRecord, payload: SupplierRecoveryPayload
) -> dict[str, Any]:
    from app.ai.supplier_recovery_preparation import source_state, validate_assessment

    if payload.review is None or not payload.details_confirmed:
        raise ProductWorkError("请逐项核对方案、责任日期、验证和缺项处理")
    original = payload.model_dump(mode="json", exclude={"review", "details_confirmed"})
    if original != {
        k: v
        for k, v in finding.proposed_payload.items()
        if k not in {"review", "details_confirmed"}
    }:
        raise ProductWorkError("原方案、对象及字段依据不可改写，请在人工核对栏记录调整")
    run = c.execute(
        select(tables.agent_runs.c.run_context).where(
            tables.agent_runs.c.tenant_id == finding.tenant_id,
            tables.agent_runs.c.project_id == finding.project_id,
            tables.agent_runs.c.id == finding.run_id,
            tables.agent_runs.c.context_version == "supplier-recovery-request-v1",
        )
    ).scalar_one_or_none()
    snapshot = run.get("supply_source") if run else None
    if not snapshot or snapshot["digest"] != payload.source_digest:
        raise ProductWorkError("候选缺少原运行固定的供应资料")
    try:
        current = source_state(c, finding.tenant_id, finding.project_id, payload.selection)
    except (LookupError, ValueError) as error:
        raise ProductWorkError("原供应资料当前不可用，请重新整理") from error
    if current["digest"] != payload.source_digest:
        raise ProductWorkError("供应、工装或排程依据已变化，请按当前资料重新准备")
    validate_assessment(payload.assessment, snapshot)
    if payload.assessment.disposition != "proposal":
        raise ProductWorkError("资料不足结果不能转为工作任务")
    if {c.key for c in payload.review.choices} != {o.key for o in payload.assessment.options}:
        raise ProductWorkError("每项原方案都须记录采用或不采用理由")
    context = review_context(c, finding.tenant_id, finding.project_id)
    eligible = {str(r["id"]) for r in context["members"]}
    stages = {str(r["id"]) for r in context["stages"]}
    for choice in payload.review.choices:
        if choice.disposition == "adopt":
            if str(choice.owner_user_id) not in eligible:
                raise ProductWorkError("所选负责人当前不是有效内部项目成员")
            if choice.stage_id is not None and str(choice.stage_id) not in stages:
                raise ProductWorkError("所选阶段不属于本项目")
            if choice.due_date is None or choice.due_date < date.today():
                raise ProductWorkError("目标日期已过，请重新核对")
    return dict(snapshot)


def apply_package(
    c: Connection,
    *,
    finding: FindingRecord,
    payload: SupplierRecoveryPayload,
    actor_user_id: UUID,
    applied_at: datetime,
) -> UUID:
    from app.domain.tasks import TaskDraft, TaskService

    authorize(c, finding, actor_user_id)
    snapshot = validate_review(c, finding, payload)
    assert payload.review is not None
    a = tables.supplier_recovery_applications
    if c.execute(
        select(a.c.id).where(
            a.c.tenant_id == finding.tenant_id,
            a.c.project_id == finding.project_id,
            a.c.source_digest == payload.source_digest,
        )
    ).scalar_one_or_none():
        raise ProductWorkError("相同供应依据已建立工作，请继续原任务并核对实际恢复结果")
    identity = uuid4()
    c.execute(
        a.insert().values(
            id=identity,
            tenant_id=finding.tenant_id,
            project_id=finding.project_id,
            finding_id=finding.id,
            run_id=finding.run_id,
            source_digest=payload.source_digest,
            source_snapshot=snapshot,
            review=payload.review.model_dump(mode="json"),
            created_by_user_id=actor_user_id,
            created_at=applied_at,
        )
    )
    proposed = {o.key: o for o in payload.assessment.options}
    for choice in payload.review.choices:
        if choice.disposition != "adopt":
            continue
        option = proposed[choice.key]
        target_labels = [payload.reference_labels.get(k, k) for k in option.target_reference_ids]
        output = (
            f"验证要求：{choice.verification}\n完成判据：{choice.completion_criteria}\n"
            f"缺项处理：{choice.missing_resolution}"
        )
        task = TaskService(c.engine).create(
            tenant_id=finding.tenant_id,
            project_id=finding.project_id,
            actor_user_id=actor_user_id,
            connection=c,
            draft=TaskDraft(
                stage_id=choice.stage_id,
                parent_task_id=None,
                assignee_user_id=choice.owner_user_id,
                title=("供应恢复：" + choice.description)[:512],
                description=(
                    f"{choice.description}\n实际对象：{'；'.join(target_labels)}\n采用依据：{choice.reason}\n"
                    f"应用范围及限制：{payload.review.scope_and_limits}\n"
                    f"原建议及裁决：/ai-review?finding={finding.id}\n"
                    "完成本任务后仍须在原业务登记实际到货、验证、拆借授权或工装可用证据。"
                ),
                priority="medium",
                start_date=None,
                due_date=choice.due_date,
                dependency_task_ids=(),
                expected_output=output,
            ),
        )
        c.execute(
            tables.supplier_recovery_items.insert().values(
                id=uuid4(),
                tenant_id=finding.tenant_id,
                project_id=finding.project_id,
                application_id=identity,
                proposal_key=choice.key,
                task_id=task.id,
            )
        )
    EventAuditWriter(
        c, tenant_id=finding.tenant_id, project_id=finding.project_id, actor_user_id=actor_user_id
    ).record(
        EventDraft(
            event_id=f"supplier-recovery:{identity}",
            event_type="SUPPLIER_RECOVERY_APPLIED",
            source="supplier_service",
            entity_id=identity,
            occurred_at=applied_at,
            payload={"finding_id": str(finding.id), "application_id": str(identity)},
        ),
        AuditDraft(
            action="supplier.recovery.applied",
            after_snapshot={
                "application_id": str(identity),
                "finding_id": str(finding.id),
                "source_digest": payload.source_digest,
            },
        ),
    )
    return identity


def applications(c: Connection, tenant: UUID, project: UUID, finding_id: UUID) -> dict[str, Any]:
    a, i, t, u = (
        tables.supplier_recovery_applications,
        tables.supplier_recovery_items,
        tables.tasks,
        tables.users,
    )
    app = (
        c.execute(
            select(a).where(
                a.c.tenant_id == tenant, a.c.project_id == project, a.c.finding_id == finding_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if app is None:
        return {"application": None, "items": []}
    items = (
        c.execute(
            select(
                i.c.id.label("item_id"),
                i.c.proposal_key,
                t.c.id.label("task_id"),
                t.c.title,
                t.c.status,
                t.c.assignee_user_id,
                t.c.due_date,
                t.c.expected_output,
                u.c.display_name.label("owner_name"),
            )
            .join(
                t,
                (t.c.tenant_id == i.c.tenant_id)
                & (t.c.project_id == i.c.project_id)
                & (t.c.id == i.c.task_id),
            )
            .outerjoin(u, (u.c.tenant_id == t.c.tenant_id) & (u.c.id == t.c.assignee_user_id))
            .where(
                i.c.tenant_id == tenant, i.c.project_id == project, i.c.application_id == app["id"]
            )
            .order_by(i.c.proposal_key)
        )
        .mappings()
        .all()
    )
    return {
        "application": _plain(
            {
                k: app[k]
                for k in (
                    "id",
                    "finding_id",
                    "source_digest",
                    "review",
                    "created_at",
                    "created_by_user_id",
                )
            }
        ),
        "items": [_plain(row) for row in items],
    }
