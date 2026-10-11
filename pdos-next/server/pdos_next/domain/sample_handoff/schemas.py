"""Closed human event input; fixed sample chain and qualification come from the server."""

from datetime import UTC
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, field_validator, model_validator

from pdos_next.domain.professional_authority.schemas import DefinitionReference
from pdos_next.engines.supply_cost.common import FrozenDTO

Revision = Annotated[int, Field(ge=1, strict=True)]
PreviousRevision = Annotated[int, Field(ge=0, strict=True)]
Text = Annotated[str, Field(min_length=1, max_length=2000)]
Key = Annotated[str, Field(min_length=1, max_length=160)]


class SampleRef(FrozenDTO):
    id: UUID
    revision: Revision


class SampleReadinessPayload(FrozenDTO):
    sample_id: UUID
    expected_sample_revision: Revision
    previous_readiness_id: UUID | None = None
    expected_previous_revision: PreviousRevision = 0
    state: Literal["ready", "hold"]
    purpose: Key
    occurred_at: AwareDatetime
    occurred_timezone: Key
    event_source: DefinitionReference
    sources: tuple[DefinitionReference, ...] = Field(min_length=1)
    reason: Text
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @field_validator("occurred_at")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC)

    @field_validator("occurred_timezone")
    @classmethod
    def timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("实物事件须保留合法IANA时区") from error
        return value

    @field_validator("purpose", mode="before")
    @classmethod
    def exact_purpose(cls, value):
        if not isinstance(value, str) or value != value.strip() or not value.strip():
            raise ValueError("实物状态用途须精确非空，不能用空白改变专业授权范围")
        return value

    @model_validator(mode="after")
    def paired_previous(self) -> Self:
        if (self.previous_readiness_id is None) != (self.expected_previous_revision == 0):
            raise ValueError("初版前版null/0；继版须固定当前ready/hold事实ID及正版本")
        identities = [
            (ref.artifact_id, ref.expected_revision, ref.line, ref.quote) for ref in self.sources
        ]
        if len(set(identities)) != len(identities):
            raise ValueError("实物事实精确依据不能重复")
        return self
