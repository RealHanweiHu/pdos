"""Trusted deterministic contract cases for the Phase 1 Agent prompts."""

from __future__ import annotations

from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.ai.executor import AgentAssessment, FindingCandidateType
from app.ai.runtime_contract import PHASE_ONE_AGENT_KEYS, AgentKey


class PhaseOneSuiteFileError(ValueError):
    pass


class PhaseOneGoldenCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    agent_key: AgentKey
    event_type: str = Field(min_length=1, max_length=64)
    output: AgentAssessment
    expected_finding_type: FindingCandidateType | None


class PhaseOneGoldenSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1, le=1)
    suite_version: str = Field(min_length=1, max_length=64)
    prompt_versions: dict[AgentKey, str]
    cases: tuple[PhaseOneGoldenCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_suite(self) -> Self:
        if set(self.prompt_versions) != PHASE_ONE_AGENT_KEYS:
            raise ValueError("Phase 1 suite must bind every Agent prompt version")
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Phase 1 golden case ids must be unique")
        return self


def load_phase_one_golden_suite(path: Path) -> PhaseOneGoldenSuite:
    try:
        return PhaseOneGoldenSuite.model_validate_json(path.read_text())
    except (OSError, UnicodeError, ValidationError) as error:
        raise PhaseOneSuiteFileError("Phase 1 golden suite document is invalid") from error
