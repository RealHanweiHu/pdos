from datetime import UTC, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_serializer, model_validator

from pdos_next.domain.build_start.schemas import BuildExecutionScope
from pdos_next.engines.supply_cost.common import Positive
from pdos_next.schema_base import StrictModel


class BuildCreatePayload(StrictModel):
    project_id: UUID
    expected_project_revision: int = Field(ge=1)
    engineering_configuration_id: UUID
    manufacturing_configuration_id: UUID
    name: str = Field(min_length=2, max_length=160)
    type: Literal["prototype", "tool_trial", "pilot"]
    purpose: str = Field(min_length=3, max_length=2000)
    planned_quantity: Positive
    unit: str = Field(min_length=1, max_length=80)
    planned_start: datetime | None = None
    planned_end: datetime | None = None
    verification_objectives: str = Field(min_length=3, max_length=2000)
    disposition_plan: str = Field(min_length=3, max_length=2000)
    previous_build_id: UUID | None = None
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @field_validator("planned_start", "planned_end")
    @classmethod
    def aware_time(cls, value):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("计划时间须明确时区")
            return value.astimezone(UTC)
        return value

    @model_validator(mode="after")
    def ordered_times(self) -> Self:
        if self.planned_start and self.planned_end and self.planned_end < self.planned_start:
            raise ValueError("计划结束不得早于计划开始")
        return self


class BuildReadinessPayload(StrictModel):
    build_id: UUID
    expected_build_revision: int = Field(ge=1)
    execution_scope: BuildExecutionScope | None = None
    previous_assessment_id: UUID | None = None
    expected_previous_revision: int = Field(default=0, ge=0, strict=True)
    reason: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def execution_fields(self) -> Self:
        if self.execution_scope is None:
            if self.reason or self.previous_assessment_id or self.expected_previous_revision:
                raise ValueError("执行评估字段须与明确execution_scope同时提供")
        elif self.reason is None or (
            (self.previous_assessment_id is None) != (self.expected_previous_revision == 0)
        ):
            raise ValueError("执行评估须提供原因及成对的前版ID/版本")
        return self

    @model_serializer(mode="wrap")
    def preserve_preparation_payload(self, handler):
        value = handler(self)
        if self.execution_scope is None:
            for key in (
                "execution_scope",
                "previous_assessment_id",
                "expected_previous_revision",
                "reason",
            ):
                value.pop(key, None)
        return value
