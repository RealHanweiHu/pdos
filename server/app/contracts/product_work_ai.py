"""Explicit source selection for product work before a Project exists."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.change_work_package import Statement

ProductCapability = Literal[
    "research_planning",
    "rfq_requirements",
    "competitor_analysis",
    "market_analysis",
    "opportunity_mapping",
    "experiment_design",
    "product_strategy",
    "product_definition",
]
BusinessSourceKind = Literal[
    "product",
    "work",
    "research",
    "competitor",
    "segment",
    "opportunity",
    "experiment",
    "strategy",
    "definition",
    "evidence",
]


ProductSourceKind = BusinessSourceKind | Literal["file"]


class ProductFileSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["file"]
    id: UUID
    ordinals: tuple[int, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_fragments(self) -> Self:
        if any(value < 1 for value in self.ordinals) or len(set(self.ordinals)) != len(
            self.ordinals
        ):
            raise ValueError("原文片段编号须为不重复的正整数")
        return self


class ProductPrivateAttachmentSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["private_attachment"]
    conversation_id: UUID
    id: UUID
    ordinals: tuple[int, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_fragments(self) -> Self:
        if any(value < 1 for value in self.ordinals) or len(set(self.ordinals)) != len(
            self.ordinals
        ):
            raise ValueError("原文片段编号须为不重复的正整数")
        return self


class ProductSourceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: BusinessSourceKind
    id: UUID


class ProductWorkSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    capability: ProductCapability
    product_line_id: UUID | None = None
    sources: list[
        ProductSourceSelection | ProductFileSelection | ProductPrivateAttachmentSelection
    ] = Field(default_factory=list, max_length=20)
    question: str = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        if self.capability == "rfq_requirements":
            if not self.sources or any(
                s.kind not in {"file", "private_attachment"} for s in self.sources
            ):
                raise ValueError("RFQ抽取须选择已解析原件中的明确片段")
        elif any(s.kind == "file" for s in self.sources):
            raise ValueError("客户原件请从RFQ需求抽取入口办理")
        keys = [(s.kind, s.id) for s in self.sources]
        if len(set(keys)) != len(keys):
            raise ValueError("同一来源不能重复选择")
        if (
            self.capability
            in {
                "opportunity_mapping",
                "experiment_design",
                "product_strategy",
                "product_definition",
            }
            and self.product_line_id is None
        ):
            raise ValueError("请为此项产品工作选择具体产品线")
        return self


class ProductWorkOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    product_line_id: UUID | None = None
    kind: ProductSourceKind = "research"
    query: str = Field(default="", max_length=200)
    offset: int = Field(default=0, ge=0, le=100000)


CAPABILITY_LABELS = {
    "rfq_requirements": "RFQ需求抽取",
    "research_planning": "研究规划",
    "competitor_analysis": "竞品分析",
    "market_analysis": "市场分析",
    "opportunity_mapping": "机会与方案",
    "experiment_design": "实验设计",
    "product_strategy": "产品策略",
    "product_definition": "产品定义",
}

REQUIRED_SECTIONS = {
    "rfq_requirements": (
        "scope_and_sources",
        "requirements",
        "acceptance_criteria",
        "uncertainties",
    ),
    "research_planning": ("questions", "scope_and_sources", "method", "stop_conditions"),
    "competitor_analysis": ("comparison_scope", "conditions_and_units", "differences", "conflicts"),
    "market_analysis": ("users_and_jtbd", "market_size", "assumptions", "evidence_gaps"),
    "opportunity_mapping": ("desired_outcomes", "opportunities", "alternatives", "tradeoffs"),
    "experiment_design": ("hypotheses", "vuvf_coverage", "method", "falsification"),
    "product_strategy": ("canvas", "routes", "cost_and_timing", "professional_constraints"),
    "product_definition": ("strategy_basis", "scope", "specifications", "verification"),
}


class ProductAnalysisSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str = Field(min_length=1, max_length=64)
    statements: tuple[Statement, ...] = Field(max_length=12)
    missing: tuple[str, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def has_result_or_gap(self) -> Self:
        if not self.statements and not self.missing:
            raise ValueError("每部分须有带依据的分析或明确缺项")
        if any(not text.strip() or len(text) > 2000 for text in self.missing):
            raise ValueError("缺项说明须非空且不超过2000字符")
        return self


class ProductWorkAssessment(BaseModel):
    """Analysis receipts are proposals, never published definitions or executed work."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    capability: ProductCapability
    disposition: Literal["analysis", "insufficient_evidence"]
    summary: tuple[Statement, ...] = Field(max_length=8)
    sections: tuple[ProductAnalysisSection, ...] = Field(min_length=4, max_length=4)
    next_steps: tuple[Statement, ...] = Field(max_length=12)
    missing: tuple[str, ...] = Field(max_length=30)
    coverage_limits: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def complete_sections(self) -> Self:
        if {section.key for section in self.sections} != set(REQUIRED_SECTIONS[self.capability]):
            raise ValueError("须逐项覆盖本能力的四部分，缺资料时明确列出缺项")
        if self.disposition == "insufficient_evidence" and not self.missing:
            raise ValueError("资料不足须列明待补项")
        if any(not text.strip() or len(text) > 2000 for text in self.missing):
            raise ValueError("缺项说明须非空且不超过2000字符")
        if not self.coverage_limits.strip():
            raise ValueError("须说明本次覆盖限制")
        return self


class ResearchPlanProposal(BaseModel):
    """A task proposal; actor/scope/IDs/state are always supplied by the server."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)
    question: str = Field(min_length=1, max_length=2048)
    user_groups: tuple[str, ...] = Field(min_length=1, max_length=30)
    regions: tuple[str, ...] = Field(min_length=1, max_length=30)
    time_scope: str = Field(min_length=1, max_length=2048)
    method: str = Field(min_length=1, max_length=2048)
    expected_decision: str = Field(min_length=1, max_length=2048)
    stop_conditions: tuple[str, ...] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def bounded_items(self) -> Self:
        if any(
            not s.strip() or len(s) > 2048
            for s in (*self.user_groups, *self.regions, *self.stop_conditions)
        ):
            raise ValueError("研究范围与停止条件须非空且不超过2048字符")
        return self


class ProductResearchAssessment(ProductWorkAssessment):
    research_plan: ResearchPlanProposal | None = None

    @model_validator(mode="after")
    def proposal_needs_basis(self) -> Self:
        if self.capability != "research_planning":
            raise ValueError("研究起草合同仅适用于研究规划")
        if self.research_plan is not None and not self.summary:
            raise ValueError("研究候选须保留带原引用的规划依据")
        return self
