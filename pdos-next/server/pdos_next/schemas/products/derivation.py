"""Version 1 calculation DTOs; none represents an authorized business decision."""

from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from pdos_next.schema_base import StrictModel
from pdos_next.schemas.products.definitions import DefinitionReference, DefinitionSpec

CONTENT_FIELDS = (
    "purpose",
    "use_cases",
    "requirements",
    "constraints",
    "unknowns",
    "exclusions",
    "sources",
)
Classification = Literal["unchanged", "parent_only", "child_only", "same_change", "conflict"]


class DTO(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


class SourceReference(DefinitionReference):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


class SpecSnapshot(DefinitionSpec):
    """Reuse only the current public Spec validation, never a domain handler."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)
    test_conditions: tuple[str, ...] = Field(default=())
    sources: tuple[SourceReference, ...] = Field(min_length=1)

    @field_validator("value", "lower", "upper", "tolerance", mode="before")
    @classmethod
    def exact_decimal_input(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError("Use a Decimal, integer or exact decimal string, never a float")
        return value

    @field_validator("test_conditions")
    @classmethod
    def valid_conditions(cls, conditions):
        if any(not item.strip() or len(item) > 1000 for item in conditions):
            raise ValueError("Test conditions must be nonempty and at most 1000 characters")
        if len(set(conditions)) != len(conditions):
            raise ValueError("Duplicate test conditions")
        return tuple(conditions)


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
    sources: tuple[SourceReference, ...] | None = None
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
    description: str = Field(min_length=1, max_length=2000)


class Override(DTO):
    path: str
    operation: Literal["set", "delete"]
    reason: str = Field(min_length=3, max_length=2000)
    sources: tuple[SourceReference, ...] = Field(min_length=1)
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
    value: str | tuple[str, ...] | tuple[SourceReference, ...] | SpecSnapshot | None = None


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
    reason: str = Field(min_length=3, max_length=2000)
    sources: tuple[SourceReference, ...] = Field(min_length=1)
    scope: ApplicabilityScope


class ReuseCheck(DTO):
    path: str
    old_parent: SnapshotRef
    new_parent: SnapshotRef
    child: SnapshotRef
    sources: tuple[SourceReference, ...]
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
    sources: tuple[SourceReference, ...]
    scope: ApplicabilityScope
    origin_nature: str | None = None
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
