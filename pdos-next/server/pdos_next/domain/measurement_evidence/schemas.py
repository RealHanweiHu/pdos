"""Server-bound report facts and source-value DTOs, without authority or persistence."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pdos_next.domain.verification_launch.schemas import ExecutionPlan
from pdos_next.schemas.verification.contracts import (
    ConfigurationRef,
    Coverage,
    EventTime,
    Measurement,
    SampleRef,
    Scope,
    SourceRef,
)

FORMAT_VERSION = "pdos-measurement-jsonl-v1"
VERIFIER_VERSION = "pdos-measurement-source-v1"
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Revision = Annotated[int, Field(strict=True, ge=1)]
Text = Annotated[str, Field(strict=True, min_length=1, max_length=2000)]
Key = Annotated[str, Field(strict=True, min_length=1, max_length=120)]


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


class OriginalRef(DTO):
    """Identity is provided by the already-authorized original-byte read path."""

    id: UUID
    revision: Revision
    sha256: Sha256
    size: Annotated[int, Field(strict=True, ge=0)]
    media_type: Literal["text/plain", "application/x-ndjson", "application/jsonl"]


class SampleItemBinding(DTO):
    sample: SampleRef
    item_id: Key


class ReportBinding(DTO):
    """Construct only on the server; hashes identify content, never qualification."""

    scope: Scope
    run_id: UUID
    run_revision: Revision
    request_id: UUID
    request_revision: Revision
    run_basis_sha256: Sha256
    report: SourceRef
    original: OriginalRef
    security_epoch: Annotated[int, Field(strict=True, ge=0)]
    pairs: tuple[SampleItemBinding, ...] = Field(min_length=1)
    execution_plan: ExecutionPlan | None = None
    parser_version: Literal["pdos-measurement-jsonl-v1"] = FORMAT_VERSION

    @model_validator(mode="after")
    def exact_identity(self):
        if self.report.kind != "artifact":
            raise ValueError("原报告须为当前已核对的Artifact固定引用")
        keys = {(pair.sample.id, pair.item_id) for pair in self.pairs}
        if len(keys) != len(self.pairs):
            raise ValueError("固定样件/测试项范围不能重复")
        samples = {}
        for pair in self.pairs:
            previous = samples.setdefault(pair.sample.id, pair.sample)
            if previous != pair.sample:
                raise ValueError("一个样件不能映射为不同配置或模穴")
        return self


class ObservationSelection(DTO):
    """An explicit real row selection; there is no reading or expected-value input."""

    line: Annotated[int, Field(strict=True, ge=1)]
    sample_id: UUID
    item_id: Key


class ObservationLine(DTO):
    """Closed JSONL schema. Optional fields remain missing or explicit null."""

    format: Literal["pdos-measurement-jsonl-v1"]
    run_id: UUID
    sample_id: UUID
    sample_revision: Revision
    actual_configuration: ConfigurationRef
    cavity: Key | None
    item_id: Key
    raw_value: Annotated[str | None, Field(strict=True, max_length=4000)] = None
    unit: Key | None = None
    conditions: Text | None = None
    equipment: SourceRef | None = None
    equipment_label: Text | None = None
    calibration: SourceRef | None = None
    environment: Text | None = None
    method: SourceRef | None = None
    executor_id: UUID | None = None
    observed_at: datetime | None = None
    observed_timezone: Key | None = None
    note: Text | None = None

    @field_validator("observed_at", mode="before")
    @classmethod
    def original_time(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("观测时间须为原报告含偏移的ISO时间字符串")
        if "T" not in value or len(value) > 80:
            raise ValueError("观测时间须为含偏移的ISO时间")
        result = datetime.fromisoformat(value)
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("原报告观测时间不能缺时区偏移")
        return result

    @field_validator("observed_timezone")
    @classmethod
    def original_zone(cls, value):
        if value is not None:
            try:
                ZoneInfo(value)
            except (ValueError, ZoneInfoNotFoundError) as exc:
                raise ValueError("原报告须保留合法IANA时区") from exc
        return value

    @field_validator("unit", "conditions", "environment", "equipment_label", "note")
    @classmethod
    def nonblank_metadata(cls, value):
        if value is not None and not value.strip():
            raise ValueError("元数据缺项应为null或省略，不能用空白冒充")
        return value

    @model_validator(mode="after")
    def temporal_offset(self):
        # A missing member is preserved as a gap. Two known members must agree;
        # an aware offset resolves DST folds and rejects nonexistent local times.
        if self.observed_at is not None and self.observed_timezone is not None:
            local = self.observed_at.astimezone(ZoneInfo(self.observed_timezone))
            if local.utcoffset() != self.observed_at.utcoffset():
                raise ValueError("原ISO偏移与声明IANA时区在该时点不一致")
        return self


class FieldLocation(DTO):
    line: Annotated[int, Field(strict=True, ge=1)]
    field: Key
    presence: Literal["missing", "null", "value"]
    raw_token: str | None = None
    # Half-open offsets. Characters are relative to the exact original line;
    # bytes are absolute in the immutable original, including prior CRLF bytes.
    character_start: Annotated[int | None, Field(strict=True, ge=0)] = None
    character_end: Annotated[int | None, Field(strict=True, ge=0)] = None
    byte_start: Annotated[int | None, Field(strict=True, ge=0)] = None
    byte_end: Annotated[int | None, Field(strict=True, ge=0)] = None


class ObservationCandidate(DTO):
    coverage: Coverage
    sample: SampleRef
    source: SourceRef
    line: Annotated[int, Field(strict=True, ge=1)]
    row_sha256: Sha256
    raw_value: Annotated[str | None, Field(strict=True, max_length=4000)]
    unit: Key | None
    conditions: Text | None
    equipment: SourceRef | None
    equipment_label: Text | None
    calibration: SourceRef | None
    environment: Text | None
    method: SourceRef | None
    executor_id: UUID | None
    observed_at: datetime | None
    observed_timezone: Key | None
    note: Text | None
    field_locations: tuple[FieldLocation, ...]
    missing: tuple[Text, ...]
    metadata_mismatches: tuple[Text, ...] = ()
    value_state: Literal["known", "unknown", "non_numeric", "non_finite"]

    def to_measurement(self, measurement_id: UUID) -> Measurement:
        """The server owns identity; only source values populate measurement data."""
        return Measurement(
            id=measurement_id,
            coverage=self.coverage,
            raw_value=self.raw_value,
            unit=self.unit,
            conditions=self.conditions,
            equipment=self.equipment,
            equipment_label=self.equipment_label,
            environment=self.environment,
            method=self.method,
            source=self.source,
            missing=self.missing + self.metadata_mismatches,
            note=self.note,
            observed_at=EventTime.aware(self.observed_at),
            observed_timezone=self.observed_timezone,
        )


class ObservationCandidates(DTO):
    binding: ReportBinding
    observations: tuple[ObservationCandidate, ...]
    missing_pairs: tuple[Coverage, ...]
    verifier_version: Literal["pdos-measurement-source-v1"] = VERIFIER_VERSION


class VerifiedObservation(DTO):
    """Exact source-value proof only; neither qualification nor a test result."""

    observation: ObservationCandidate
    measurement: Measurement
    report_sha256: Sha256
    proof_sha256: Sha256
    verification: Literal["exact_source_values"] = "exact_source_values"
    verifier_version: Literal["pdos-measurement-source-v1"] = VERIFIER_VERSION
