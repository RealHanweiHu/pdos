"""Typed engineering assessment data, independent of runtime and business services."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reference_id: str = Field(min_length=1, max_length=160)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    field_path: tuple[str, ...] = Field(min_length=1, max_length=12)
    quoted_value: str = Field(min_length=1, max_length=6000)


class Statement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    text: str = Field(min_length=1, max_length=4000)
    nature: Literal["observed", "derived", "hypothesis"]
    citations: tuple[Citation, ...] = Field(min_length=1, max_length=10)


class ProposedWork(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["retest", "rereview", "recertification", "coordination"]
    discipline: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=4000)
    completion_criteria: str | None = Field(min_length=1, max_length=4000)
    basis: Statement
    missing: tuple[str, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def clear_work(self) -> Self:
        if not self.discipline.strip() or not self.description.strip():
            raise ValueError("专业与工作说明须非空")
        if self.completion_criteria is None and not self.missing:
            raise ValueError("完成判据未知时须说明待补资料")
        if self.completion_criteria is not None and not self.completion_criteria.strip():
            raise ValueError("完成判据未知时请明确留空")
        return self


class Impact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    target_reference_id: str = Field(min_length=1, max_length=160)
    verdict: Literal["affected", "unaffected", "unknown"]
    basis: Statement
    proposed_work: tuple[ProposedWork, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def actionable_uncertainty(self) -> Self:
        if self.verdict != "unaffected" and not self.proposed_work:
            raise ValueError("受影响或未知影响须提出调查、复验或协同要求")
        if self.verdict != "unknown" and self.basis.nature == "hypothesis":
            raise ValueError("假设不能作为已判定影响")
        return self


class ChangeImpactAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    disposition: Literal["analysis", "insufficient_evidence"]
    summary: tuple[Statement, ...] = Field(max_length=20)
    impacts: tuple[Impact, ...] = Field(max_length=100)
    missing: tuple[str, ...] = Field(max_length=50)
    coverage_limits: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def scope(self) -> Self:
        if not self.coverage_limits.strip():
            raise ValueError("请明确本次覆盖限制")
        keys = [item.target_reference_id for item in self.impacts]
        if len(keys) != len(set(keys)):
            raise ValueError("同一对象的影响请合并")
        if self.disposition == "analysis" and not self.impacts:
            raise ValueError("影响分析需要逐对象结论")
        if self.disposition == "insufficient_evidence" and (self.impacts or self.summary):
            raise ValueError("证据不足时仅返回待补资料与覆盖限制")
        if self.disposition == "insufficient_evidence" and not self.missing:
            raise ValueError("请指出缺少的具体资料")
        statements = list(self.summary) + [i.basis for i in self.impacts]
        statements += [w.basis for i in self.impacts for w in i.proposed_work]
        if any(not s.text.strip() for s in statements):
            raise ValueError("说明不能为空")
        missing = list(self.missing) + [
            v for i in self.impacts for w in i.proposed_work for v in w.missing
        ]
        if any(not v.strip() or len(v) > 4000 for v in missing):
            raise ValueError("待补资料须简明且非空")
        return self
