"""Closed quality wrappers: failure, risk, role and nature remain server facts."""

from datetime import UTC
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, field_validator, model_validator

from pdos_next.domain.professional_authority.schemas import ApprovalBasis, DefinitionReference
from pdos_next.schemas.quality_issues.contracts import (
    CapaDraft,
    ContainmentRecord,
    FailureRef,
    Issue,
    IssueCreate,
    IssueMerge,
    IssueTriage,
    Risk,
)
from pdos_next.schemas.verification.contracts import DTO, SourceRef

Revision = Annotated[int, Field(strict=True, ge=1)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, Field(min_length=1, max_length=2000)]
Token = Annotated[str, Field(min_length=20, max_length=128)]


class IssueCreatePayload(IssueCreate):
    visibility: Literal["private", "category", "audience"] = "private"


class IssueTarget(DTO):
    issue_id: UUID
    expected_issue_revision: Revision


class IssueMergePayload(IssueTarget, IssueMerge):
    confirmation_token: Token | None = None


class IssueTriagePayload(IssueTarget, IssueTriage):
    confirmation_token: Token | None = None


class ContainmentPayload(IssueTarget, ContainmentRecord):
    confirmation_token: Token | None = None


class CapaDraftPayload(IssueTarget, CapaDraft):
    """Hypotheses/actions only; completion and professional conclusions forbidden."""


class SourceRead(DTO):
    artifact_id: UUID
    expected_revision: Revision


class PolicyInput(DTO):
    """Trusted host input, never a public command or self-granted role."""

    product_id: UUID
    project_id: UUID
    external_id: Annotated[str, Field(min_length=1, max_length=200)]
    purpose: Text
    risk: Risk
    independent_verification: bool = Field(strict=True)
    state: Literal["active", "withdrawn"] = "active"
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    previous_id: UUID | None = None
    expected_previous_revision: int = Field(default=0, strict=True, ge=0)
    approval: ApprovalBasis
    sources: tuple[DefinitionReference, ...] = Field(min_length=1)
    reason: Text

    @field_validator("valid_from", "valid_until")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def binding(self):
        if self.valid_until <= self.valid_from:
            raise ValueError("Policy validity must be a complete increasing interval")
        if (self.previous_id is None) != (self.expected_previous_revision == 0):
            raise ValueError("Policy successor requires its exact previous identity/revision")
        keys = {(r.artifact_id, r.expected_revision, r.line, r.quote) for r in self.sources}
        if len(keys) != len(self.sources):
            raise ValueError("Policy evidence cannot repeat")
        return self


class CurrentIssue(DTO):
    issue_version_id: UUID
    revision: Revision


class FailureReading(DTO):
    failure: FailureRef
    available: bool
    measurement: dict[str, JsonValue] | None = None
    projection_id: UUID | None = None
    basis_sha256: Sha256 | None = None
    event_ids: tuple[UUID, ...] = ()
    reason_codes: tuple[str, ...] = ()
    required_source_read_set: tuple[SourceRead, ...] = ()
    capabilities: dict[str, bool] = {}
    authority: dict[str, JsonValue] = {}


class IssueView(DTO):
    id: UUID  # immutable version row, common Receipt subject
    issue_id: UUID  # stable logical identity, command target
    revision: Revision
    project_id: UUID
    purpose: Text
    visibility: Literal["private", "category", "audience"]
    owner_id: UUID
    status: str
    issue: Issue
    is_current: bool
    source_status: Literal["current", "needs_recheck", "unavailable", "not_evaluated_historical"]
    failures: tuple[FailureReading, ...] = ()
    capabilities: dict[str, bool]
    authority: dict[str, JsonValue]
    policy: dict[str, JsonValue] | None = None
    required_source_read_set: tuple[SourceRead, ...]
    sources: tuple[SourceRef, ...]
    created_at: AwareDatetime
    reason: Text
    followup_needs: tuple[dict[str, JsonValue], ...] = ()


class QualityReading(DTO):
    issues: tuple[IssueView, ...]
    current_by_issue: dict[str, CurrentIssue]
    failures: tuple[FailureReading, ...] = ()
    policy: dict[str, JsonValue] | None = None
    next_owners: tuple[dict[str, JsonValue], ...] = ()
    capabilities: dict[str, bool]
    unavailable_count: int = Field(ge=0)
    has_more: bool
