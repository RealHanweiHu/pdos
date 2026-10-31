"""Strict human retrieval selectors, independent from SQL and runtime imports."""

from datetime import datetime
from typing import Literal, get_args
from uuid import UUID

from pydantic import Field, model_validator

from pdos_next.schema_base import StrictModel

SourceType = Literal[
    "artifact",
    "knowledge",
    "issue",
    "capa",
    "change",
    "external_wait",
    "supply",
    "build",
    "test_run",
    "field_feedback",
    "project_status",
    "manufacturing_document",
    "verification_handoff",
]
SOURCE_TYPES = get_args(SourceType)


class SearchInput(StrictModel):
    query: str = Field(min_length=1, max_length=2000)
    source_types: list[SourceType] = Field(
        default_factory=lambda: list(SOURCE_TYPES),
        min_length=1,
        max_length=len(SOURCE_TYPES),
    )
    category_id: UUID | None = None
    product_id: UUID | None = None
    project_id: UUID | None = None
    proposal_id: UUID | None = None
    include_history: bool = False
    after: datetime | None = None
    before: datetime | None = None
    limit: int = Field(default=10, ge=1, le=50, strict=True)

    @model_validator(mode="after")
    def aware_dates(self):
        for value in (self.after, self.before):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("Search dates require a timezone")
        if self.after and self.before and self.after >= self.before:
            raise ValueError("Search time range is empty")
        return self
