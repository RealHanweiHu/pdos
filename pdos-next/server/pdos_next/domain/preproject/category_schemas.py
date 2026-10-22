"""Closed category material commands; provenance is exclusively server-bound."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_serializer, model_validator

from pdos_next.schema_base import StrictModel

from .schemas import Reference

KnowledgeKind = Literal[
    "boundary", "segment", "competitor", "voice", "regulation", "research_question"
]


class BoundaryContent(StrictModel):
    definition: str = Field(min_length=1)
    includes: list[str] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)
    criteria: list[str] = Field(default_factory=list)
    criteria_note: str | None = None
    edge_cases: list[dict | str] = Field(default_factory=list)
    classification_rule: str | None = None
    decision_record: dict | None = None
    material: dict = Field(default_factory=dict)


class SegmentContent(StrictModel):
    segment: str = Field(min_length=1)
    jtbd: list[str] = Field(default_factory=list)
    buying_criteria: list[dict | str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    material: dict = Field(default_factory=dict)


class CompetitorMetric(StrictModel):
    parameter_id: UUID
    parameter_version: int = Field(gt=0)
    value: Decimal | str | bool | None = None
    lower: Decimal | None = None
    upper: Decimal | None = None
    text: str | None = None
    unit: str | None = None
    condition_note: str | None = None
    nature: Literal["measured", "claimed", "inferred", "unknown"]
    source_ref: Reference | None = None


class PriceObservation(StrictModel):
    amount: Decimal | None = None
    currency: str | None = None
    observed_on: str | None = None
    price_type: Literal["retail", "promo", "unknown"] = "unknown"
    includes_tax: bool | None = None
    includes_shipping: bool | None = None
    channel: str | None = None
    region: str | None = None
    source_ref: Reference | None = None


class SegmentRef(StrictModel):
    entry_id: UUID
    version: int = Field(gt=0, strict=True)


class CompetitorContent(StrictModel):
    brand: str = Field(min_length=1)
    model: str = Field(min_length=1)
    metrics: list[CompetitorMetric] = Field(default_factory=list)
    features: list[CompetitorMetric] = Field(default_factory=list)
    prices: list[PriceObservation] = Field(default_factory=list)
    segment_refs: list[SegmentRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_segments(self):
        keys = [(ref.entry_id, ref.version) for ref in self.segment_refs]
        if len(keys) != len(set(keys)):
            raise ValueError("Fixed segment references must be distinct")
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_content(self, handler):
        result = handler(self)
        # Existing candidate and replay digests include the old defaults. Only
        # this new field is absent when omitted; an explicit [] remains a clear.
        if "segment_refs" not in self.model_fields_set:
            result.pop("segment_refs", None)
        return result


class VoiceContent(StrictModel):
    label: str = Field(min_length=1)
    representative_refs: list[Reference] = Field(default_factory=list)
    source_platform: str
    # Sample size is derived by the service from distinct supplied source locations.


class RegulationContent(StrictModel):
    instrument: str = Field(min_length=1)
    region: str
    applicability: str | None = None
    source_state: str
    applicability_state: str
    compliance_state: str
    requirement_kind: Literal["statutory", "customer_channel", "voluntary_reference"]
    classification_state: str = "ai_draft"
    material: dict = Field(default_factory=dict)


class ResearchQuestionContent(StrictModel):
    question: str = Field(min_length=1)
    assumption: dict | None = None


CONTENT_TYPES = {
    "boundary": BoundaryContent,
    "segment": SegmentContent,
    "competitor": CompetitorContent,
    "voice": VoiceContent,
    "regulation": RegulationContent,
    "research_question": ResearchQuestionContent,
}


class Candidate(StrictModel):
    prepared_by_run_id: UUID | None = None
    candidate_digest: str | None = None
    confirmation_token: str | None = None


class Supersedes(StrictModel):
    lineage_id: UUID
    expected_version: int = Field(gt=0)


class KnowledgeAdd(Candidate):
    kind: KnowledgeKind
    content: dict
    regions: list[str] = Field(default_factory=list)
    source_refs: list[Reference] = Field(default_factory=list)
    supersedes: Supersedes | None = None

    @model_validator(mode="after")
    def typed_content(self):
        self.content = CONTENT_TYPES[self.kind].model_validate(self.content).model_dump(mode="json")
        return self


class KnowledgeWithdraw(Candidate):
    lineage_id: UUID
    expected_version: int = Field(gt=0)
    reason: str = Field(min_length=1)


class SourceItemRef(StrictModel):
    item_id: UUID
    version: int = Field(gt=0)


class KnowledgePromote(Candidate):
    source_proposal_id: UUID
    source_proposal_revision: int = Field(gt=0)
    source_item_refs: list[SourceItemRef] = Field(default_factory=list)
    kind: KnowledgeKind
    content: dict
    deidentified_confirmed: bool

    @model_validator(mode="after")
    def typed_content(self):
        self.content = CONTENT_TYPES[self.kind].model_validate(self.content).model_dump(mode="json")
        return self


class ParameterPublish(Candidate):
    parameter_id: UUID | None = None
    expected_current_version: int = Field(ge=0)
    key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    value_type: Literal["number", "range", "text", "boolean", "enum"]
    enum_values: list[str] | None = None
    unit: str | None = None
    direction: Literal["higher", "lower", "target", "neutral"]
    standard_condition: str | None = None
    method: str | None = None
    acceptance_criterion: str | None = None
    change_note: str = Field(min_length=1)

    @model_validator(mode="after")
    def version_and_enum(self):
        if (self.parameter_id is None) != (self.expected_current_version == 0):
            raise ValueError("New parameters start at version zero; revisions require identity")
        if self.value_type != "enum" and self.enum_values is not None:
            raise ValueError("Only enum parameters have enum values")
        if self.enum_values and len(self.enum_values) != len(set(self.enum_values)):
            raise ValueError("Enum values must be distinct")
        return self


PAYLOADS = {
    "category.knowledge.add": KnowledgeAdd,
    "category.knowledge.withdraw": KnowledgeWithdraw,
    "category.knowledge.promote": KnowledgePromote,
    "category.parameter.publish": ParameterPublish,
}
