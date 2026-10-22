from datetime import UTC
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator

from pdos_next.engines.supply_cost.common import FrozenDTO


class LifecycleCommandPayload(FrozenDTO):
    candidate_id: UUID
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=2000)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)


class LifecycleCancelPayload(FrozenDTO):
    intent_id: UUID
    expected_revision: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=2000)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)


class LifecycleProtectionPayload(FrozenDTO):
    object_id: UUID
    expected_revision: int = Field(ge=1, strict=True)
    manual_hold: bool = Field(strict=True)
    retention_until: AwareDatetime
    reason: str = Field(min_length=1, max_length=2000)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @field_validator("retention_until")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC)
