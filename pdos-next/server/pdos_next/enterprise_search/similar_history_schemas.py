"""Finite page retrieval and explicit feedback inputs, independent of Agent runs."""

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from pdos_next.schema_base import StrictModel


class SimilarHistoryInput(StrictModel):
    version_id: UUID


class SimilarHistoryFeedback(StrictModel):
    version_id: UUID
    candidate_kind: Literal["issue", "capa", "change"]
    candidate_source_id: UUID
    candidate_revision: int = Field(ge=1, le=2147483647, strict=True)
    action: Literal["opened", "not_relevant", "merge_prepared"]
    request_key: UUID


class SimilarHistoryTitleInput(StrictModel):
    kind: Literal["issue", "change"]
    title: str = Field(min_length=1, max_length=240, strict=True)
    project_id: UUID | None = None

    @field_validator("title", mode="before")
    @classmethod
    def trimmed_title(cls, value):
        return value.strip() if isinstance(value, str) else value
