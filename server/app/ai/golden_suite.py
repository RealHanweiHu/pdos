"""Immutable golden-case suite schema and content digest."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class GoldenSuiteFileError(ValueError):
    """Raised when the checked-in golden suite is missing or malformed."""


class GoldenAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(min_length=1, max_length=64)
    evidence_codes: list[str] = Field(max_length=16)


class GoldenCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    system_prompt: str = Field(min_length=1, max_length=20_000)
    instruction: str = Field(min_length=1, max_length=20_000)
    context: dict[str, object]
    expected: GoldenAnswer


class GoldenSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1, le=1)
    suite_version: str = Field(min_length=1, max_length=64)
    pass_threshold: float = Field(ge=1.0, le=1.0)
    cases: list[GoldenCase] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_duplicate_case_ids(self) -> Self:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("golden case ids must be unique")
        return self


@dataclass(frozen=True)
class LoadedGoldenSuite:
    suite: GoldenSuite
    digest: str


def load_golden_suite(path: Path) -> LoadedGoldenSuite:
    try:
        document = path.read_bytes()
        suite = GoldenSuite.model_validate_json(document)
    except (OSError, ValidationError) as error:
        raise GoldenSuiteFileError("golden suite document is invalid") from error
    return LoadedGoldenSuite(
        suite=suite,
        digest=f"sha256:{sha256(document).hexdigest()}",
    )
