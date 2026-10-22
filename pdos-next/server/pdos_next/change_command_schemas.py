"""Strict payload/owner DTOs separated from SQL model registration for cold imports."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from pdos_next.schemas.change_control.contracts import (
    ImplementationRecord,
    OrderApprove,
    OrderPrepare,
)
from pdos_next.schemas.verification.contracts import DTO, SourceRef


class Target(DTO):
    change_id: UUID
    expected_change_revision: int = Field(strict=True, ge=1)
    visibility: Literal["private", "category", "audience"] = "private"

    @model_validator(mode="before")
    @classmethod
    def exact_revisions(cls, value):
        def walk(v):
            if isinstance(v, dict):
                for k, x in v.items():
                    if k in {"revision", "expected_change_revision"} and (
                        type(x) is not int or x < 1
                    ):
                        raise ValueError("Every fixed revision requires a positive strict integer")
                    walk(x)
            elif isinstance(v, (list, tuple)):
                for x in v:
                    walk(x)

        walk(value)
        return value


class OrderPreparePayload(Target, OrderPrepare):
    confirmation_token: str | None = Field(default=None, min_length=16, max_length=512)


class OrderApprovePayload(Target, OrderApprove):
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    approval_token: str | None = Field(default=None, min_length=16, max_length=512)

    @model_validator(mode="after")
    def source_refs(self):
        if any(v.kind != "artifact" or type(v.revision) is not int for v in self.sources):
            raise ValueError("Named approval sources require exact registered original lines")
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("Exact sources cannot repeat")
        return self


class ImplementationPayload(Target, ImplementationRecord):
    confirmation_token: str | None = Field(default=None, min_length=16, max_length=512)


class CaptureInput(Target):
    capture_key: str = Field(min_length=8, max_length=160)
    order_id: UUID
    item_id: UUID
    source: SourceRef


class ControlledPolicy(DTO):
    """Trusted callback result; public payload cannot provide this object."""

    scope: dict
    purpose: str
    owner_id: UUID
    visibility: Literal["private", "category", "audience"]
    nature: Literal["real", "synthetic"]
    source: SourceRef
    required_disciplines: tuple[
        Literal["engineering", "manufacturing", "quality", "customer", "regulatory"], ...
    ]
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    epoch: int = Field(strict=True, ge=1)
    required_source_read_set: tuple[dict, ...] = Field(min_length=1)
    source_basis: dict
    owner_proof: dict  # Actual publisher's immutable group, not an input bool.


class SelectionProof(DTO):
    scope: dict
    item_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    nature: Literal["real", "synthetic"]
    applicable: Literal[True]
    valid_until: AwareDatetime | None = None
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    required_source_read_set: tuple[dict, ...] = Field(min_length=1)
    source_basis: dict
    owner_proof: dict
