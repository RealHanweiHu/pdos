"""Closed follow-up bindings. Facts are populated by server owner readers only."""

from datetime import UTC
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, field_validator, model_validator

from pdos_next.domain.configurations.schemas import DefinitionReference
from pdos_next.domain.quality_execution.schemas import Revision, Sha256, SourceRead, Text, Token
from pdos_next.schemas.quality_issues.contracts import EffectivenessRequirement
from pdos_next.schemas.verification.contracts import DTO, EventTime, Scope, SourceRef

Nature = Literal["real", "synthetic"]
OutputKind = Literal[
    "definition",
    "bom",
    "engineering_configuration",
    "manufacturing_configuration",
    "build",
    "actual_configuration",
    "build_lot",
    "sample",
    "verification_preparation",
    "verification_request",
    "verification_run",
]


class FixedRef(DTO):
    id: UUID
    revision: Revision


class OutputRef(FixedRef):
    """id always denotes the immutable owner row, never a guessed logical identity."""

    kind: OutputKind
    key: Annotated[str, Field(min_length=1, max_length=120)] | None = None

    @model_validator(mode="after")
    def keyed(self):
        if self.key is not None and self.kind not in {"bom", "manufacturing_configuration"}:
            raise ValueError(
                "Only an actual fixed BOM line or manufacturing operation may have a key"
            )
        return self


class ActionBinding(DTO):
    action_id: UUID
    executor_id: UUID
    action_sha256: Sha256
    completion_sha256: Sha256 | None = None
    completed_at: EventTime | None = None

    @model_validator(mode="after")
    def completed(self):
        if (self.completion_sha256 is None) != (self.completed_at is None):
            raise ValueError("A completion clock must have its exact persisted completion digest")
        return self


class FollowupBasis(DTO):
    """A server-derived immutable Issue/CAPA anchor; payload copies are rechecked."""

    scope: Scope
    issue_id: UUID
    issue_version_id: UUID
    issue_revision: Revision
    capa_id: UUID
    purpose: Text
    owner_id: UUID
    visibility: Literal["private", "category", "audience"]
    nature: Nature
    requirement: EffectivenessRequirement
    requirement_sha256: Sha256
    failure_ids: tuple[Text, ...] = Field(min_length=1)
    failure_basis_sha256: Sha256
    actions: tuple[ActionBinding, ...] = Field(min_length=1)
    root_cause_sha256: Sha256 | None = None
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...] = Field(min_length=1)
    source_basis_sha256: Sha256
    basis_sha256: Sha256

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.failure_ids)) != len(self.failure_ids):
            raise ValueError("Failure identities must be unique")
        if tuple(sorted(self.failure_ids)) != self.failure_ids:
            raise ValueError("Failure identities must use stable sorted order")
        if len({a.action_id for a in self.actions}) != len(self.actions):
            raise ValueError("CAPA actions must have unique fixed identities")
        if set(self.failure_ids) != set(self.requirement.required_failure_ids):
            raise ValueError("CAPA requirement must cover the exact fixed Issue failure set")
        return self


class Missing(DTO):
    dimension: Literal[
        "source",
        "owner",
        "completion",
        "root_cause",
        "mapping",
        "execution",
        "results",
        "applicability",
        "independence",
        "observation",
        "policy",
    ]
    code: Annotated[str, Field(min_length=1, max_length=120)]
    detail: Text
    output_ref: OutputRef | None = None
    failure_id: Text | None = None


class OutputReading(DTO):
    ref: OutputRef
    logical_id: UUID | None = None
    project_id: UUID | None = None  # product-level configuration has no project identity
    owner_id: UUID
    visibility: Literal["private", "category", "audience"]
    title: Text
    status: Text
    meaning: Literal["draft", "planned", "observed", "performed"]
    source_status: Literal["current", "needs_recheck"]
    snapshot: dict[str, JsonValue]
    required_source_read_set: tuple[SourceRead, ...]
    owner_basis_sha256: Sha256
    missing: tuple[Missing, ...] = ()


class ResolvedOutputs(DTO):
    basis: FollowupBasis
    action_id: UUID
    outputs: tuple[OutputReading, ...] = Field(min_length=1)
    visibility: Literal["private", "category", "audience"]
    owner_id: UUID
    required_source_read_set: tuple[SourceRead, ...] = Field(min_length=1)
    source_basis_sha256: Sha256
    resolution_sha256: Sha256
    missing: tuple[Missing, ...] = ()
    # Resolving facts cannot certify that an action's free text was fulfilled.
    action_fulfilled: None = None


class FollowupLinkPayload(DTO):
    issue_id: UUID
    expected_issue_revision: Revision
    capa_id: UUID
    action_id: UUID
    output_refs: tuple[OutputRef, ...] = Field(min_length=1)
    sources: tuple[DefinitionReference, ...] = Field(default=())
    reason: Text
    confirmation_token: Token | None = None

    @model_validator(mode="after")
    def unique(self):
        if len({(r.kind, r.id, r.revision, r.key) for r in self.output_refs}) != len(
            self.output_refs
        ):
            raise ValueError("A follow-up output cannot repeat")
        return self


class RemediationLink(DTO):
    id: UUID
    revision: Literal[1] = 1
    basis: FollowupBasis
    action_id: UUID
    output_refs: tuple[OutputRef, ...] = Field(min_length=1)
    resolution_sha256: Sha256
    owner_id: UUID
    visibility: Literal["private", "category", "audience"]
    received_at: AwareDatetime
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...] = Field(min_length=1)
    reason: Text

    @field_validator("received_at")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC)


class FailurePairMapping(DTO):
    failure_id: Text
    run: OutputRef
    sample_id: UUID
    sample_revision: Revision
    actual_configuration_id: UUID
    actual_configuration_revision: Revision
    item_id: Annotated[str, Field(min_length=1, max_length=120)]
    measurement_id: UUID | None = None
    projection_id: UUID | None = None
    applicability_sources: tuple[DefinitionReference, ...] = Field(default=())

    @model_validator(mode="after")
    def run_only(self):
        if self.run.kind != "verification_run" or self.run.key is not None:
            raise ValueError("Failure mapping requires an exact immutable new Run row")
        return self


class CandidateBinding(DTO):
    basis: FollowupBasis
    remediation_link_refs: tuple[FixedRef, ...] = Field(default=())
    mappings: tuple[FailurePairMapping, ...] = Field(default=())

    @model_validator(mode="after")
    def mapping_scope(self):
        if any(m.failure_id not in self.basis.failure_ids for m in self.mappings):
            raise ValueError("A mapping cannot add a failure outside the fixed Issue")
        keys = {(m.failure_id, m.run.id, m.sample_id, m.item_id) for m in self.mappings}
        if len(keys) != len(self.mappings):
            raise ValueError("Failure to sample/item mappings cannot repeat")
        if len({r.id for r in self.remediation_link_refs}) != len(self.remediation_link_refs):
            raise ValueError("A remediation link cannot repeat")
        return self


class CandidateInspect(DTO):
    candidate_ref: FixedRef | None = None
    binding: CandidateBinding
    outputs: tuple[OutputReading, ...] = ()
    # These are missing owner facts, never inferred from client flags or Run pass.
    applicable: None = None
    independently_verified: None = None
    observation_complete: None = None
    observed_from: None = None
    observed_until: None = None
    result: Literal["indeterminate"] = "indeterminate"
    current: bool = Field(strict=True)
    required_source_read_set: tuple[SourceRead, ...] = Field(min_length=1)
    source_basis_sha256: Sha256
    inspection_sha256: Sha256
    missing: tuple[Missing, ...]
    capabilities: dict[Literal["effectiveness_decide", "issue_close"], Literal[False]] = Field(
        default_factory=lambda: {"effectiveness_decide": False, "issue_close": False}
    )
