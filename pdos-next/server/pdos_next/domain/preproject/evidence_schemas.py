"""Evidence command inputs; identity, provenance and privacy stay server-bound."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, StrictBool, model_serializer, model_validator

from pdos_next.schema_base import StrictModel

ClaimNature = Literal["observed", "extracted", "computed", "inferred", "decided"]
Availability = Literal["known", "unknown", "conflicted", "not_applicable"]


class ClaimSource(StrictModel):
    # Quotes are literal source substrings: preserve spaces and line endings.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    kind: Literal["artifact", "snapshot"]
    id: UUID
    version: int = Field(gt=0)
    locator: str | None = Field(default=None, min_length=1)
    line: int | None = Field(default=None, gt=0)
    quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def located_source(self):
        if self.locator is None:
            if self.line is None:
                raise ValueError("A source locator or line is required")
            self.locator = f"line:{self.line}"
        if not self.locator.strip() or not self.quote.strip():
            raise ValueError("Source locator and quote must not be blank")
        if self.locator.startswith("line:"):
            try:
                located_line = int(self.locator.removeprefix("line:"))
            except ValueError as exc:
                raise ValueError("Invalid line locator") from exc
            if located_line < 1 or (self.line is not None and self.line != located_line):
                raise ValueError("Source line and locator disagree")
            self.line = located_line
        return self


class ClaimContent(StrictModel):
    parameter_id: UUID | None = None
    parameter_version: int | None = Field(default=None, gt=0)
    value: Decimal | str | bool | None = None
    lower: Decimal | None = None
    upper: Decimal | None = None
    unit: str | None = None
    condition_note: str | None = None
    modality: Literal["must", "should", "may", "prohibited", "unstated"] | None = None
    exceptions: list[dict] = Field(default_factory=list)
    verification_method: str | None = None
    acceptance_criterion: str | None = None
    text: str | None = None

    @model_validator(mode="after")
    def coherent_values(self):
        if (self.parameter_id is None) != (self.parameter_version is None):
            raise ValueError("Parameter identity and version must be supplied together")
        if self.lower is not None or self.upper is not None:
            if self.lower is not None and self.upper is not None and self.lower > self.upper:
                raise ValueError("Lower bound exceeds upper bound")
            if self.value is not None:
                raise ValueError("Choose a scalar value or a range")
        for value in (self.value, self.lower, self.upper):
            if isinstance(value, Decimal) and not value.is_finite():
                raise ValueError("Numeric evidence must be finite")
        return self


class ClaimRecord(StrictModel):
    """One record, accepting either canonical source or the existing S0 input.

    Legacy source revision is deliberately not inferred here: the command's
    authoritative read set supplies it. Legacy visibility is only a requested
    restriction; the handler must reject enlargement of source/Run privacy.
    """

    source: ClaimSource | None = None
    artifact_id: UUID | None = None
    line: int | None = Field(default=None, gt=0)
    quote: str | None = Field(default=None, min_length=1)
    statement: str | None = Field(default=None, min_length=1)
    visibility: Literal["private", "category", "audience"] | None = None
    nature: ClaimNature = "extracted"
    availability: Availability = "known"
    vendor_claimed: StrictBool = False
    content: dict = Field(default_factory=dict)
    extraction_ref: str | dict | None = None
    proposal_id: UUID | None = None
    prepared_event_id: UUID | None = None
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def source_and_content(self):
        legacy = (self.artifact_id, self.line, self.quote, self.statement)
        if self.source is None:
            if any(value is None for value in legacy):
                raise ValueError("Legacy claims require artifact_id, line, quote and statement")
            if self.visibility is None:
                self.visibility = "private"
        elif any(value is not None for value in legacy) or "visibility" in self.model_fields_set:
            raise ValueError("Canonical source cannot include legacy source or visibility fields")
        if self.vendor_claimed and self.nature != "extracted":
            raise ValueError("Only extracted claims can be vendor-claimed")
        if self.content:
            typed = ClaimContent.model_validate(self.content)
            self.content = typed.model_dump(mode="json", exclude_unset=True)
            if self.availability in {"unknown", "not_applicable"} and any(
                value is not None for value in (typed.value, typed.lower, typed.upper)
            ):
                raise ValueError("Unavailable evidence must not assert a numeric or scalar value")
        if self.source is not None and self.availability == "known" and not self.content:
            raise ValueError("Known canonical claims require content")
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_semantics(self, handler):
        values = handler(self)
        if self.source is None:
            defaults = {
                "source": None,
                "vendor_claimed": False,
                "content": {},
                "extraction_ref": None,
                "proposal_id": None,
            }
            for field, default in defaults.items():
                if values.get(field) == default:
                    values.pop(field, None)
        else:
            for field in ("artifact_id", "line", "quote", "statement", "visibility"):
                values.pop(field, None)
        return values


class ClaimRecordBatch(StrictModel):
    claims: list[ClaimRecord] = Field(min_length=1)


class EvidenceReference(StrictModel):
    type: Literal["claim", "snapshot", "artifact"]
    id: UUID
    version: int = Field(gt=0)
    locator: str | None = Field(default=None, min_length=1)


class EvidenceTarget(StrictModel):
    type: Literal["proposal_item", "knowledge_entry", "definition_spec"]
    id: UUID
    version: int = Field(gt=0)


class EvidenceLinkCreate(StrictModel):
    evidence: EvidenceReference
    target: EvidenceTarget
    relation: str = Field(min_length=1)


class ClaimWithdraw(StrictModel):
    claim_id: UUID
    expected_version: int = Field(gt=0)
    reason: str = Field(min_length=1)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)


class ProposalShare(StrictModel):
    proposal_id: UUID
    expected_revision: int = Field(gt=0)
    visibility: Literal["category", "audience"]
    audience_ids: list[UUID]
    deidentified_confirmed: StrictBool
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def explicit_audience(self):
        if len(self.audience_ids) != len(set(self.audience_ids)):
            raise ValueError("Audience identities must be distinct")
        if self.visibility == "category" and self.audience_ids:
            raise ValueError("Category sharing must not also specify a named audience")
        if self.visibility == "audience" and not self.audience_ids:
            raise ValueError("Named audience sharing requires audience identities")
        return self


PAYLOADS = {
    "evidence.claim.record": ClaimRecord,
    "evidence.link.create": EvidenceLinkCreate,
    "evidence.claim.withdraw": ClaimWithdraw,
    "proposal.share": ProposalShare,
}
