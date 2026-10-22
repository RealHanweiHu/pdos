"""Closed wrappers; human identity, policy and proof identity remain server facts."""

from datetime import UTC
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from pdos_next.domain.quality_execution.schemas import (
    IssueTarget,
    Revision,
    Sha256,
    SourceRead,
    Text,
    Token,
)
from pdos_next.schemas.quality_issues.contracts import ActionsComplete, Containment, RootCauseDecide
from pdos_next.schemas.verification.contracts import DTO, EventTime, Scope, SourceRef


class ExactSource(SourceRef):
    revision: Revision


class CompletionTime(EventTime):
    source: ExactSource

    @model_validator(mode="after")
    def no_effective_clock(self):
        if self.effective_at is not None:
            raise ValueError("An actually completed action cannot specify an effective clock")
        return self


class Completion(Containment):
    evidence: tuple[ExactSource, ...] = Field(min_length=1)
    at: CompletionTime


class RootCausePayload(IssueTarget, RootCauseDecide):
    sources: tuple[ExactSource, ...] = Field(min_length=1)
    approval_token: Token | None = None

    @field_validator("sources")
    @classmethod
    def unique_sources(cls, value):
        keys = [(s.kind, s.id, s.revision, s.position) for s in value]
        if len(keys) != len(set(keys)):
            raise ValueError("Root cause evidence cannot repeat")
        return tuple(sorted(value, key=lambda s: (s.kind, str(s.id), s.revision, s.position)))


class ActionsCompletePayload(IssueTarget, ActionsComplete):
    completions: tuple[Completion, ...] = Field(min_length=1)
    confirmation_token: Token | None = None

    @field_validator("completions")
    @classmethod
    def stable_order(cls, value):
        return tuple(sorted(value, key=lambda item: str(item.id)))


class CompletionFact(DTO):
    """Exact JSON line, not an authority assertion or a model-generated conclusion."""

    issue_id: UUID
    capa_id: UUID
    action_id: UUID
    executor_id: UUID
    operation: Literal["quality.capa.actions.complete"]
    occurred_at: AwareDatetime
    original_timezone: str = Field(min_length=1, max_length=120)
    purpose: Text
    text: Text

    @field_validator("occurred_at")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC)

    @field_validator("occurred_at", mode="before")
    @classmethod
    def source_iso(cls, value):
        if not isinstance(value, str):
            raise ValueError("Observed JSON clock must be an ISO timestamp string")
        return value

    @field_validator("original_timezone")
    @classmethod
    def timezone(cls, value):
        return EventTime.timezone(value)


class OwnerImplementationProof(DTO):
    kind: Literal["approved_change_implementation"]
    id: UUID
    revision: Revision
    receipt_id: UUID
    sha256: Sha256
    status: Literal["implemented"]
    current: Literal[True]

    @field_validator("current", mode="before")
    @classmethod
    def true_boolean(cls, value):
        if type(value) is not bool or value is not True:
            raise ValueError("Owner proof must be actually current, not a truthy value")
        return value


class CompletionAssessment(DTO):
    """Trusted host decision, never accepted from a command payload."""

    scope: Scope
    issue_id: UUID
    capa_id: UUID
    action_id: UUID
    executor_id: UUID
    purpose: Text
    basis_sha256: Sha256
    action_sha256: Sha256
    completion_sha256: Sha256
    event_source: ExactSource
    policy_basis_sha256: Sha256
    allowed: bool = Field(strict=True)
    current: bool = Field(strict=True)
    classification: Literal["investigation", "formal_change", "unknown"]
    nature: Literal["real", "synthetic"]
    reason_codes: tuple[str, ...] = ()
    sources: tuple[ExactSource, ...] = Field(min_length=1)
    owner_proofs: tuple[OwnerImplementationProof, ...] = ()
    required_source_read_set: tuple[SourceRead, ...] = Field(min_length=1)
    valid_until: AwareDatetime | None = None
    time_constraints: tuple[AwareDatetime, ...] = ()
    proof_sha256: Sha256


class CurrentIssue(DTO):
    issue_version_id: UUID
    revision: Revision


class FollowupReading(DTO):
    # Issue view JSON follows quality_execution.IssueView with two new exact caps.
    issues: tuple[dict, ...]
    current_by_issue: dict[str, CurrentIssue]
    capabilities: dict[str, bool]
    unavailable_count: int = Field(ge=0)
    has_more: bool
