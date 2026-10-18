"""Recipient declarations over one actual promise and submission."""

from typing import Literal

from pydantic import Field, field_validator

from pdos_next.domain.work_management.schemas import (
    ConfirmedPayload,
    ReviewCheck,
    VersionRef,
    unique_keys,
)

from .models import OPERATION


class CommitmentReviewPayload(ConfirmedPayload):
    commitment: VersionRef
    task: VersionRef
    submission: VersionRef
    expected_review_revision: int = Field(ge=0, strict=True)
    decision: Literal["accepted", "returned"]
    checks: tuple[ReviewCheck, ...] = Field(min_length=1)

    @field_validator("checks")
    @classmethod
    def distinct(cls, values):
        if not unique_keys(values):
            raise ValueError("Commitment checks cannot repeat an outcome")
        return values


PAYLOADS = {OPERATION: CommitmentReviewPayload}
