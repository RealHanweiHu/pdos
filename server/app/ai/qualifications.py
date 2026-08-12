"""Read-only loader for operator-published golden-case model qualifications."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.ai.model_catalog import GoldenQualification, ProviderName


class GoldenQualificationFileError(ValueError):
    """Raised when the trusted qualification document is missing or invalid."""


class QualificationEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    model: str = Field(min_length=1, max_length=128)
    status: Literal["passed", "failed"]


class QualificationDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    suite_version: str = Field(min_length=1, max_length=64)
    suite_digest: str = Field(min_length=1, max_length=256)
    models: list[QualificationEntry]

    @model_validator(mode="after")
    def reject_duplicate_models(self) -> Self:
        identities = [(entry.provider, entry.model) for entry in self.models]
        if len(identities) != len(set(identities)):
            raise ValueError("qualification models must be unique")
        return self


def load_golden_qualifications(path: Path) -> list[GoldenQualification]:
    try:
        document = QualificationDocument.model_validate_json(path.read_text())
    except (OSError, UnicodeError, ValidationError) as error:
        raise GoldenQualificationFileError("golden qualification document is invalid") from error
    return [
        GoldenQualification(
            provider=entry.provider,
            model=entry.model,
            suite_version=document.suite_version,
            suite_digest=document.suite_digest,
            status=entry.status,
        )
        for entry in document.models
    ]
