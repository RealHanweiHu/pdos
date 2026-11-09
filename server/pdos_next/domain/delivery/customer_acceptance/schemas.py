"""Closed T2 customer acceptance declarations (P97 第 5–8 项, C11, D309).

An internal named member registers what a customer's signed sample sheet
accepts, scope by scope: appearance, dimensions, performance, packaging and
labeling, certification documents. Each scope is accepted, conditionally
accepted, not accepted or not applicable, with optional conditions and expiry.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from pdos_next.domain.projects.work.schemas import DTO, Text, VersionRef
from pdos_next.schemas.verification.contracts import SourceRef

OPERATION = "customer.acceptance.record"
EVENT = "customer.acceptance_recorded"
SUBJECT = "customer_acceptance"
SCOPES = ("appearance", "dimensions", "performance", "packaging_labeling", "certification_docs")
STATES = ("accepted", "conditional", "not_accepted")
Short = Annotated[str, Field(min_length=1, max_length=200)]


class ScopeDecision(DTO):
    scope: Literal[
        "appearance", "dimensions", "performance", "packaging_labeling", "certification_docs"
    ]
    state: Literal["accepted", "conditionally_accepted", "not_accepted", "not_applicable"]
    conditions: list[Text] = Field(default_factory=list, max_length=20)
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("到期时间须带时区")
        return value

    @model_validator(mode="after")
    def conditional(self):
        if self.state == "conditionally_accepted" and not self.conditions:
            raise ValueError("条件承认须写明条件")
        if self.state in {"not_accepted", "not_applicable"} and (
            self.conditions or self.expires_at
        ):
            raise ValueError("未承认或不涉及的范围不带条件和到期日")
        return self


class Customer(DTO):
    label: Short
    goodjob_id: Short | None = None


class Payload(DTO):
    acceptance: VersionRef | None = None
    build_id: UUID | None = None
    expected_build_revision: int | None = Field(default=None, ge=1, strict=True)
    customer: Customer
    scopes: list[ScopeDecision] = Field(min_length=5, max_length=5)
    signed_sheet: SourceRef
    send_ref: VersionRef | None = None
    reason: Text
    approval_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def shape(self):
        if sorted(item.scope for item in self.scopes) != sorted(SCOPES):
            raise ValueError("五类范围须各登记一次：外观、尺寸、性能、包装标识、认证资料")
        if (self.acceptance is None) != (
            self.build_id is not None and self.expected_build_revision is not None
        ):
            raise ValueError("首次登记给出 Build；续登固定原承认记录版本")
        if self.signed_sheet.kind != "artifact":
            raise ValueError("签样单须是上传的原件")
        return self


PAYLOADS = {OPERATION: Payload}
