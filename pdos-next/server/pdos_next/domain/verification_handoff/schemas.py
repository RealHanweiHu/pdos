"""Closed human payloads; no readiness, authority, receipt or actual configuration from claims."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from pdos_next.domain.configurations.schemas import DefinitionReference
from pdos_next.domain.verification_front.schemas import Key, Revision, Text
from pdos_next.schemas.verification.contracts import DTO, Coverage, EventTime, SampleRef


class HandoffBase(DTO):
    request_id: UUID
    expected_request_revision: Revision
    sources: tuple[DefinitionReference, ...] = Field(default=())
    reason: Text
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)


class ActualItemAssessment(DTO):
    sample: SampleRef
    item_id: Key
    expected_assessment_revision: Annotated[int, Field(ge=0, strict=True)]
    status: Literal["applicable", "not_applicable", "unknown"]
    conditions: tuple[Text, ...] = Field(default=())
    reason: Text
    sources: tuple[DefinitionReference, ...] = Field(default=())

    @model_validator(mode="after")
    def positive_evidence(self) -> Self:
        if self.status == "applicable" and not self.sources:
            raise ValueError("实际配置适用结论必须有逐对精确原文依据")
        return self


class ActualMethodPreparePayload(HandoffBase):
    assessments: tuple[ActualItemAssessment, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_pairs(self) -> Self:
        pairs = [(a.sample.id, a.item_id) for a in self.assessments]
        if len(pairs) != len(set(pairs)):
            raise ValueError("每个实际样件与测试项只能有一个本次核对结论")
        return self


class OfferPayload(HandoffBase):
    samples: tuple[SampleRef, ...] = Field(min_length=1)
    coverage: tuple[Coverage, ...] = Field(min_length=1)
    at: EventTime

    @model_validator(mode="after")
    def unique_coverage(self) -> Self:
        ids = [sample.id for sample in self.samples]
        pairs = [(c.sample_id, c.item_id) for c in self.coverage]
        if len(ids) != len(set(ids)) or len(pairs) != len(set(pairs)):
            raise ValueError("交样身份与逐项范围不能重复")
        if set(ids) != {c.sample_id for c in self.coverage}:
            raise ValueError("每个交样身份必须属于明确交接范围")
        return self


class AcceptPayload(HandoffBase):
    coverage: tuple[Coverage, ...] = Field(min_length=1)
    returned_coverage: tuple[Coverage, ...] = Field(default=())
    next_owner_id: UUID | None = None
    at: EventTime

    @model_validator(mode="after")
    def disjoint(self) -> Self:
        accepted = {(c.sample_id, c.item_id) for c in self.coverage}
        returned = {(c.sample_id, c.item_id) for c in self.returned_coverage}
        if len(accepted) != len(self.coverage) or len(returned) != len(self.returned_coverage):
            raise ValueError("接收和退回的逐项范围不能重复")
        if accepted & returned:
            raise ValueError("接收与退回范围须互不相交")
        return self


class ReturnPayload(HandoffBase):
    coverage: tuple[Coverage, ...] = Field(min_length=1)
    next_owner_id: UUID
    at: EventTime

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({(c.sample_id, c.item_id) for c in self.coverage}) != len(self.coverage):
            raise ValueError("退回范围不能重复")
        return self
