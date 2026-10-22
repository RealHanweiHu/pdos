"""Narrow trusted result bridge. Absence never becomes a positive failure proof."""

from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from pdos_next.domain.quality_issues.ports import VerifiedRun
from pdos_next.schemas.verification.contracts import DTO, Scope, SourceRef

from .schemas import Revision, Sha256, SourceRead


class FixedQualityResult(DTO):
    scope: Scope
    purpose: str = Field(min_length=1, max_length=2000)
    event_id: UUID | None
    run_version_id: UUID
    run_revision: Revision
    measurement_id: UUID
    projection_id: UUID
    projection_revision: Revision
    basis_sha256: Sha256
    rules_version: str = Field(min_length=1, max_length=120)
    rules_sha256: Sha256
    verified: VerifiedRun
    visibility: Literal["private", "category", "audience"]
    owner_id: UUID
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...] = Field(min_length=1)
    source_basis: dict[str, JsonValue]
    retained: dict[str, JsonValue]
    current: bool
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def bound(self):
        if self.verified.run.scope != self.scope or self.verified.run.revision != self.run_revision:
            raise ValueError("Bridge must bind the exact archived Run scope/revision")
        if len([m for m in self.verified.run.measurements if m.id == self.measurement_id]) != 1:
            raise ValueError("Bridge must bind exactly one recorded measurement")
        return self


class FixedQualityScope(DTO):
    """RLS-owned result identity for a current authority check, never failure evidence."""

    scope: Scope
    purpose: str = Field(min_length=1, max_length=2000)
    run_id: UUID
    run_version_id: UUID
    run_revision: Revision
    event_id: UUID


class ResultBridge(Protocol):
    def __call__(
        self,
        s,
        ctx,
        product_id,
        *,
        run_id: UUID,
        measurement_id: UUID,
        event_id: UUID | None = None,
        run_revision: int | None = None,
        write: bool = False,
    ) -> FixedQualityResult: ...
