"""Typed clarification and research candidates, never model-granted write authority."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.product_proposals import ProposalDocument

Goal = Literal["category", "proposal"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Question(Input):
    id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=1024)
    options: list[str] = Field(default_factory=list, max_length=3)
    recommendation: str = Field(default="", max_length=512)


class Parameter(Input):
    key: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]{0,63}$")
    label: str = Field(min_length=1, max_length=128)
    unit: str = Field(min_length=1, max_length=64)
    conditions: str = Field(min_length=1, max_length=1024)
    direction: Literal["higher", "lower", "target", "neutral"]
    verification_method: str = Field(default="", max_length=2048)
    acceptance_criterion: str = Field(default="", max_length=2048)


class Note(Input):
    kind: Literal["scene", "voice", "regulation", "general_requirement", "competitor"]
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(min_length=1, max_length=8000)
    citation_ids: list[str] = Field(default_factory=list, max_length=10)
    state: Literal["ai_draft", "unknown"] = "unknown"


class CategoryCandidate(Input):
    code: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{1,128}$")
    title: str = Field(min_length=1, max_length=512)
    user_groups: list[str] = Field(min_length=1, max_length=20)
    regions: list[str] = Field(min_length=1, max_length=20)
    use_scenarios: list[str] = Field(min_length=1, max_length=20)
    research_questions: list[str] = Field(min_length=1, max_length=20)
    parameters: list[Parameter] = Field(default_factory=list, max_length=20)
    notes: list[Note] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def keys(self) -> Self:
        if len({p.key for p in self.parameters}) != len(self.parameters):
            raise ValueError("参数键不能重复")
        if any(n.state != "unknown" and not n.citation_ids for n in self.notes):
            raise ValueError("研究资料需原文引用，无来源内容保留未知")
        if any(
            not s.strip() or len(s) > 1024
            for s in self.user_groups + self.regions + self.use_scenarios + self.research_questions
        ):
            raise ValueError("品类条目不能为空或过长")
        return self


class ProposalCandidate(Input):
    title: str = Field(min_length=1, max_length=512)
    entry_kind: Literal["odm", "new_product", "iteration"]
    document: ProposalDocument


class Assessment(Input):
    goal: Goal
    stage: Literal["clarify", "ready"]
    questions: list[Question] = Field(default_factory=list, max_length=3)
    category: CategoryCandidate | None = None
    proposal: ProposalCandidate | None = None

    @model_validator(mode="after")
    def shape(self) -> Self:
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError("澄清问题编号不能重复")
        if self.stage == "clarify":
            if not self.questions or self.category or self.proposal:
                raise ValueError("澄清只询问当前可回答的必要决策")
        elif (
            self.questions
            or (self.goal == "category" and (not self.category or self.proposal))
            or (self.goal == "proposal" and (not self.proposal or self.category))
        ):
            raise ValueError("候选需匹配当前入口")
        return self
