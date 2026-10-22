from datetime import UTC
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from pdos_next.domain.configurations.schemas import DefinitionReference
from pdos_next.engines.supply_cost.common import FrozenDTO, Quantity


class SupplyRecordInput(FrozenDTO):
    record_kind: Literal["inventory", "commitment", "in_transit", "receipt", "restriction"]
    record_id: str = Field(min_length=1, max_length=160)
    material_id: UUID
    quantity: Quantity | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=80)
    sources: list[DefinitionReference] = Field(min_length=1)
    source_system: str | None = Field(default=None, min_length=1, max_length=100)
    pool_id: str | None = Field(default=None, min_length=1, max_length=200)
    supplier_id: str | None = Field(default=None, min_length=1, max_length=200)
    expected_at: AwareDatetime | None = None
    received_at: AwareDatetime | None = None
    commitment_id: str | None = Field(default=None, min_length=1, max_length=160)
    quality: Literal["unknown", "frozen"] = "unknown"
    availability: Literal["unknown", "unavailable"] = "unknown"
    note: str = Field(min_length=1, max_length=2000)

    @field_validator("expected_at", "received_at")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def sourced_identity(self) -> Self:
        if self.quantity is not None and self.unit is None:
            raise ValueError("已知来源数量须有单位，未知数量保持null")
        if self.record_kind != "commitment" and (
            self.source_system is None or self.pool_id is None
        ):
            raise ValueError("实物池须提供来源系统和真实外部池标识，不由系统编造")
        if self.record_kind == "commitment" and self.supplier_id is None:
            raise ValueError("承诺来源须明确外部供方标识")
        if self.record_kind == "receipt" and self.received_at is None:
            raise ValueError("实际到货须明确发生时间，不用捕获时点代替")
        if self.record_kind != "receipt" and self.received_at is not None:
            raise ValueError("仅实际到货记录接收时间")
        if len(
            {(ref.artifact_id, ref.expected_revision, ref.line, ref.quote) for ref in self.sources}
        ) != len(self.sources):
            raise ValueError("精确原文来源不能重复")
        return self


class SupplyCaptureInput(FrozenDTO):
    capture_key: str = Field(min_length=8, max_length=160)
    expected_product_revision: int = Field(ge=1, strict=True)
    build_id: UUID
    expected_build_revision: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=3, max_length=2000)
    records: list[SupplyRecordInput] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_records(self) -> Self:
        if len({(row.record_kind, row.record_id) for row in self.records}) != len(self.records):
            raise ValueError("一份来源快照中不能重复同种记录的稳定身份")
        return self


class SnapshotRecordPayload(FrozenDTO):
    build_id: UUID
    expected_build_revision: int = Field(ge=1, strict=True)
    capture_id: UUID
    expected_capture_revision: int = Field(ge=1, strict=True)
    expected_previous_snapshot_id: UUID | None = None
    expected_previous_revision: int | None = Field(default=None, ge=1, strict=True)
    reason: str = Field(min_length=3, max_length=2000)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def previous_pair(self) -> Self:
        if (self.expected_previous_snapshot_id is None) != (
            self.expected_previous_revision is None
        ):
            raise ValueError("前版快照ID与版本须成对，首版均为null")
        return self


class KitComputePayload(FrozenDTO):
    build_id: UUID
    expected_build_revision: int = Field(ge=1, strict=True)
    supply_snapshot_id: UUID
    expected_supply_revision: int = Field(ge=1, strict=True)
