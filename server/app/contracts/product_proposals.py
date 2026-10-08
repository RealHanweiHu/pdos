"""Lightweight pre-project proposals; approval never freezes engineering specifications."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.object_operations import CommandPrecondition


class ProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProposalSpec(ProposalInput):
    parameter_id: UUID | None = None
    parameter_version: int | None = Field(default=None, ge=1)
    direction: Literal["higher", "lower", "target", "neutral"] | None = None
    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    value: str = Field(default="", max_length=2048)
    unit: str = Field(default="", max_length=64)
    conditions: str = Field(default="", max_length=1024)
    state: Literal["ai_draft", "confirmed", "expert_pending", "unknown"] = "unknown"
    source_ids: list[str] = Field(default_factory=list, max_length=20)


class ProposalOption(ProposalInput):
    key: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=128)
    audience: str = Field(default="", max_length=1024)
    positioning: str = Field(default="", max_length=2048)
    use_path: str = Field(default="", max_length=2048)
    price_band: str = Field(default="", max_length=512)
    tradeoffs: str = Field(default="", max_length=2048)
    source_ids: list[str] = Field(default_factory=list, max_length=20)


class ProposalDifference(ProposalInput):
    area: Literal["specification", "bom", "certification", "tooling"]
    baseline: str = Field(default="", max_length=2048)
    proposed: str = Field(default="", max_length=2048)
    impact: str = Field(default="", max_length=2048)
    source_ids: list[str] = Field(default_factory=list, max_length=20)


class ProposalCompetitor(ProposalInput):
    name: str = Field(min_length=1, max_length=256)
    audience: str = Field(default="未知", max_length=1024)
    use_path: str = Field(default="未知", max_length=2048)
    price_band: str = Field(default="未知", max_length=512)
    strengths: str = Field(default="未知", max_length=2048)
    pain_points: str = Field(default="未知", max_length=2048)
    comparison_basis: str = Field(default="口径待核对", max_length=2048)
    source_ids: list[str] = Field(min_length=1, max_length=20)


class ProposalVoice(ProposalInput):
    quote: str = Field(min_length=1, max_length=2048)
    context: str = Field(default="", max_length=1024)
    pain_point: str = Field(default="", max_length=1024)
    source_ids: list[str] = Field(min_length=1, max_length=20)


class ProposalDocument(ProposalInput):
    narrative: str = Field(default="", max_length=24000)
    specifications: list[ProposalSpec] = Field(default_factory=list, max_length=80)
    options: list[ProposalOption] = Field(default_factory=list, max_length=3)
    differences: list[ProposalDifference] = Field(default_factory=list, max_length=40)
    questions: list[str] = Field(default_factory=list, max_length=30)
    risks: list[str] = Field(default_factory=list, max_length=30)
    competitors: list[ProposalCompetitor] = Field(default_factory=list, max_length=12)
    user_voices: list[ProposalVoice] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def unique_keys(self) -> Self:
        for values in ([s.id for s in self.specifications], [o.key for o in self.options]):
            if len(set(values)) != len(values):
                raise ValueError("规格编号和方案编号不能重复")
        if any(not value.strip() or len(value) > 2048 for value in self.questions + self.risks):
            raise ValueError("问题和风险需为非空短文本")
        return self


class ProposalCreate(ProposalInput):
    target_regions: list[str] = Field(default_factory=list, max_length=30)
    request_id: UUID
    title: str = Field(min_length=1, max_length=512)
    entry_kind: Literal["odm", "new_product", "iteration"]
    brief: str = Field(default="", max_length=16000)
    product_line_id: UUID | None = None
    baseline_product_id: UUID | None = None
    source_file_ids: list[UUID] = Field(default_factory=list, max_length=8)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def actual_input(self) -> Self:
        if not self.brief and not self.source_file_ids:
            raise ValueError("请提供需求片段或原文件")
        if len(set(self.source_file_ids)) != len(self.source_file_ids):
            raise ValueError("原文件不能重复")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("证据不能重复")
        return self


class ProposalEdit(CommandPrecondition):
    document: ProposalDocument
    ai_run_id: UUID | None = None


class ProposalSubmit(CommandPrecondition):
    reviewer_user_id: UUID


class ProposalDecide(CommandPrecondition):
    outcome: Literal["approved", "returned", "declined"]
    selected_option: str | None = Field(default=None, max_length=16)
    rationale: str = Field(min_length=1, max_length=4000)
    accepted_unknowns: str = Field(default="", max_length=4000)


class ProposalAIRequest(CommandPrecondition):
    instruction: str = Field(min_length=1, max_length=4000)


class ProposalAssessment(ProposalInput):
    document: ProposalDocument
    completed: list[str] = Field(max_length=20)
    needs_answers: list[str] = Field(max_length=30)
