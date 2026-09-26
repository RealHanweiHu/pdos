"""Human-reviewed quality Findings apply to real investigation Tasks or CAPA actions."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, select

from app.auth.roles import Action
from app.contracts.quality_work_package import QualityAssessment
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

if TYPE_CHECKING:
    from app.domain.findings import FindingRecord


class WorkChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str
    disposition: Literal["adopt", "exclude"]
    reason: str = Field(min_length=1, max_length=4000)
    description: str = Field(default="", max_length=4000)
    expected_evidence: str = Field(default="", max_length=4000)
    owner_user_id: UUID | None = None
    due_date: date | None = None

    @model_validator(mode="after")
    def complete(self) -> WorkChoice:
        if self.disposition == "adopt" and (
            not self.description
            or not self.expected_evidence
            or self.owner_user_id is None
            or self.due_date is None
        ):
            raise ValueError("采用工作须有具体内容、实际负责人、日期与证据要求")
        return self


class QualityReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=4000)
    scope_and_limits: str = Field(min_length=1, max_length=4000)
    choices: list[WorkChoice] = Field(min_length=1, max_length=30)
    verification_criteria: str = Field(default="", max_length=4000)
    verification_method_scope: str = Field(default="", max_length=4000)
    minimum_observation_days: int | None = Field(default=None, strict=True, ge=1, le=3650)

    @model_validator(mode="after")
    def choices_complete(self) -> QualityReview:
        if len({c.key for c in self.choices}) != len(self.choices):
            raise ValueError("每项建议只核对一次")
        if not any(c.disposition == "adopt" for c in self.choices):
            raise ValueError("全部不采用时请填写理由并拒绝候选")
        return self


class QualityWorkPackagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ncr_id: UUID
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    assessment: QualityAssessment
    review_context: dict[str, Any] = Field(default_factory=dict)
    review: QualityReview | None = None
    details_confirmed: bool = False


def members(c: Connection, tenant: UUID, project: UUID) -> list[dict[str, Any]]:
    u, m = tables.users, tables.project_members
    return [
        {"id": str(r.id), "name": r.display_name}
        for r in c.execute(
            select(u.c.id, u.c.display_name)
            .join(m, (m.c.tenant_id == u.c.tenant_id) & (m.c.user_id == u.c.id))
            .where(
                u.c.tenant_id == tenant,
                m.c.project_id == project,
                u.c.is_active.is_(True),
                u.c.role.not_in(["supplier", "customer"]),
            )
            .order_by(u.c.display_name, u.c.id)
        )
    ]


def authorize(c: Connection, finding: FindingRecord, actor: UUID, phase: str) -> None:
    from app.domain.findings import FindingService

    for action in (
        Action.QUALITY_VIEW,
        Action.CAPA_EXECUTE,
        *([Action.WORK_ITEM_EDIT] if phase == "investigation" else []),
    ):
        FindingService._authorize_user(
            c,
            tenant_id=finding.tenant_id,
            project_id=finding.project_id,
            user_id=actor,
            action=action,
        )


def validate_review(
    c: Connection, finding: FindingRecord, payload: QualityWorkPackagePayload
) -> dict[str, Any]:
    from app.ai.quality_preparation import RUN_VERSION, source_state, validate_assessment
    from app.domain.quality_operations import Evidence

    if payload.review is None or not payload.details_confirmed:
        raise ProductWorkError("请核对原值、调查或措施、具名责任时间及后续验证要求")
    original = payload.model_dump(mode="json", exclude={"review", "details_confirmed"})
    if any(finding.proposed_payload.get(k) != value for k, value in original.items()):
        raise ProductWorkError("原建议和证据上下文不可改写，请在人工核对栏说明调整")
    run = (
        c.execute(
            select(tables.agent_runs).where(
                tables.agent_runs.c.tenant_id == finding.tenant_id,
                tables.agent_runs.c.project_id == finding.project_id,
                tables.agent_runs.c.id == finding.run_id,
                tables.agent_runs.c.context_version == RUN_VERSION,
            )
        )
        .mappings()
        .one_or_none()
    )
    if run is None or "quality_source" not in run["run_context"]:
        raise ProductWorkError("候选缺少固定的品质准备运行及原始资料")
    snapshot: dict[str, Any] = run["run_context"]["quality_source"]
    selections = [
        Evidence.model_validate({k: r[k] for k in Evidence.model_fields})
        for r in snapshot["source_values"]
    ]
    current = source_state(c, finding.tenant_id, finding.project_id, payload.ncr_id, selections)
    if current["digest"] != payload.source_digest or snapshot["digest"] != payload.source_digest:
        raise ProductWorkError("NCR、调查任务或质量依据已变化，请按当前资料重新准备")
    validate_assessment(payload.assessment, snapshot)
    if payload.assessment.disposition != "proposal":
        raise ProductWorkError("资料不足结果不能作为业务应用候选")
    proposed_keys = {w.key for w in payload.assessment.work}
    if {w.key for w in payload.review.choices} != proposed_keys:
        raise ProductWorkError("每项建议均须记录采用或不采用及实际理由")
    eligible = {r["id"] for r in members(c, finding.tenant_id, finding.project_id)}
    for item in payload.review.choices:
        if item.disposition == "adopt":
            if str(item.owner_user_id) not in eligible:
                raise ProductWorkError("所选负责人已无有效项目成员资格")
            if item.due_date is None or item.due_date < date.today():
                raise ProductWorkError("目标日期已过，请重新准备并核对接受")
    if payload.assessment.phase == "actions" and (
        not payload.review.verification_criteria
        or not payload.review.verification_method_scope
        or payload.review.minimum_observation_days is None
    ):
        raise ProductWorkError("整改工作须补齐实际有效性判据、方法范围和观察时长")
    return snapshot


def apply_package(
    c: Connection,
    *,
    finding: FindingRecord,
    payload: QualityWorkPackagePayload,
    actor_user_id: UUID,
    applied_at: datetime,
) -> UUID:
    from app.domain.capa_actions import CapaActionDraft, CapaActionService
    from app.domain.tasks import TaskDraft, TaskService

    authorize(c, finding, actor_user_id, payload.assessment.phase)
    snapshot = validate_review(c, finding, payload)
    assert payload.review is not None
    table = tables.quality_work_package_applications
    prior = c.execute(
        select(table.c.id).where(
            table.c.tenant_id == finding.tenant_id,
            table.c.project_id == finding.project_id,
            table.c.ncr_id == payload.ncr_id,
            table.c.source_digest == payload.source_digest,
        )
    ).scalar_one_or_none()
    if prior:
        raise ProductWorkError("相同品质依据已转入实际工作，请在原任务或措施继续办理")
    id = uuid4()
    c.execute(
        table.insert().values(
            id=id,
            tenant_id=finding.tenant_id,
            project_id=finding.project_id,
            ncr_id=payload.ncr_id,
            finding_id=finding.id,
            run_id=finding.run_id,
            source_digest=payload.source_digest,
            phase=payload.assessment.phase,
            review=payload.review.model_dump(mode="json"),
            source_snapshot=snapshot,
            created_by_user_id=actor_user_id,
            created_at=applied_at,
        )
    )
    proposed = {w.key: w for w in payload.assessment.work}
    for choice in payload.review.choices:
        if choice.disposition != "adopt":
            continue
        work = proposed[choice.key]
        assert choice.owner_user_id is not None and choice.due_date is not None
        task_id = action_id = None
        common: dict[str, Any] = {
            "tenant_id": finding.tenant_id,
            "project_id": finding.project_id,
            "actor_user_id": actor_user_id,
            "connection": c,
        }
        if work.kind == "investigation":
            task = TaskService(c.engine).create(
                **common,
                draft=TaskDraft(
                    stage_id=None,
                    parent_task_id=None,
                    assignee_user_id=choice.owner_user_id,
                    title=("质量调查：" + choice.description)[:512],
                    description=(
                        f"原 NCR：{snapshot['state']['ncr']['code']}\n{choice.description}\n"
                        f"采用依据：{choice.reason}\n本任务仅收集调查证据；"
                        "完成不代表根因获批或 NCR 关闭。"
                    ),
                    priority="medium",
                    start_date=None,
                    due_date=choice.due_date,
                    dependency_task_ids=(),
                    expected_output=choice.expected_evidence,
                ),
            )
            task_id = task.id
        else:
            action = CapaActionService(c.engine).create(
                **common,
                ncr_id=payload.ncr_id,
                draft=CapaActionDraft(
                    owner_user_id=choice.owner_user_id,
                    action_type=work.kind,
                    description=f"{choice.description}\n完成证据要求：{choice.expected_evidence}\n采用依据：{choice.reason}",
                    due_date=choice.due_date,
                ),
            )
            action_id = action.id
        c.execute(
            tables.quality_work_package_items.insert().values(
                id=uuid4(),
                tenant_id=finding.tenant_id,
                project_id=finding.project_id,
                application_id=id,
                proposal_key=choice.key,
                task_id=task_id,
                capa_action_id=action_id,
            )
        )
    EventAuditWriter(
        c, tenant_id=finding.tenant_id, project_id=finding.project_id, actor_user_id=actor_user_id
    ).record(
        EventDraft(
            event_id=f"quality-work-package:{id}",
            event_type="QUALITY_WORK_PACKAGE_APPLIED",
            source="quality_service",
            entity_id=id,
            payload={"ncr_id": str(payload.ncr_id), "finding_id": str(finding.id)},
        ),
        AuditDraft(
            action="quality.work_package.applied",
            after_snapshot={
                "application_id": str(id),
                "finding_id": str(finding.id),
                "phase": payload.assessment.phase,
            },
        ),
    )
    return id


def applications(
    c: Connection, tenant: UUID, project: UUID, ncr: UUID, offset: int = 0
) -> dict[str, Any]:
    app, work = tables.quality_work_package_applications, tables.quality_work_package_items
    records = (
        c.execute(
            select(app)
            .where(app.c.tenant_id == tenant, app.c.project_id == project, app.c.ncr_id == ncr)
            .order_by(app.c.created_at.desc(), app.c.id.desc())
            .offset(offset)
            .limit(21)
        )
        .mappings()
        .all()
    )
    result = []
    for row in records[:20]:
        items = []
        for item in c.execute(
            select(work)
            .where(work.c.application_id == row["id"], work.c.tenant_id == tenant)
            .order_by(work.c.proposal_key)
        ).mappings():
            t = tables.tasks if item["task_id"] else tables.capa_actions
            actual = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == tenant,
                        t.c.project_id == project,
                        t.c.id == (item["task_id"] or item["capa_action_id"]),
                    )
                )
                .mappings()
                .one()
            )
            items.append({**dict(item), "current": dict(actual)})
        result.append({**{k: v for k, v in row.items() if k != "source_snapshot"}, "items": items})
    people = {row["created_by_user_id"] for row in records[:20]}
    for prepared in result:
        for choice in prepared["review"]["choices"]:
            if choice.get("owner_user_id"):
                people.add(UUID(choice["owner_user_id"]))
        for item in prepared["items"]:
            actual_owner = item["current"].get("owner_user_id") or item["current"].get(
                "assignee_user_id"
            )
            if actual_owner:
                people.add(UUID(str(actual_owner)))
    names = {
        str(r.id): r.display_name
        for r in c.execute(
            select(tables.users.c.id, tables.users.c.display_name).where(
                tables.users.c.tenant_id == tenant, tables.users.c.id.in_(people)
            )
        )
    }
    return _plain(
        {
            "items": result,
            "people": names,
            "next_offset": offset + 20 if len(records) > 20 else None,
        }
    )


def persist(
    c: Connection,
    *,
    row: Any,
    snapshot: dict[str, Any],
    output: QualityAssessment,
    invocation_id: UUID,
    created_at: datetime,
) -> UUID | None:
    """The preparation handler may persist only a pending Finding after an actual model call."""
    from app.ai.quality import FindingQualityService
    from app.ai.quality_preparation import RUN_VERSION, source_state, validate_assessment
    from app.ai.rollout_guard import require_live_finding
    from app.domain.findings import FINDING_PREFLIGHT_VERSION
    from app.domain.quality_operations import Evidence

    require_live_finding("quality_intelligence", "capa_work_package")
    if row["agent_key"] != "quality_intelligence" or row["context_version"] != RUN_VERSION:
        raise ProductWorkError("品质候选须来自固定版本的实际准备运行")
    if row["run_context"].get("quality_source") != snapshot:
        raise ProductWorkError("准备输入未固定在本次运行")
    invocation = c.execute(
        select(tables.model_invocations.c.id).where(
            tables.model_invocations.c.tenant_id == row["tenant_id"],
            tables.model_invocations.c.project_id == row["project_id"],
            tables.model_invocations.c.run_id == row["id"],
            tables.model_invocations.c.id == invocation_id,
            tables.model_invocations.c.agent_key == "quality_intelligence",
            tables.model_invocations.c.status == "succeeded",
        )
    ).first()
    if invocation is None:
        raise ProductWorkError("候选缺少实际成功的模型调用回执")
    selections = [
        Evidence.model_validate({k: r[k] for k in Evidence.model_fields})
        for r in snapshot["source_values"]
    ]
    current = source_state(
        c, row["tenant_id"], row["project_id"], UUID(snapshot["ncr_id"]), selections
    )
    if current["digest"] != snapshot["digest"]:
        raise ProductWorkError("生成期间原质量依据已有变化，请重新准备")
    validate_assessment(output, snapshot)
    if output.disposition == "insufficient_evidence":
        return None
    if not FindingQualityService.is_output_allowed_connection(
        c,
        tenant_id=row["tenant_id"],
        agent_key="quality_intelligence",
        finding_type="capa_work_package",
    ):
        raise ProductWorkError("品质工作包候选质量控制已收窄")
    origin = "quality-work-package:" + snapshot["digest"]
    prior = c.execute(
        select(tables.findings.c.id).where(
            tables.findings.c.tenant_id == row["tenant_id"],
            tables.findings.c.run_id == row["id"],
            tables.findings.c.origin_key == origin,
        )
    ).scalar_one_or_none()
    if prior:
        return UUID(str(prior))
    payload = QualityWorkPackagePayload(
        ncr_id=UUID(snapshot["ncr_id"]),
        source_digest=snapshot["digest"],
        assessment=output,
        review_context={
            "ncr": snapshot["state"]["ncr"],
            "members": members(c, row["tenant_id"], row["project_id"]),
            "reference_labels": {
                r["reference_id"]: r["label"] for r in snapshot["model_context"]["references"]
            },
        },
    )
    id = uuid4()
    c.execute(
        tables.findings.insert().values(
            id=id,
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            run_id=row["id"],
            model_invocation_id=invocation_id,
            agent_key="quality_intelligence",
            finding_type="capa_work_package",
            origin_key=origin,
            status="pending_review",
            title="品质调查与整改工作包待审稿",
            summary="核对事实、假设与实际执行要求；" + output.coverage_limits,
            proposed_payload=payload.model_dump(mode="json"),
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
            finding_id=id,
            action="created",
            actor_user_id=None,
            to_status="pending_review",
            detail={"source": "quality_sources", "ncr_id": snapshot["ncr_id"]},
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
            event_id=f"ai-finding:{id}:created",
            event_type="AI_FINDING_CREATED",
            source="ai_runtime",
            entity_id=id,
            occurred_at=created_at,
            payload={"finding_id": str(id), "agent_run_id": str(row["id"])},
        ),
        AuditDraft(
            action="finding.create_quality_work_package",
            after_snapshot={"finding_id": str(id)},
            context={"ncr_id": snapshot["ncr_id"], "model_invocation_id": str(invocation_id)},
        ),
    )
    return id
