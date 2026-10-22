"""Version 1 calculation DTOs; none represents an authorized business decision."""

from decimal import Decimal
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import AliasChoices, ConfigDict, Field, field_validator, model_validator

from pdos_next.schema_base import StrictModel
from pdos_next.schemas.products.definitions import DefinitionReference
from pdos_next.schemas.spec_values import numeric_value_shape

CONTENT_FIELDS = (
    "purpose",
    "use_cases",
    "requirements",
    "constraints",
    "unknowns",
    "exclusions",
    "sources",
    "source_refs",
)
Classification = Literal["unchanged", "parent_only", "child_only", "same_change", "conflict"]


class DTO(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


class SourceReference(DefinitionReference):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


class ObjectReference(DTO):
    """An exact M3 object reference; descriptive evidence never grants read authority."""

    type: Literal[
        "human", "artifact", "original", "snapshot", "knowledge", "parameter", "definition", "claim"
    ]
    id: UUID
    version: int = Field(gt=0)
    line: int | None = Field(default=None, gt=0)
    quote: str | None = None
    statement: str | None = None


Reference = SourceReference | ObjectReference


class SpecSnapshot(DTO):
    """Lossless calculation input, including incomplete G0 specifications.

    This is not a publication/write schema: missing units, evidence or conditions
    are diagnostics, and cannot make an otherwise readable snapshot uncomputable.
    """

    key: str = Field(min_length=1)
    parameter: str
    value_type: Literal["number", "range", "text", "boolean", "enum"]
    availability: Literal["known", "unknown", "conflicted", "not_applicable"] = "unknown"
    value: Decimal | None = None
    lower: Decimal | None = None
    upper: Decimal | None = None
    tolerance: Decimal | None = None
    text: str | None = Field(default=None, validation_alias=AliasChoices("text", "text_value"))
    unit: str | None = None
    test_conditions: tuple[str, ...] = ()
    method: str | None = Field(
        default=None, validation_alias=AliasChoices("method", "verification_method")
    )
    acceptance_criterion: str | None = None
    nature: Literal["observed", "extracted", "computed", "inferred", "decided"] = "extracted"
    state: Literal["proposed", "needs_confirmation"] = "needs_confirmation"
    owner_id: UUID | None = None
    reason: str | None = None
    sources: tuple[Reference, ...] = ()
    parameter_id: UUID | None = None
    parameter_version: int | None = Field(default=None, gt=0)
    item_status: Literal["ai_draft", "confirmed", "expert_pending", "unknown"] = "unknown"
    condition_note: str | None = None
    modality: Literal["must", "should", "may", "prohibited", "unstated"] | None = None
    exceptions: tuple[dict, ...] = ()
    applicable_variants: tuple[dict, ...] = ()
    source_refs: tuple[Reference, ...] = ()
    origin: str | None = None
    writer_id: UUID | None = None
    run_id: UUID | None = None
    confirmed_by: UUID | None = None
    receipt_id: UUID | None = None

    @field_validator("value", "lower", "upper", "tolerance", mode="before")
    @classmethod
    def exact_decimal_input(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError("Use a Decimal, integer or exact decimal string, never a float")
        return value

    @field_validator("value", "lower", "upper", "tolerance")
    @classmethod
    def finite_decimal(cls, value):
        if value is not None and not value.is_finite():
            raise ValueError("Specification decimals must be finite")
        return value

    @model_validator(mode="after")
    def consistent_values(self) -> Self:
        if (self.parameter_id is None) != (self.parameter_version is None):
            raise ValueError("Parameter identity and version must be supplied together")
        values = (self.value, self.lower, self.upper, self.text)
        if self.availability != "known" and any(value is not None for value in values):
            raise ValueError("Unknown values must remain absent")
        if self.availability == "known":
            valid = {
                "number": numeric_value_shape(
                    self.value_type, self.value, self.lower, self.upper, self.text
                ),
                "range": numeric_value_shape(
                    self.value_type, self.value, self.lower, self.upper, self.text
                ),
                "text": self.text is not None and all(v is None for v in values[:3]),
                "enum": self.text is not None and all(v is None for v in values[:3]),
                "boolean": self.text in {"true", "false"} and all(v is None for v in values[:3]),
            }[self.value_type]
            if not valid:
                raise ValueError("Specification value shape does not match value_type")
        if self.tolerance is not None and self.tolerance < 0:
            raise ValueError("Tolerance must be nonnegative")
        return self


class SnapshotRef(DTO):
    definition_id: UUID
    revision: int = Field(ge=1, strict=True)
    category_id: UUID
    product_id: UUID
    variant_id: UUID | None = None


class DefinitionContent(DTO):
    """Sections may be absent or explicitly null; specs is a complete keyed collection."""

    purpose: str | None = None
    use_cases: tuple[str, ...] | None = None
    requirements: tuple[str, ...] | None = None
    constraints: tuple[str, ...] | None = None
    unknowns: tuple[str, ...] | None = None
    exclusions: tuple[str, ...] | None = None
    sources: tuple[Reference, ...] | None = None
    source_refs: tuple[Reference, ...] | None = None
    specs: tuple[SpecSnapshot, ...] = Field(default=())
    deleted_fields: tuple[str, ...] = ()

    @model_validator(mode="after")
    def unique_keys_and_tombstones(self) -> Self:
        if len({spec.key for spec in self.specs}) != len(self.specs):
            raise ValueError("Duplicate specification key")
        if len(set(self.deleted_fields)) != len(self.deleted_fields):
            raise ValueError("Duplicate deleted field")
        for name in self.deleted_fields:
            if name not in CONTENT_FIELDS or name in self.model_fields_set:
                raise ValueError("Deleted field must be an absent inheritable section")
        if self.sources is not None:
            refs = set(self.sources)
            if len(refs) != len(self.sources):
                raise ValueError("Duplicate definition source")
        return self


class DefinitionSnapshot(DTO):
    ref: SnapshotRef
    content: DefinitionContent
    # Local identity and decisions stay outside inheritable content.
    title: str
    status: str
    owner_id: UUID | None = None
    published_by: UUID | None = None
    approval_ids: tuple[UUID, ...] = ()


class ApplicabilityScope(DTO):
    """Descriptive requested scope, not an ACL, grant or applicability determination."""

    category_id: UUID
    product_id: UUID
    variant_id: UUID | None = None
    description: str = Field(min_length=1)


class Override(DTO):
    path: str
    operation: Literal["set", "delete"]
    reason: str = Field(min_length=1)
    sources: tuple[Reference, ...] = ()
    scope: ApplicabilityScope


class DerivationRequest(DTO):
    schema_version: Literal["derivation.v1"] = "derivation.v1"
    old_parent: DefinitionSnapshot
    new_parent: DefinitionSnapshot
    child: DefinitionSnapshot
    pinned_parent: SnapshotRef
    overrides: tuple[Override, ...] = ()


class PathValue(DTO):
    state: Literal["missing", "deleted", "null", "unknown", "value"]
    value: str | tuple[str, ...] | tuple[Reference, ...] | SpecSnapshot | None = None


class Diagnostic(DTO):
    path: str
    code: str
    detail: str


class Difference(DTO):
    path: str
    old_parent: PathValue
    new_parent: PathValue
    child: PathValue
    classification: Classification
    changed_fields: tuple[str, ...] = ()
    reconfirmation: tuple[str, ...] = ()
    override: Override | None = None


class DerivationResult(DTO):
    schema_version: Literal["derivation.v1"] = "derivation.v1"
    request_digest: str
    old_parent: SnapshotRef
    new_parent: SnapshotRef
    child: SnapshotRef
    differences: tuple[Difference, ...]
    missing: tuple[Diagnostic, ...]


class AdoptionSelection(DTO):
    """Binding to an exact calculation prevents accepting a stale path list."""

    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    paths: tuple[str, ...] = Field(min_length=1)
    resolve_conflicts: tuple[str, ...] = ()
    reason: str = Field(min_length=1)
    sources: tuple[Reference, ...] = Field(min_length=1)
    scope: ApplicabilityScope


class ReuseCheck(DTO):
    path: str
    old_parent: SnapshotRef
    new_parent: SnapshotRef
    child: SnapshotRef
    sources: tuple[Reference, ...]
    scope: ApplicabilityScope


class ReuseAssessment(DTO):
    audience: Literal["allowed", "denied", "unknown"]
    cross_customer: Literal["allowed", "not_required", "denied", "unknown"]
    applicability: Literal["applicable", "not_applicable", "unknown"]
    basis: tuple[str, ...] = Field(min_length=1)


class ReuseValidationPort(Protocol):
    """Mainline supplies authoritative checks; request values never grant access."""

    def assess(self, check: ReuseCheck) -> ReuseAssessment: ...


class AdoptionTrace(DTO):
    path: str
    source_parent: SnapshotRef
    reason: str
    sources: tuple[Reference, ...]
    scope: ApplicabilityScope
    origin_nature: str | None = None
    source_spec: SpecSnapshot | None = None
    assessment: ReuseAssessment | None = None


class AdoptionCandidate(DTO):
    schema_version: Literal["derivation.v1"] = "derivation.v1"
    kind: Literal["calculation_candidate"] = "calculation_candidate"
    request_digest: str
    based_on_child: SnapshotRef
    pinned_parent: SnapshotRef
    # Selective adoption does not claim that every path now matches the new parent.
    offered_parent: SnapshotRef
    content: DefinitionContent
    overrides: tuple[Override, ...]
    traces: tuple[AdoptionTrace, ...]
    missing: tuple[Diagnostic, ...]
    required_authority_checks: tuple[str, ...] = (
        "fixed_snapshot_versions",
        "source_audience",
        "cross_customer_permission",
        "applicability",
        "child_responsibility",
        "command_confirmation",
    )
