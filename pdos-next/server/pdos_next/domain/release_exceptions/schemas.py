"""Closed declarations and owner inputs, never qualifications or signed facts."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from pdos_next.contracts import SourceRead
from pdos_next.domain.release.policy_schemas import PolicyMaterial
from pdos_next.domain.release.schemas import (
    DTO,
    Discipline,
    OriginalRef,
    PackagePlan,
    ReleaseCheck,
    ReleaseScope,
    SourcedText,
    SubjectConfiguration,
    Text,
    VersionRef,
)
from pdos_next.schemas.verification.contracts import Scope, SourceRef

from .constants import DECIDE, WITHDRAW

Token = Annotated[str, Field(min_length=20, max_length=128)]


class DecidePayload(DTO):
    basis_package: VersionRef
    discipline: Discipline
    release_scope: ReleaseScope
    purpose: Text
    check_keys: tuple[Text, ...] = Field(min_length=1)
    limits: tuple[SourcedText, ...] = Field(min_length=1)
    risk_controls: tuple[SourcedText, ...] = Field(min_length=1)
    expiry: AwareDatetime | None = None
    sources: tuple[OriginalRef, ...] = Field(min_length=1)
    reason: Text
    approval_token: Token | None = None

    @model_validator(mode="after")
    def fixed(self):
        if len(set(self.check_keys)) != len(self.check_keys):
            raise ValueError("Exception check identities cannot repeat")
        if not self.purpose.strip() or self.purpose != self.purpose.strip():
            raise ValueError("Exception purpose must preserve the explicit original string")
        return self


class WithdrawPayload(DTO):
    exception: VersionRef
    sources: tuple[OriginalRef, ...] = Field(min_length=1)
    reason: Text
    approval_token: Token | None = None


PAYLOADS = {DECIDE: DecidePayload, WITHDRAW: WithdrawPayload}


class ActualData(DTO):
    """Only the actual owner may bind these rows, policy and current watermarks."""

    package_ref: VersionRef
    package: PackagePlan
    package_current: bool | None
    policy_fact: VersionRef | None
    policy: PolicyMaterial | None
    policy_current: bool | None
    sources_current: bool | None
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...]


class ExceptionPlan(DTO):
    """An unexecuted candidate; common T2 and its immutable row prove signing."""

    structural_only: Literal[True] = True
    status: Literal["unexecuted_candidate"] = "unexecuted_candidate"
    operation: Literal["release.exception.decide", "release.exception.withdraw"]
    action: Literal["approved", "withdrawn"]
    declaration: dict[str, JsonValue]
    scope: Scope
    category_id: UUID
    owner_id: UUID
    visibility: Literal["private", "category", "audience"]
    discipline: Discipline
    basis_package: VersionRef
    policy_fact: VersionRef | None
    policy_version: Text | None
    subject_config: SubjectConfiguration
    release_scope: ReleaseScope
    purpose: Text
    check_keys: tuple[Text, ...] = Field(min_length=1)
    selected_checks: tuple[ReleaseCheck, ...]
    limits: tuple[SourcedText, ...] = Field(min_length=1)
    risk_controls: tuple[SourcedText, ...] = Field(min_length=1)
    expiry: AwareDatetime | None
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...]
    signers: tuple[UUID, ...] = Field(min_length=1)
    prepared_at: AwareDatetime
    previous: VersionRef | None = None
    reason: Text
    state: Literal["READY", "UNKNOWN", "BLOCKED"]
    unknown: tuple[Text, ...] = ()
    blocked: tuple[Text, ...] = ()


class WithdrawActualData(DTO):
    """The owner first proves the complete retained decision/common atom."""

    exception: VersionRef
    previous: ExceptionPlan
    current: bool | None
    sources_current: bool | None
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...]
