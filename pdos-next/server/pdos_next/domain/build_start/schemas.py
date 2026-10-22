"""Closed execution inputs; scope facts, professional roles and readiness are server bound."""

from datetime import UTC
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, field_validator, model_validator

from pdos_next.domain.configurations.schemas import DefinitionReference
from pdos_next.engines.supply_cost.common import FrozenDTO, Positive
from pdos_next.schemas.resource_readiness.contracts import ExecutionWindow

Text = Annotated[str, Field(min_length=1, max_length=2000)]
Key = Annotated[str, Field(min_length=1, max_length=160)]
Revision = Annotated[int, Field(ge=1, strict=True)]
PreviousRevision = Annotated[int, Field(ge=0, strict=True)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class BuildExecutionScope(FrozenDTO):
    purpose: Key
    quantity: Positive
    unit: Key
    site: Key
    window_start: AwareDatetime
    window_end: AwareDatetime
    window_timezone: Key

    @field_validator("window_start", "window_end")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_window(self) -> Self:
        self.execution_window()
        return self

    def execution_window(self):
        return ExecutionWindow(
            start=self.window_start,
            finish=self.window_end,
            original_timezone=self.window_timezone,
        )


class BuildAssessmentPayload(FrozenDTO):
    build_id: UUID
    expected_build_revision: Revision
    execution_scope: BuildExecutionScope
    previous_assessment_id: UUID | None = None
    expected_previous_revision: PreviousRevision = 0
    reason: Text

    @model_validator(mode="after")
    def previous(self) -> Self:
        if (self.previous_assessment_id is None) != (self.expected_previous_revision == 0):
            raise ValueError("初评为null/0；复评必须固定当前评估ID和正版本")
        return self


Control = Literal[
    "no_test_run_or_sample_qualification",
    "no_external_delivery",
    "retain_traceable_outputs",
    "stop_on_configuration_deviation",
]


class ProfessionalApplicability(FrozenDTO):
    rule_id: Literal[
        "product_definition_applicability",
        "verification_objective_applicability",
        "process_configuration_applicability",
        "output_disposition_applicability",
    ]
    status: Literal["applicable", "unknown", "blocked"]
    sources: tuple[DefinitionReference, ...] = Field(default=())
    valid_until: AwareDatetime | None = None
    reason: Text

    @field_validator("valid_until")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC) if value is not None else None


class BuildAuthorizationPayload(FrozenDTO):
    assessment_id: UUID
    expected_assessment_revision: Revision
    expected_assessment_sha256: Sha256
    action: Literal["approve", "revoke"]
    previous_decision_id: UUID | None = None
    expected_previous_revision: PreviousRevision = 0
    valid_until: AwareDatetime | None = None
    professional_assessments: tuple[ProfessionalApplicability, ...] = Field(default=())
    accepted_controls: tuple[Control, ...] = Field(default=())
    sources: tuple[DefinitionReference, ...] = Field(min_length=1)
    reason: Text
    approval_token: str | None = Field(default=None, min_length=20, max_length=128)

    @field_validator("valid_until")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def previous(self) -> Self:
        if (self.previous_decision_id is None) != (self.expected_previous_revision == 0):
            raise ValueError("首次决定为null/0；后续决定必须固定当前ID和正版本")
        if len(set(self.accepted_controls)) != len(self.accepted_controls):
            raise ValueError("执行约束不能重复")
        if len({item.rule_id for item in self.professional_assessments}) != len(
            self.professional_assessments
        ):
            raise ValueError("专业适用项不能重复")
        return self


class BuildStartPayload(FrozenDTO):
    assessment_id: UUID
    expected_assessment_revision: Revision
    expected_assessment_sha256: Sha256
    engineering_authorization_id: UUID
    expected_engineering_authorization_revision: Revision
    manufacturing_authorization_id: UUID
    expected_manufacturing_authorization_revision: Revision
    occurred_at: AwareDatetime
    occurred_timezone: Key
    event_source: DefinitionReference
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
            raise ValueError("实际发生时间必须保留合法IANA时区") from error
        return value
