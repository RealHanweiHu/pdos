from datetime import UTC
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import AwareDatetime, BeforeValidator, Field, field_validator, model_validator

from pdos_next.domain.configurations.schemas import DefinitionReference
from pdos_next.engines.supply_cost.common import FrozenDTO, bounded_decimal
from pdos_next.schemas.verification.contracts import EventTime

Key = Annotated[str, Field(min_length=1, max_length=120)]
Text = Annotated[str, Field(min_length=1, max_length=2000)]
CriterionNumber = Annotated[
    Decimal, BeforeValidator(bounded_decimal), Field(max_digits=32, decimal_places=12)
]


class PreparationCriterion(FrozenDTO):
    lower: CriterionNumber | None = None
    upper: CriterionNumber | None = None
    source: DefinitionReference

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if self.lower is None and self.upper is None:
            raise ValueError("判据至少包含一个界限")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("判据上限不得小于下限")
        return self


class PreparationItem(FrozenDTO):
    id: Key
    feature: Text
    drawing: DefinitionReference | None = None
    method: DefinitionReference | None = None
    criterion: PreparationCriterion | None = None
    criterion_text: Text | None = None
    criterion_source: DefinitionReference | None = None
    unit: Key | None = None
    conditions: Text | None = None
    material: Text | None = None
    sample_count: int = Field(ge=1, le=10000, strict=True)
    cavities: tuple[Key, ...] = Field(default=())
    destructive: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def unique_cavities(self) -> Self:
        if len(self.cavities) != len(set(self.cavities)):
            raise ValueError("模穴范围不能重复")
        return self


class PreparationDocument(FrozenDTO):
    id: Key
    title: Text
    item_ids: tuple[Key, ...] = Field(min_length=1)
    source: DefinitionReference | None = None
    required: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def unique_items(self) -> Self:
        if len(self.item_ids) != len(set(self.item_ids)):
            raise ValueError("资料适用测试项不能重复")
        return self


class PreparationRecordPayload(FrozenDTO):
    request_id: UUID
    expected_request_revision: int = Field(ge=0, strict=True)
    build_id: UUID
    expected_build_revision: int = Field(ge=1, strict=True)
    title: Text
    purpose: Text
    return_form: Text
    items: tuple[PreparationItem, ...] = Field(min_length=1)
    documents: tuple[PreparationDocument, ...] = Field(default=())
    expected_at: AwareDatetime | None = None
    expected_timezone: Key | None = None
    tentative_at: AwareDatetime | None = None
    tentative_timezone: Key | None = None
    sources: tuple[DefinitionReference, ...] = Field(min_length=1)
    reason: Text
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @field_validator("expected_at", "tentative_at")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC) if value is not None else None

    @field_validator("expected_timezone", "tentative_timezone")
    @classmethod
    def zone(cls, value):
        return EventTime.timezone(value) if value is not None else None

    @model_validator(mode="after")
    def complete_scope(self) -> Self:
        for time, zone in (
            (self.expected_at, self.expected_timezone),
            (self.tentative_at, self.tentative_timezone),
        ):
            if (time is None) != (zone is None):
                raise ValueError("预期或暂定时点与原IANA时区须成对")
        keys = {item.id for item in self.items}
        if len(keys) != len(self.items):
            raise ValueError("测试项稳定ID不能重复")
        if len({document.id for document in self.documents}) != len(self.documents):
            raise ValueError("资料稳定ID不能重复")
        if any(not set(document.item_ids) <= keys for document in self.documents):
            raise ValueError("资料适用范围须在本版测试项内")
        if len(
            {(ref.artifact_id, ref.expected_revision, ref.line, ref.quote) for ref in self.sources}
        ) != len(self.sources):
            raise ValueError("精确原文来源不能重复")
        return self
