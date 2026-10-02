"""Typed event-Issue suggestions over bounded, server-selected business evidence.

Callers pass the internal result of read_event_source, not an HTTP supplied
snapshot. This module neither proves read permission nor grants write authority.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.executor import PromptFile
from app.domain.product_workspace import digest

KEY = "quality_intelligence.event_issue"
PURPOSE = "event_issue"
OPERATION = "event.issue.create"
CONTEXT_VERSION = "event-issue-context-v1"
SNAPSHOT_VERSION = "event-issue-source-v1"
MAX_CONTEXT_BYTES = 64_000
MAX_REFERENCE_CHARS = 16_000
MAX_REFERENCES = 120
PROMPT = PromptFile.model_validate_json(
    (Path(__file__).with_name("prompts") / "issue_event_v1.json").read_text()
)

Question = Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]


class IssueEventProposalError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reference_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_.]+$")
    exact_quote: str = Field(min_length=1, max_length=4000, pattern=r"\S")


class IssueEventProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    disposition: Literal["create_issue", "reuse_issue", "insufficient_evidence"]
    title: str | None = Field(default=None, min_length=1, max_length=512, pattern=r"\S")
    description: str | None = Field(default=None, min_length=1, max_length=16_000, pattern=r"\S")
    severity: Literal["low", "medium", "high", "critical"] | None = None
    existing_issue_id: UUID | None = None
    citations: tuple[Citation, ...] = Field(default=(), max_length=20)
    open_questions: tuple[Question, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def correct_disposition(self) -> Self:
        fields = (self.title, self.description, self.severity)
        if self.disposition == "create_issue":
            if any(value is None for value in fields) or self.existing_issue_id is not None:
                raise ValueError("新建建议须完整标题、说明和严重度，不能指定既有问题")
        elif any(value is not None for value in fields):
            raise ValueError("只有新建建议可以填写标题、说明和严重度")
        if (self.disposition == "reuse_issue") != (self.existing_issue_id is not None):
            raise ValueError("仅复用建议必须指定既有问题")
        if self.disposition == "insufficient_evidence":
            if not self.open_questions:
                raise ValueError("证据不足必须说明需要补充的资料")
        elif self.open_questions or not self.citations:
            raise ValueError("新建或复用须引用原依据，补证问题仅用于证据不足")
        keys = [(v.reference_id, v.exact_quote) for v in self.citations]
        if len(set(keys)) != len(keys):
            raise ValueError("请勿重复相同引用")
        return self


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IssueEventProposalError("source_incomplete", f"缺少可核对的{label}")
    return value


def _identity(value: Any, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as error:
        raise IssueEventProposalError("source_incomplete", f"{label}编号不可核对") from error


def _source(source: dict[str, Any]) -> dict[str, Any]:
    if source.get("source_status") != "current":
        raise IssueEventProposalError("source_not_current", "原来源已变化或不可用，请先重新核对")
    raw = _mapping(source.get("source"), "来源")
    if source.get("source_kind") not in {"test_failure", "material_exception"}:
        raise IssueEventProposalError("unsupported_source", "只支持原测试失败或物料异常")
    return raw


def _existing(source: dict[str, Any]) -> dict[str, Any] | None:
    value = source.get("existing_issue")
    if value is None:
        return None
    row = _mapping(value, "原问题")
    identity = _identity(row.get("id"), "原问题")
    snapshot = _mapping(row.get("snapshot"), "原问题当前正文")
    if _identity(snapshot.get("id"), "原问题正文") != identity:
        raise IssueEventProposalError("source_incomplete", "原问题编号与正文不一致")
    if snapshot.get("withdrawn_at") is not None:
        raise IssueEventProposalError(
            "existing_issue_withdrawn", "原问题已撤回，须具名核对来源关系"
        )
    if snapshot.get("status") not in {"open", "analysis", "action", "verification", "closed"}:
        raise IssueEventProposalError("source_incomplete", "原问题当前状态不可核对")
    return row


def _add(references: list[dict[str, str]], key: str, label: str, value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise IssueEventProposalError("source_incomplete", f"{label}不是原始文本")
    if not value.strip():
        return
    if len(value) > MAX_REFERENCE_CHARS or len(references) >= MAX_REFERENCES:
        raise IssueEventProposalError(
            "context_too_large", "原依据超出单次容量，请先整理来源；未截断内容"
        )
    references.append({"reference_id": key, "label": label, "excerpt": value})


def _number(value: Any, label: str) -> str:
    if isinstance(value, bool) or value is None:
        raise IssueEventProposalError("source_incomplete", f"{label}未知")
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise IssueEventProposalError("source_incomplete", f"{label}不是实际数值") from error
    if not number.is_finite():
        raise IssueEventProposalError("source_incomplete", f"{label}不是有限数值")
    return str(value)


def _test_context(raw: dict[str, Any], references: list[dict[str, str]]) -> dict[str, Any]:
    case = _mapping(raw.get("current_case"), "当前测试")
    original = _mapping(raw.get("original_result"), "原失败结果")
    if case.get("status") != "failed" or original.get("status") != "failed":
        raise IssueEventProposalError("source_not_current", "原失败与当前测试结果不一致")
    if raw.get("origin_kind") not in {"legacy_test_case", "test_run", "test_report_import"}:
        raise IssueEventProposalError("source_incomplete", "尚未核实失败对应的原测试记录")
    _add(references, "test.original.failure", "原登记测试结果", "原登记测试结果：失败")
    _add(references, "test.original.result_notes", "原失败说明", original.get("result_notes"))
    for key, label in (
        ("title", "测试名称"),
        ("acceptance_criteria", "原测试判据"),
        ("method", "原测试方法"),
    ):
        _add(references, f"test.case.{key}", label, case.get(key))
    metrics = original.get("metrics") or []
    if not isinstance(metrics, (list, tuple)) or len(metrics) > 100:
        raise IssueEventProposalError("context_too_large", "原实测指标超出单次容量或尚不可核对")
    for index, item in enumerate(metrics):
        metric = _mapping(item, "原实测指标")
        # These are actual business cells, not arbitrary nested JSON or identifiers.
        parts = []
        for key, label in (
            ("name", "指标"),
            ("value", "实测"),
            ("unit", "单位"),
            ("target", "目标"),
            ("verdict", "原判定"),
        ):
            value = metric.get(key)
            if value is None:
                continue
            if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                raise IssueEventProposalError("source_incomplete", "原实测指标字段不可核对")
            parts.append(f"{label}：{value}")
        _add(
            references, f"test.original.metric.{index}", f"原实测指标 {index + 1}", "；".join(parts)
        )
    return {"test_status": "failed", "origin_kind": raw["origin_kind"]}


def _material_context(raw: dict[str, Any], references: list[dict[str, str]]) -> dict[str, Any]:
    original = _mapping(raw.get("original_review"), "原异常核对")
    snapshot = _mapping(original.get("snapshot"), "原异常依据")
    original_basis = _mapping(snapshot.get("basis"), "原物料依据")
    current = _mapping(raw.get("current_assessment"), "当前供给核对")
    basis = _mapping(current.get("basis"), "当前物料依据")
    material = _mapping(original_basis.get("material"), "原物料缺口")
    current_material = _mapping(basis.get("material"), "当前物料缺口")
    if original.get("disposition") != "follow_up" or original.get("basis_digest") != current.get(
        "digest"
    ):
        raise IssueEventProposalError("source_not_current", "原物料异常尚未按当前供给具名核对")
    gap = _number(material.get("observed_on_hand_gap"), "原已登记范围现货缺口")
    current_gap = _number(current_material.get("observed_on_hand_gap"), "当前现货缺口")
    if Decimal(gap) <= 0 or Decimal(gap) != Decimal(current_gap):
        raise IssueEventProposalError("source_not_current", "当前资料没有与原核对一致的正缺口")
    required = _number(material.get("required"), "固定需求")
    reference = material.get("material_reference") or "物料引用待补"
    unit = material.get("unit") or "单位待补"
    if not isinstance(reference, str) or not isinstance(unit, str):
        raise IssueEventProposalError("source_incomplete", "原物料引用或单位不可核对")
    _add(
        references,
        "material.original.shortage",
        "原已具名核对的物料缺口",
        (f"物料：{reference}；已登记范围现货缺口：{gap} {unit}；固定需求：{required} {unit}"),
    )
    _add(references, "material.original.reason", "原异常核对说明", original.get("reason"))
    return {"review_disposition": "follow_up", "observed_on_hand_gap": current_gap}


def model_context(source: dict[str, Any]) -> dict[str, Any]:
    """Business fields only. Extra audit/identity/receipt JSON never reaches the model."""
    raw = _source(source)
    references: list[dict[str, str]] = []
    current_state = (
        _test_context(raw, references)
        if source["source_kind"] == "test_failure"
        else (_material_context(raw, references))
    )
    existing = _existing(source)
    if existing is not None:
        issue = existing["snapshot"]
        for key, label in (("title", "原问题标题"), ("description", "原问题说明")):
            _add(references, f"issue.current.{key}", label, issue.get(key))
        current_state["issue_status"] = issue.get("status")
    context = {
        "version": CONTEXT_VERSION,
        "question": "根据原测试失败或已具名确认的物料缺口，给出新建、复用或补证建议。",
        "source_kind": source["source_kind"],
        "current_state": current_state,
        "existing_issue_id": existing["id"] if existing else None,
        "references": references,
    }
    if len(json.dumps(context, ensure_ascii=False, sort_keys=True).encode()) > MAX_CONTEXT_BYTES:
        raise IssueEventProposalError(
            "context_too_large", "业务依据超过单次容量；未截断或省略已选字段"
        )
    return context


def source_snapshot(source: dict[str, Any]) -> dict[str, Any]:
    """Pin original event and current reader digest for before/after execution checks."""
    raw = _source(source)
    event = _mapping(raw.get("event"), "原事件")
    signature = source.get("source_digest")
    if (
        not isinstance(signature, str)
        or len(signature) != 64
        or any(char not in "0123456789abcdef" for char in signature)
    ):
        raise IssueEventProposalError("source_incomplete", "缺少原来源摘要")
    if (
        type(event.get("id")) is not int
        or event["id"] <= 0
        or any(
            source.get(key) != event.get(field)
            for key, field in (
                ("event_row_id", "id"),
                ("event_id", "event_id"),
                ("event_type", "event_type"),
            )
        )
    ):
        raise IssueEventProposalError("source_incomplete", "原事件身份与读取回执不一致")
    context = model_context(source)
    return {
        "version": SNAPSHOT_VERSION,
        "tenant_id": _identity(event.get("tenant_id"), "租户"),
        "project_id": _identity(event.get("project_id"), "项目"),
        "event_row_id": event["id"],
        "event_id": event["event_id"],
        "event_type": event["event_type"],
        "event_at": event.get("timestamp"),
        "entity_id": _identity(event.get("entity_id"), "原业务对象"),
        "source_kind": source["source_kind"],
        "source_key": raw.get("source_key"),
        "source_digest": signature,
        "existing_issue_id": context["existing_issue_id"],
        "context_digest": digest(context),
        "context": context,
    }


def validate_proposal(
    source: dict[str, Any], payload: IssueEventProposal | dict[str, Any]
) -> IssueEventProposal:
    """Validate against a freshly trusted read, never a model-supplied snapshot."""
    proposal = IssueEventProposal.model_validate(payload)
    context = model_context(source)
    existing = context["existing_issue_id"]
    if existing is not None:
        if proposal.disposition != "reuse_issue" or str(proposal.existing_issue_id) != existing:
            raise IssueEventProposalError(
                "existing_issue_requires_reuse", "已有实际问题，只能复用原问题"
            )
    elif proposal.disposition == "reuse_issue":
        raise IssueEventProposalError("existing_issue_missing", "原来源没有可复用的实际问题")
    references = {row["reference_id"]: row["excerpt"] for row in context["references"]}
    for citation in proposal.citations:
        excerpt = references.get(citation.reference_id)
        if (
            excerpt is None
            or citation.exact_quote not in excerpt
            or not any(character.isalnum() for character in citation.exact_quote)
        ):
            raise IssueEventProposalError("citation_invalid", "引用须逐字对应所提供的业务原文")
    if proposal.disposition == "create_issue":
        proof = (
            "test.original.failure"
            if source["source_kind"] == "test_failure"
            else "material.original.shortage"
        )
        valid = any(
            (item.reference_id == proof and item.exact_quote == references[proof])
            or (
                source["source_kind"] == "test_failure"
                and item.reference_id == "test.original.result_notes"
            )
            for item in proposal.citations
        )
        if not valid:
            raise IssueEventProposalError(
                "failure_evidence_required",
                "新建须引用原失败说明或完整失败/缺口事实，不能只引标题或元数据",
            )
    return proposal
