"""Explicit Human knowledge contribution; authority never comes from these selectors."""

from datetime import UTC
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator

from pdos_next.schema_base import StrictModel


class AnswerOrigin(StrictModel):
    run_id: UUID
    answer_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class KnowledgeReview(StrictModel):
    responsible_id: UUID
    applicability_scope: str = Field(min_length=1, max_length=4000)
    review_due_at: AwareDatetime

    @field_validator("review_due_at")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC)


class VerifiedAnswerContent(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=8000)
    answer: str = Field(min_length=1, max_length=200000)
    draft_origin: Literal["ai_draft"] = "ai_draft"


class AnswerDraftInput(StrictModel):
    run_id: UUID
    kind: Literal["category", "rule"] = "category"


class GapPreviewInput(StrictModel):
    run_id: UUID
    kind: Literal["missing_material", "shared_feedback"]
    feedback_id: UUID | None = None


class GapInput(GapPreviewInput):
    request_key: UUID
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class AttributionInput(StrictModel):
    request_key: UUID
    submission_id: UUID
    reason: Literal[
        "missing_material",
        "version_conflict",
        "unclear_content",
        "retrieval_miss",
        "answer_problem",
    ]


class ReviewDraftInput(StrictModel):
    entry_id: UUID
