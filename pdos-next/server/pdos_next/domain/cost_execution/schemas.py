from datetime import UTC
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from pdos_next.domain.configurations.schemas import DefinitionReference
from pdos_next.engines.supply_cost.common import Currency, FrozenDTO, Loss, Positive, Quantity
from pdos_next.engines.supply_cost.dto import CostScope, MaterialPrice


class _Sourced(FrozenDTO):
    sources: list[DefinitionReference] = Field(min_length=1)

    @model_validator(mode="after")
    def exact_sources(self) -> Self:
        if len(
            {(ref.artifact_id, ref.expected_revision, ref.line, ref.quote) for ref in self.sources}
        ) != len(self.sources):
            raise ValueError("精确原文来源不能重复")
        return self


class PriceInput(_Sourced):
    price_id: str = Field(min_length=1, max_length=160)
    subject_kind: Literal["material", "process", "nre"]
    subject_id: str = Field(min_length=1, max_length=200)
    stage: Literal["estimate", "quote"]
    basis: Literal["unit", "nre"]
    amount: Quantity | None = None
    price_quantity: Positive | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=80)
    currency: Currency | None = None
    tax_basis: Literal["exclusive", "inclusive", "unknown"] = "unknown"
    tax_rate: Loss | None = None
    freight_basis: Literal["included", "excluded", "unknown"] = "unknown"
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None
    minimum_quantity: Quantity | None = None
    maximum_quantity: Positive | None = None
    scope_assumption: str = Field(min_length=1, max_length=500)

    @field_validator("valid_from", "valid_until")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC) if value is not None else None


class ProcessOperationInput(_Sourced):
    operation_id: str = Field(min_length=1, max_length=80)
    quantity_per_product: Quantity | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=80)
    loss_rate: Loss | None = None
    price_id: str | None = Field(default=None, min_length=1, max_length=160)


class ProcessInput(_Sourced):
    assumption: str = Field(min_length=1, max_length=500)
    operations: list[ProcessOperationInput] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_keys(self) -> Self:
        if len({row.operation_id for row in self.operations}) != len(self.operations):
            raise ValueError("固定制造工序不能重复")
        return self


class RateInput(_Sourced):
    rate_id: str = Field(min_length=1, max_length=160)
    from_currency: Currency
    to_currency: Currency
    rate: Positive | None = None
    purpose: Literal["spot", "budget"]
    observed_at: AwareDatetime

    @field_validator("observed_at")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC)


class CostCaptureInput(_Sourced):
    capture_key: str = Field(min_length=8, max_length=160)
    expected_product_revision: int = Field(ge=1, strict=True)
    build_id: UUID
    expected_build_revision: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=3, max_length=2000)
    cost_scope: CostScope
    prices: list[PriceInput] = Field(default_factory=list)
    material_prices: list[MaterialPrice] = Field(default_factory=list)
    process: ProcessInput | None = None
    rates: list[RateInput] = Field(default_factory=list)
    nre_price_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_selections(self) -> Self:
        for rows, key in (
            (self.prices, "price_id"),
            (self.rates, "rate_id"),
            (self.material_prices, "bom_item_id"),
        ):
            if len({getattr(row, key) for row in rows}) != len(rows):
                raise ValueError("价格、汇率和BOM映射的稳定身份不能重复")
        if len(set(self.nre_price_ids)) != len(self.nre_price_ids):
            raise ValueError("NRE价格不能重复选择")
        return self


class InputsRecordPayload(FrozenDTO):
    build_id: UUID
    expected_build_revision: int = Field(ge=1, strict=True)
    capture_id: UUID
    expected_capture_revision: int = Field(ge=1, strict=True)
    expected_previous_input_id: UUID | None = None
    expected_previous_revision: int | None = Field(default=None, ge=1, strict=True)
    reason: str = Field(min_length=3, max_length=2000)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def previous_pair(self) -> Self:
        if (self.expected_previous_input_id is None) != (self.expected_previous_revision is None):
            raise ValueError("前版成本输入ID与版本须成对，首版均为null")
        return self


class EstimateComputePayload(FrozenDTO):
    build_id: UUID
    expected_build_revision: int = Field(ge=1, strict=True)
    cost_input_id: UUID
    expected_cost_input_revision: int = Field(ge=1, strict=True)
