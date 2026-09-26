"""Typed test-plan proposals and human-only, append-only revision application."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)
from sqlalchemy import Connection, select

from app.db.schema import tables
from app.domain.npi_execution import NpiExecutionService, _snapshot
from app.domain.test_plan_sources import PlanSourceError, resolve_sources, selections_for
from app.domain.test_templates import instantiate_cases

if TYPE_CHECKING:
    from app.domain.findings import FindingRecord


class TestPlanChangeError(ValueError):
    pass


class PlanItemDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=512)
    category: str = Field(min_length=1, max_length=64)
    method: str = Field(max_length=10_000)
    acceptance_criteria: str = Field(max_length=10_000)
    applicability: str = Field(max_length=2000)
    evidence_requirements: str = Field(max_length=2000)
    required: bool = True


class ExecutionPreparationProposal(BaseModel):
    """Reviewed preparation requirements, separate from an actual task assignment."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    conditions: str = Field(default="", max_length=10_000)
    environment: str = Field(default="", max_length=2000)
    required_sample_count: int | None = Field(default=None, gt=0, le=100000)
    responsible_role: str = Field(default="", max_length=128)
    expected_output: str = Field(default="", max_length=10_000)
    resource_requirements: list[str] = Field(default_factory=list, max_length=100)
    unresolved: list[str] = Field(default_factory=list, max_length=20)
    basis: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def valid_notes(self) -> ExecutionPreparationProposal:
        if any(
            not item.strip() or len(item) > 2000
            for item in self.resource_requirements + self.unresolved
        ):
            raise ValueError("资源要求和待补项须为非空文字，单项不超过2000字")
        if not self.unresolved and not all(
            (
                self.conditions,
                self.environment,
                self.required_sample_count,
                self.responsible_role,
                self.expected_output,
            )
        ):
            raise ValueError("执行准备仍有未知字段，请在待补条件中说明")
        return self


class ReviewedPlanItemDraft(PlanItemDraft):
    # Keep the qualified v5 model response schema unchanged. These fields
    # belong to the human review contract until model-version qualification.
    execution_preparation: ExecutionPreparationProposal | None = None

    @model_serializer(mode="wrap")
    def serialize_reviewed_item(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        value: dict[str, Any] = handler(self)
        if self.execution_preparation is None:
            value.pop("execution_preparation", None)
        return value


class ProposalReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reference_id: str = Field(min_length=1, max_length=160)
    quote: str = Field(min_length=1, max_length=30_000)


class TestItemChangeFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation: Literal["add", "modify", "exclude"]
    target_key: str | None = Field(default=None, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)
    after: PlanItemDraft | None = None
    unresolved: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def valid_operation(self) -> TestItemChangeFields:
        if (self.operation == "add") != (self.target_key is None):
            raise ValueError("新增不得指定原项，修改或不适用必须指定原项")
        if (self.operation == "exclude") != (self.after is None):
            raise ValueError("不适用只需理由，新增或修改必须提供建议内容")
        if any(not value.strip() or len(value) > 2000 for value in self.unresolved):
            raise ValueError("待补条件必须为有效文本")
        return self


class TestItemChange(TestItemChangeFields):
    after: ReviewedPlanItemDraft | None = None
    references: list[ProposalReference] = Field(min_length=1, max_length=20)


class ModelTestItemChange(TestItemChangeFields):
    reference_ids: list[str] = Field(min_length=1, max_length=20)


class TestPlanModelAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    summary: str = Field(min_length=1, max_length=2000)
    changes: list[ModelTestItemChange] = Field(max_length=60)
    questions: list[str] = Field(max_length=20)

    def bind_sources(self, sources: dict[str, str]) -> TestPlanAssessment:
        return bind_source_changes(self.changes, sources, self.summary, self.questions)


class WorkPackageModelTestItemChange(ModelTestItemChange):
    after: ReviewedPlanItemDraft | None = None

    @model_validator(mode="after")
    def includes_execution_preparation(self) -> WorkPackageModelTestItemChange:
        if self.after is not None and self.after.execution_preparation is None:
            raise ValueError("新版测试建议须附执行准备；未知项留空并列出待补条件")
        return self


class WorkPackageTestPlanModelAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    summary: str = Field(min_length=1, max_length=2000)
    changes: list[WorkPackageModelTestItemChange] = Field(max_length=60)
    questions: list[str] = Field(max_length=20)

    def bind_sources(self, sources: dict[str, str]) -> TestPlanAssessment:
        return bind_source_changes(self.changes, sources, self.summary, self.questions)


def bind_source_changes(
    source_changes: Sequence[ModelTestItemChange],
    sources: dict[str, str],
    summary: str,
    questions: list[str],
) -> TestPlanAssessment:
    changes = []
    for change in source_changes:
        if len(set(change.reference_ids)) != len(change.reference_ids):
            raise TestPlanChangeError("同一测试项引用来源重复")
        if any(ref not in sources for ref in change.reference_ids):
            raise TestPlanChangeError("建议引用不存在或超出当前范围")
        changes.append(
            TestItemChange(
                **change.model_dump(exclude={"reference_ids"}),
                references=[
                    ProposalReference(reference_id=ref, quote=sources[ref])
                    for ref in change.reference_ids
                ],
            )
        )
    return TestPlanAssessment(summary=summary, changes=changes, questions=questions)


class TestPlanAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    summary: str = Field(min_length=1, max_length=2000)
    changes: list[TestItemChange] = Field(max_length=60)
    questions: list[str] = Field(max_length=20)

    @model_validator(mode="after")
    def valid_questions(self) -> TestPlanAssessment:
        if any(not q.strip() or len(q) > 2000 for q in self.questions):
            raise ValueError("追问内容无效")
        return self


class TestPlanChangePayload(TestPlanAssessment):
    base_plan_id: UUID
    base_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    messages: list[str] = Field(min_length=1, max_length=12)
    base_items: list[dict[str, Any]] = Field(max_length=500)
    source_snapshots: list[dict[str, Any]] = Field(default_factory=list, max_length=8)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def plan_state(
    connection: Connection, *, tenant_id: UUID, project_id: UUID, plan_id: UUID
) -> dict[str, Any]:
    project = NpiExecutionService._project(
        connection, tenant_id=tenant_id, project_id=project_id, lock=True
    )
    if project["status"] in {"completed", "archived"}:
        raise TestPlanChangeError("项目已结束，不能修订测试计划")
    plan = dict(
        NpiExecutionService._row(
            connection,
            tables.test_plans,
            tenant_id=tenant_id,
            project_id=project_id,
            record_id=plan_id,
            lock=True,
        )
    )
    if not plan["template_snapshot"]:
        raise TestPlanChangeError("请先选择测试模板")
    if connection.execute(
        select(tables.test_plans.c.id).where(
            tables.test_plans.c.tenant_id == tenant_id,
            tables.test_plans.c.parent_plan_id == plan_id,
        )
    ).first():
        raise TestPlanChangeError("此计划已有修订版本，请在最新版本上继续")
    cases = [
        dict(row)
        for row in connection.execute(
            select(tables.test_cases)
            .where(
                tables.test_cases.c.tenant_id == tenant_id,
                tables.test_cases.c.project_id == project_id,
                tables.test_cases.c.plan_id == plan_id,
            )
            .order_by(tables.test_cases.c.id)
        ).mappings()
    ]
    expected = {i["key"] for i in plan["template_snapshot"]["items"] if i["applicable"]}
    if {c["template_item_key"] for c in cases} != expected:
        raise TestPlanChangeError("计划存在模板外用例或绑定缺项，请先核对，避免修订时遗漏")
    runs = [
        dict(row)
        for row in connection.execute(
            select(tables.test_runs)
            .where(
                tables.test_runs.c.tenant_id == tenant_id,
                tables.test_runs.c.project_id == project_id,
                tables.test_runs.c.test_case_id.in_([c["id"] for c in cases]),
            )
            .order_by(tables.test_runs.c.id)
        ).mappings()
    ]
    reports = [
        dict(row)
        for row in connection.execute(
            select(tables.test_reports)
            .where(
                tables.test_reports.c.tenant_id == tenant_id,
                tables.test_reports.c.project_id == project_id,
                tables.test_reports.c.plan_id == plan_id,
            )
            .order_by(tables.test_reports.c.id)
        ).mappings()
    ]
    # Results and reports are fingerprinted locally, never sent as model context.
    return {"plan": plan, "cases": cases, "runs": runs, "reports": reports}


def proposal_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = copy.deepcopy(state["plan"]["template_snapshot"]["items"])
    cases = {case["template_item_key"]: case for case in state["cases"]}
    for item in items:
        if item["key"] in cases:
            for key in ("title", "category", "method", "acceptance_criteria"):
                item[key] = cases[item["key"]][key]
    return items


def proposal_references(
    state: dict[str, Any], messages: list[str], source_snapshots: list[dict[str, Any]] | None = None
) -> dict[str, str]:
    refs = {f"message:{i + 1}": message for i, message in enumerate(messages)}
    for item in proposal_items(state):
        refs[f"item:{item['key']}"] = "\n".join(
            str(item.get(k) or "")
            for k in ("title", "method", "acceptance_criteria", "applicability", "exclusion_reason")
        )
    refs.update({s["reference_id"]: s["excerpt"] for s in source_snapshots or []})
    return refs


def validate_changes(
    assessment: TestPlanAssessment,
    *,
    state: dict[str, Any],
    messages: list[str],
    ready: bool,
    source_snapshots: list[dict[str, Any]] | None = None,
) -> None:
    if ready and (assessment.questions or not assessment.changes):
        raise TestPlanChangeError("请先补齐待确认条件并选择至少一项变更")
    items = {i["key"]: i for i in proposal_items(state)}
    references = proposal_references(state, messages, source_snapshots)
    targeted: set[str] = set()
    titles = {k: " ".join(i["title"].split()).casefold() for k, i in items.items()}
    for index, change in enumerate(assessment.changes):
        for ref in change.references:
            if ref.reference_id not in references or ref.quote not in references[ref.reference_id]:
                raise TestPlanChangeError("建议引用不存在或原文不匹配")
        if not any(ref.reference_id.startswith("message:") for ref in change.references):
            raise TestPlanChangeError("每项变更须引用本次用户要求")
        if change.target_key is not None:
            if change.target_key not in items or change.target_key in targeted:
                raise TestPlanChangeError("修改目标不存在或同一项重复修改")
            targeted.add(change.target_key)
        if ready and change.unresolved:
            raise TestPlanChangeError("测试项仍有待补条件")
        if change.after:
            if ready and not all(
                (
                    change.after.method,
                    change.after.acceptance_criteria,
                    change.after.applicability,
                    change.after.evidence_requirements,
                )
            ):
                raise TestPlanChangeError("请补充方法、判定依据、适用条件及证据要求")
            if (
                change.target_key
                and items[change.target_key]["required"]
                and not change.after.required
            ):
                raise TestPlanChangeError("本入口不能降低原必测项要求")
            titles[change.target_key or f"new:{index}"] = " ".join(
                change.after.title.split()
            ).casefold()
        elif change.target_key and not items[change.target_key]["applicable"]:
            raise TestPlanChangeError("该项已经不适用，无需重复排除")
        if ready and change.operation == "exclude":
            case = next(
                (c for c in state["cases"] if c["template_item_key"] == change.target_key), None
            )
            if case and (
                case["status"] != "planned"
                or any(r["test_case_id"] == case["id"] for r in state["runs"])
            ):
                raise TestPlanChangeError("已有测试决策的项目不能在此排除，请走工程变更流程")
    applicable = {key for key, item in items.items() if item["applicable"] and item["required"]}
    for index, change in enumerate(assessment.changes):
        if change.operation == "exclude":
            applicable.discard(change.target_key)
        elif change.after and change.after.required:
            applicable.add(change.target_key or f"new:{index}")
    if ready and not applicable:
        raise TestPlanChangeError("修订后至少保留一个适用必测项")
    if len(set(titles.values())) != len(titles):
        raise TestPlanChangeError("存在同名测试项，请修改原项或调整名称以明确差异")


def validate_finding_change(
    connection: Connection,
    finding: FindingRecord,
    payload: TestPlanChangePayload,
) -> dict[str, Any]:
    original = TestPlanChangePayload.model_validate(finding.proposed_payload)
    if (payload.base_plan_id, payload.base_digest) != (original.base_plan_id, original.base_digest):
        raise TestPlanChangeError("不能修改建议绑定的原计划或版本")
    if payload.messages != original.messages or payload.base_items != original.base_items:
        raise TestPlanChangeError("不能修改建议的原始对话或基线")
    if payload.source_snapshots != original.source_snapshots:
        raise TestPlanChangeError("不能修改建议绑定的来源原文或版本")
    run_context = connection.execute(
        select(tables.agent_runs.c.run_context).where(
            tables.agent_runs.c.tenant_id == finding.tenant_id,
            tables.agent_runs.c.project_id == finding.project_id,
            tables.agent_runs.c.id == finding.run_id,
        )
    ).scalar_one()
    if run_context.get("superseded_by"):
        raise TestPlanChangeError("此建议已有新的对话修订，请审阅最新建议")
    if run_context.get("base_digest") != payload.base_digest:
        raise TestPlanChangeError("建议与冻结上下文不一致")
    state = plan_state(
        connection,
        tenant_id=finding.tenant_id,
        project_id=finding.project_id,
        plan_id=payload.base_plan_id,
    )
    if digest(state) != payload.base_digest:
        raise TestPlanChangeError("原计划或用例已变化，请重新生成差异并审阅")
    try:
        current_sources = resolve_sources(
            connection,
            tenant_id=finding.tenant_id,
            project_id=finding.project_id,
            selections=selections_for(payload.source_snapshots),
        )
    except PlanSourceError as error:
        raise TestPlanChangeError(str(error)) from error
    if current_sources != payload.source_snapshots or current_sources != run_context.get(
        "source_snapshots", []
    ):
        raise TestPlanChangeError("建议来源与冻结上下文不一致")
    validate_changes(
        payload,
        state=state,
        messages=run_context["messages"],
        ready=True,
        source_snapshots=current_sources,
    )
    return state


def apply_test_plan_change(
    connection: Connection,
    *,
    finding: FindingRecord,
    payload: TestPlanChangePayload,
    actor_user_id: UUID,
    applied_at: datetime,
) -> UUID:
    state = validate_finding_change(connection, finding, payload)
    source = state["plan"]
    baseline = copy.deepcopy(source["template_snapshot"])
    # Preserve any human method/title changes that happened before generation.
    for case in state["cases"]:
        item = next(i for i in baseline["items"] if i["key"] == case["template_item_key"])
        for field in ("title", "category", "method", "acceptance_criteria"):
            item[field] = case[field]
        if case["specification_id"] is not None:
            item["specification_id"] = str(case["specification_id"])
        else:
            item.pop("specification_id", None)
    for change in payload.changes:
        if change.operation == "add":
            item = {"key": f"project-{uuid4()}", "applicable": True, "exclusion_reason": None}
            baseline["items"].append(item)
        else:
            item = next(i for i in baseline["items"] if i["key"] == change.target_key)
        if change.after:
            item.pop("execution_preparation", None)
            item.pop("specification_id", None)  # Changed methods require a fresh human link review.
            item.update(change.after.model_dump())
            item.update(applicable=True, exclusion_reason=None)
        else:
            item.update(applicable=False, exclusion_reason=change.reason)
        item["project_change"] = change.model_dump(mode="json")
        item["source_finding_id"] = str(finding.id)
    if not any(i["required"] and i["applicable"] for i in baseline["items"]):
        raise TestPlanChangeError("修订后至少保留一个适用必测项")
    baseline.update(
        plan_revision=baseline.get("plan_revision", 1) + 1,
        confirmed_by_user_id=str(actor_user_id),
        confirmed_at=applied_at.isoformat(),
        reviewed_by_user_id=str(finding.reviewed_by_user_id),
        reviewed_at=finding.reviewed_at.isoformat() if finding.reviewed_at else None,
        parent_plan_id=str(source["id"]),
        source_finding_id=str(finding.id),
        proposal_sources=payload.source_snapshots,
    )
    plan_id = uuid4()
    values = {
        key: source[key]
        for key in (
            "tenant_id",
            "project_id",
            "workflow_id",
            "stage_id",
            "phase",
            "scope",
            "sample_size",
        )
    }
    values.update(
        id=plan_id,
        parent_plan_id=source["id"],
        source_finding_id=finding.id,
        title=source["title"],
        created_by_user_id=actor_user_id,
        status="draft",
        template_snapshot=baseline,
        created_at=applied_at,
        updated_at=applied_at,
    )
    connection.execute(tables.test_plans.insert().values(**values))
    instantiate_cases(
        connection,
        tenant_id=finding.tenant_id,
        project_id=finding.project_id,
        plan_id=plan_id,
        actor_user_id=actor_user_id,
        snapshot=baseline,
    )
    NpiExecutionService._record_change(
        connection,
        tenant_id=finding.tenant_id,
        project_id=finding.project_id,
        actor_user_id=actor_user_id,
        record_id=plan_id,
        record_type="test_plan",
        action="revised",
        before=None,
        after=_snapshot(values),
    )
    return plan_id
