"""Quality preparation proposes investigation and work, never a proven root cause."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.change_work_package import Statement


class QualityWork(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    kind: Literal["investigation", "corrective", "preventive"]
    description: str = Field(min_length=1, max_length=4000)
    expected_evidence: str = Field(min_length=1, max_length=4000)
    basis: Statement
    missing: tuple[str, ...] = Field(max_length=20)


class VerificationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    criteria: str = Field(min_length=1, max_length=4000)
    method_and_scope: str = Field(min_length=1, max_length=4000)
    minimum_observation_days: int | None = Field(ge=1, le=3650)
    basis: Statement
    missing: tuple[str, ...] = Field(max_length=20)


class QualityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    disposition: Literal["proposal", "insufficient_evidence"]
    phase: Literal["investigation", "actions"]
    observations: tuple[Statement, ...] = Field(max_length=20)
    hypotheses: tuple[Statement, ...] = Field(max_length=20)
    work: tuple[QualityWork, ...] = Field(max_length=30)
    verification: VerificationProposal | None
    missing: tuple[str, ...] = Field(max_length=50)
    coverage_limits: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if any(v.nature != "observed" for v in self.observations):
            raise ValueError("事实观察须引用原记录，不得以推导或假设替代")
        if any(v.nature != "hypothesis" for v in self.hypotheses):
            raise ValueError("模型原因判断始终作为待验证假设")
        if len({w.key for w in self.work}) != len(self.work):
            raise ValueError("每项调查或措施须有唯一编号")
        if self.disposition == "insufficient_evidence":
            if (
                not self.missing
                or self.observations
                or self.hypotheses
                or self.work
                or self.verification
            ):
                raise ValueError("证据不足时只说明待补资料与覆盖限制")
        elif not self.work:
            raise ValueError("方案须包含可核对的具体调查或措施")
        if any((w.kind == "investigation") != (self.phase == "investigation") for w in self.work):
            raise ValueError("根因调查与获批根因后的纠正预防措施应分别准备")
        if self.disposition == "proposal" and self.phase == "actions" and self.verification is None:
            raise ValueError("整改建议须包含后续有效性观察方案")
        missing = list(self.missing) + [v for w in self.work for v in w.missing]
        if self.verification:
            missing += self.verification.missing
            if self.verification.minimum_observation_days is None and not self.verification.missing:
                raise ValueError("观察时长未知须说明缺少的判据")
        if any(not v.strip() or len(v) > 4000 for v in missing):
            raise ValueError("待补说明应简明且非空")
        return self
