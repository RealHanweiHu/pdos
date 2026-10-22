"""Closed wrappers: no authority, milestones, configuration or reservation from payload."""

from datetime import UTC
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from pdos_next.domain.configurations.schemas import DefinitionReference
from pdos_next.engines.supply_cost.common import FrozenDTO
from pdos_next.schemas.resource_readiness.contracts import ExecutionWindow

Text = Annotated[str, Field(min_length=1, max_length=2000)]
Key = Annotated[str, Field(min_length=1, max_length=120)]
Revision = Annotated[int, Field(ge=1, strict=True)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class RequestCreatePayload(FrozenDTO):
    request_id: UUID
    preparation_id: UUID
    expected_preparation_revision: Revision
    preparation_sha256: Sha256
    reason: Text


class ItemAssessment(FrozenDTO):
    item_id: Key
    status: Literal["applicable", "not_applicable", "unknown"]
    conditions: tuple[Text, ...] = Field(default=())
    reason: Text
    sources: tuple[DefinitionReference, ...] = Field(default=())

    @model_validator(mode="after")
    def positive_evidence(self) -> Self:
        if self.status == "applicable" and not self.sources:
            raise ValueError("专业适用结论必须有精确原文依据")
        return self


class MethodPreparePayload(FrozenDTO):
    request_id: UUID
    expected_request_revision: Revision
    assessments: tuple[ItemAssessment, ...] = Field(min_length=1)
    reason: Text
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def unique_items(self) -> Self:
        if len({item.item_id for item in self.assessments}) != len(self.assessments):
            raise ValueError("每个固定测试项只能有一个专业适用结论")
        return self


class ResourceIntent(FrozenDTO):
    kind: Literal["equipment", "fixture", "person", "line", "tooling"]
    label: Text
    resource_id: UUID | None = None
    expected_revision: Revision | None = None
    units: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=12)

    @model_validator(mode="after")
    def paired_identity(self) -> Self:
        if (self.resource_id is None) != (self.expected_revision is None):
            raise ValueError("资源身份和固定版本须成对")
        return self


class ScheduleProposePayload(FrozenDTO):
    request_id: UUID
    expected_request_revision: Revision
    start: AwareDatetime
    finish: AwareDatetime
    original_timezone: Key
    resource_intents: tuple[ResourceIntent, ...] = Field(default=())
    duration_basis: DefinitionReference | None = None
    calendar_source: DefinitionReference | None = None
    sources: tuple[DefinitionReference, ...] = Field(default=())
    reason: Text

    @field_validator("start", "finish")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def window(self) -> Self:
        ExecutionWindow(
            start=self.start, finish=self.finish, original_timezone=self.original_timezone
        )
        identities = [item.resource_id for item in self.resource_intents if item.resource_id]
        if len(set(identities)) != len(identities):
            raise ValueError("资源意向不能重复固定身份")
        return self
