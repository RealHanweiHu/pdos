from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from pdos_next.schema_base import StrictModel
from pdos_next.schemas.spec_values import numeric_value_shape


class Reference(StrictModel):
    type: Literal[
        "human", "artifact", "original", "snapshot", "knowledge", "parameter", "definition", "claim"
    ]
    id: UUID
    version: int = Field(gt=0)
    line: int | None = Field(default=None, gt=0)
    quote: str | None = None
    statement: str | None = None


class SpecItem(StrictModel):
    key: str = Field(min_length=1)
    parameter: str = Field(min_length=1)
    parameter_id: UUID | None = None
    parameter_version: int | None = Field(default=None, gt=0)
    value_type: Literal["number", "range", "text", "boolean", "enum"]
    value: Decimal | None = None
    lower: Decimal | None = None
    upper: Decimal | None = None
    tolerance: Decimal | None = Field(default=None, ge=0)
    text_value: str | None = None
    unit: str | None = None
    condition_note: str | None = None
    test_conditions: list[str] = Field(default_factory=list)
    verification_method: str | None = None
    acceptance_criterion: str | None = None
    modality: Literal["must", "should", "may", "prohibited", "unstated"] | None = None
    exceptions: list[dict] = Field(default_factory=list)
    applicable_variants: list[dict] = Field(default_factory=list)
    nature: Literal["observed", "extracted", "computed", "inferred", "decided"] = "decided"
    availability: Literal["known", "unknown", "conflicted", "not_applicable"] = "unknown"
    item_status: Literal["ai_draft", "confirmed", "expert_pending", "unknown"] = "unknown"
    owner_id: UUID | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def consistent_values(self):
        if (self.parameter_id is None) != (self.parameter_version is None):
            raise ValueError("Parameter identity and version must be supplied together")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("Lower bound exceeds upper bound")
        values = (self.value, self.lower, self.upper, self.text_value)
        if self.availability != "known" and any(v is not None for v in values):
            raise ValueError("Unknown values must remain null")
        if self.availability == "known":
            valid = {
                "number": numeric_value_shape(
                    self.value_type, self.value, self.lower, self.upper, self.text_value
                ),
                "range": numeric_value_shape(
                    self.value_type, self.value, self.lower, self.upper, self.text_value
                ),
                "text": self.text_value is not None and all(v is None for v in values[:3]),
                "enum": self.text_value is not None and all(v is None for v in values[:3]),
                "boolean": self.text_value in {"true", "false"}
                and all(v is None for v in values[:3]),
            }[self.value_type]
            if not valid:
                raise ValueError("Value shape does not match value_type")
        if self.item_status == "confirmed" and self.availability not in {"known", "not_applicable"}:
            raise ValueError("Confirmed items need a value or a not-applicable reason")
        if self.availability == "not_applicable" and not self.reason:
            raise ValueError("Not-applicable items need a reason")
        return self


class Question(StrictModel):
    question: str = Field(min_length=1)
    owner_id: UUID
    due_date: date
    related_item_ids: list[UUID] = Field(default_factory=list)
    status: Literal["open", "answered", "carried"] = "open"
    answer: str | None = None
    supersedes_item_id: UUID | None = None

    @model_validator(mode="after")
    def answered(self):
        if self.status == "answered" and not self.answer:
            raise ValueError("Answered questions need an answer")
        return self


class ItemInput(StrictModel):
    item_id: UUID | None = None
    kind: Literal[
        "section",
        "option",
        "risk",
        "decision_note",
        "difference",
        "commercial_target",
        "assumption",
        "spec",
        "question",
    ]
    content: dict
    source_refs: list[Reference] = Field(default_factory=list)

    @model_validator(mode="after")
    def content_schema(self):
        if self.kind == "spec":
            self.content = SpecItem.model_validate(self.content).model_dump(mode="json")
            if self.content["item_status"] == "confirmed" and not self.source_refs:
                raise ValueError("Confirmed specifications need a source")
        elif self.kind == "question":
            self.content = Question.model_validate(self.content).model_dump(mode="json")
            if self.content["status"] == "carried":
                raise ValueError("Only a G0 decision can carry a question")
        elif self.kind == "section":
            if self.content.get("key") not in {
                "worth_it",
                "target_customer_market_channel",
                "features_in_out",
                "certification_regions",
                "launch_window",
                "summary",
            } or not isinstance(self.content.get("text"), str):
                raise ValueError("A section needs a registered key and text")
        elif self.kind == "option":
            if not self.content.get("name") or self.content.get("kind") not in {
                "new",
                "status_quo",
                "do_nothing",
            }:
                raise ValueError("An option needs a name and kind")
        elif self.kind == "commercial_target":
            self.content = CommercialTarget.model_validate(self.content).model_dump(mode="json")
            # Commercial facts have their own source field. Keep that citation in
            # the same validated, counted source set as every other item citation.
            for value in self.content.values():
                if value and value.get("source"):
                    ref = Reference.model_validate(value["source"])
                    if ref not in self.source_refs:
                        self.source_refs.append(ref)
        return self


class CommercialValue(StrictModel):
    amount: Decimal | None = None
    currency: str | None = None
    basis: Literal["retail", "promo", "unknown"] | None = None
    includes_tax: bool | None = None
    as_of: date | None = None
    source: Reference | None = None


class CommercialTarget(StrictModel):
    target_price: CommercialValue | None = None
    cost: CommercialValue | None = None
    volume: CommercialValue | None = None


class Groups(StrictModel):
    items: list[ItemInput] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)


class PreparedContent(StrictModel):
    prepared_by_run_id: UUID | None = None
    candidate_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    confirmation_token: str | None = None

    @model_validator(mode="after")
    def paired_candidate(self):
        if (self.prepared_by_run_id is None) != (self.candidate_digest is None):
            raise ValueError("Prepared run and candidate digest must be supplied together")
        return self


class ProposalCreate(PreparedContent):
    title: str = Field(min_length=1)
    entry_kind: Literal["customer_request", "new_product", "derivative"]
    target_kind: Literal["new_product", "new_variant"] = "new_product"
    baseline_product_id: UUID | None = None
    baseline_definition_id: UUID | None = None
    baseline_definition_revision: int | None = Field(default=None, gt=0)
    brief: str = ""
    customer_identities: list[str] = Field(default_factory=list)
    source_refs: list[Reference] = Field(default_factory=list)
    context_refs: list[Reference] = Field(default_factory=list)
    groups: Groups = Field(default_factory=Groups)

    @model_validator(mode="after")
    def baseline(self):
        needed = self.entry_kind == "derivative" or self.target_kind == "new_variant"
        if needed and (not self.baseline_product_id or not self.baseline_definition_revision):
            raise ValueError("Derivatives need a fixed baseline")
        if not needed and any(
            (
                self.baseline_product_id,
                self.baseline_definition_id,
                self.baseline_definition_revision,
            )
        ):
            raise ValueError("Only derivatives may bind a parent baseline")
        return self


class PatchOp(ItemInput):
    op: Literal["upsert", "remove"] = "upsert"
    base_version: int | None = Field(default=None, gt=0)


class ItemPatch(PreparedContent):
    proposal_id: UUID
    ops: list[PatchOp] = Field(min_length=1)
    source_refs: list[Reference] = Field(default_factory=list)


class QuestionCreate(Question, PreparedContent):
    proposal_id: UUID
    expected_revision: int = Field(gt=0)
    confirmation_token: str | None = None


class G0Submit(StrictModel):
    proposal_id: UUID
    expected_revision: int = Field(gt=0)
    reviewer_id: UUID
    no_alternative_reason: str | None = None
    confirmation_token: str | None = None


class Disposition(StrictModel):
    subject_type: Literal["question", "spec_item"]
    subject_id: UUID
    kind: Literal["task", "risk"]
    owner_id: UUID
    due_date: date
    note: str = Field(min_length=1)


class ProjectInput(StrictModel):
    name: str = Field(min_length=1)
    owner_id: UUID | None = None


class IdentityInput(StrictModel):
    name: str = Field(min_length=1)
    variant_kind: Literal["customer", "region", "configuration"] = "configuration"


class G0Decide(StrictModel):
    proposal_id: UUID
    submission_id: UUID
    expected_revision: int = Field(gt=0)
    outcome: Literal["approved", "returned", "rejected"]
    rationale: str = Field(min_length=1)
    selected_option_item_id: UUID | None = None
    dispositions: list[Disposition] = Field(default_factory=list)
    project: ProjectInput | None = None
    new_identity: IdentityInput | None = None
    approval_token: str | None = None


PAYLOADS = {
    "proposal.create": ProposalCreate,
    "proposal.item.patch": ItemPatch,
    "proposal.question.create": QuestionCreate,
    "proposal.g0.submit": G0Submit,
    "proposal.g0.decide": G0Decide,
}
OPERATIONS = frozenset(PAYLOADS)
