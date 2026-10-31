"""Experience stays a candidate until a named, authorized applicability publication."""

from datetime import UTC
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_serializer, model_validator

from pdos_next.domain.work_management.schemas import DTO, SourceRef, Text, VersionRef

from .assistant_schemas import AnswerOrigin, KnowledgeReview

CANDIDATE_OP = "knowledge.candidate.create"
RULE_OP = "knowledge.rule.publish"


class ResultRef(DTO):
    receipt_id: UUID


class ReviewFields(DTO):
    knowledge_review: KnowledgeReview | None = None
    answer_origin: AnswerOrigin | None = None

    @model_serializer(mode="wrap")
    def old_digest(self, handler):
        value = handler(self)
        for name in ("knowledge_review", "answer_origin"):
            if getattr(self, name) is None:
                value.pop(name, None)
        return value


class CandidatePayload(ReviewFields):
    candidate: VersionRef | None = None
    project_id: UUID | None = None
    visibility: Literal["private", "category"] = "private"
    title: str = Field(min_length=1, max_length=200)
    lesson: Text
    evidence_summary: Text
    applicability_hypothesis: Text
    result_receipts: tuple[ResultRef, ...] = ()
    sources: tuple[SourceRef, ...]
    reason: Text

    @model_validator(mode="after")
    def actual_sources(self):
        if not self.sources and self.answer_origin is None and self.candidate is None:
            raise ValueError("须有精确原件或实际回答来源")
        if self.answer_origin is not None and self.knowledge_review is None:
            raise ValueError("回答候选须有实际负责人、适用范围和复核日期")
        return self

    @field_validator("sources")
    @classmethod
    def originals(cls, values):
        if any(value.kind != "artifact" for value in values):
            raise ValueError("Knowledge requires exact original artifact references")
        return values

    @field_validator("result_receipts")
    @classmethod
    def unique_results(cls, values):
        if len({value.receipt_id for value in values}) != len(values):
            raise ValueError("Result receipts cannot repeat")
        return values


class TargetConfiguration(VersionRef):
    kind: Literal["engineering_configuration", "process_revision"]


class Applicability(DTO):
    target: TargetConfiguration
    purpose: str = Field(min_length=1, max_length=2000)
    differences: tuple[Text, ...]
    adopted_rule: Text
    conditions: tuple[Text, ...]
    decision: Literal["applicable", "not_applicable", "unknown", "conflicted"]
    rationale: Text
    valid_from: AwareDatetime
    valid_until: AwareDatetime | None = None

    @field_validator("valid_from", "valid_until")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC) if value else None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("Applicability validity must have a positive interval")
        return self


class RulePublishPayload(ReviewFields):
    project_id: UUID
    candidate: VersionRef
    rule: VersionRef | None = None
    title: str = Field(min_length=1, max_length=200)
    rule_text: Text
    applicability: Applicability
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    reason: Text
    approval_token: str | None = Field(default=None, min_length=20, max_length=128)

    @field_validator("sources")
    @classmethod
    def originals(cls, values):
        return CandidatePayload.originals(values)


PAYLOADS = {CANDIDATE_OP: CandidatePayload, RULE_OP: RulePublishPayload}
