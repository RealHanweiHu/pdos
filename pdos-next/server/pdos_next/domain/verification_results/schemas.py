"""Closed wrapper inputs: measurements, authority and computed results are server facts."""

from uuid import UUID

from pydantic import Field, model_validator

from pdos_next.domain.configurations.schemas import DefinitionReference
from pdos_next.domain.verification_front.schemas import Revision, Sha256, Text
from pdos_next.schemas.verification.contracts import DTO, EventTime


class ObservationSelection(DTO):
    line: int = Field(strict=True, ge=1)
    sample_id: UUID
    item_id: str = Field(min_length=1, max_length=120)


class CaptureInput(DTO):
    capture_key: str = Field(min_length=8, max_length=200)
    expected_product_revision: Revision
    request_id: UUID
    expected_request_revision: Revision
    run_id: UUID
    expected_run_revision: Revision
    report_artifact_id: UUID
    expected_report_revision: Revision
    selections: tuple[ObservationSelection, ...] = Field(min_length=1)
    reason: Text

    @model_validator(mode="after")
    def unique(self):
        if len({(v.sample_id, v.item_id) for v in self.selections}) != len(self.selections):
            raise ValueError("One original observation per fixed sample/item pair")
        if len({v.line for v in self.selections}) != len(self.selections):
            raise ValueError("An original report line cannot be assigned to multiple pairs")
        return self


class ResultBase(DTO):
    request_id: UUID
    expected_request_revision: Revision
    run_id: UUID
    expected_run_revision: Revision
    reason: Text


class ImportPayload(ResultBase):
    capture_id: UUID | None = None
    expected_capture_revision: Revision | None = None
    final: bool = Field(default=False, strict=True)
    at: EventTime
    actual_end: EventTime | None = None
    incomplete_reason: Text | None = None
    next_owner_id: UUID | None = None
    sources: tuple[DefinitionReference, ...] = Field(default=())
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def complete(self):
        if (self.capture_id is None) != (self.expected_capture_revision is None):
            raise ValueError("Capture identity and revision must be supplied together")
        if not self.final and self.capture_id is None:
            raise ValueError("A partial return needs a real observation capture")
        if self.final != (self.actual_end is not None):
            raise ValueError("Only a final return must carry the actual end event")
        if (self.incomplete_reason is None) != (self.next_owner_id is None):
            raise ValueError("Incomplete reason and next owner must be supplied together")
        if self.final and self.next_owner_id is not None:
            raise ValueError("A final return cannot assign unfinished responsibility")
        return self


class ComputePayload(ResultBase):
    expected_basis_sha256: Sha256


class ReviewPayload(ResultBase):
    projection_id: UUID
    expected_projection_revision: Revision
    expected_basis_sha256: Sha256
    text: Text
    at: EventTime
    sources: tuple[DefinitionReference, ...] = Field(default=())
    approval_token: str | None = Field(default=None, min_length=20, max_length=128)


class DispositionPayload(ReviewPayload):
    """A named conclusion about this Run; no resource release or external approval."""
