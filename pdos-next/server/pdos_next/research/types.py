"""Immutable public research contracts; authority always comes from RunScope."""

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from pdos_next.schema_base import StrictModel


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str
    summary: str
    provider: str


@dataclass(frozen=True)
class Snapshot:
    id: UUID
    url: str
    final_url: str
    title: str
    summary: str
    retrieved_at: datetime
    markdown: str
    content_hash: str
    provider: str
    credibility: str
    status: Literal["ok", "partial"] = "ok"


@dataclass(frozen=True)
class ReadPage:
    snapshot: Snapshot
    locator: str
    markdown: str
    next_cursor: int | None


@dataclass(frozen=True)
class ParsedDocument:
    """Result of a trusted isolated parser port, not a model extraction."""

    title: str
    markdown: str
    status: Literal["ok", "partial"] = "ok"


@dataclass(frozen=True)
class ParameterVersion:
    parameter_id: UUID
    version: int


@dataclass(frozen=True)
class ResearchTask:
    key: str
    focus: str
    brand: str | None = None
    source_type: str | None = None
    parameters: tuple[ParameterVersion, ...] = ()


class LedgerDraft(StrictModel):
    """Model extraction is a proposal; status and coverage are not model fields."""

    brand: str | None = None
    model: str | None = None
    parameter_id: UUID | None = None
    parameter_version: int | None = Field(default=None, ge=1)
    free_key: str | None = None
    value: str | int | float | None = None
    unit: str | None = None
    condition: str | None = None
    quote: str = Field(min_length=1)
    snapshot_id: UUID
    locator: str

    @field_validator("value")
    @classmethod
    def finite_value(cls, value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Research values must be finite")
        return value

    @model_validator(mode="after")
    def parameter_binding(self):
        if (self.parameter_id is None) != (self.parameter_version is None):
            raise ValueError("Parameter id and version must be provided together")
        if self.parameter_id is None and not self.free_key:
            raise ValueError("Unmapped observations require a free key")
        return self


@dataclass(frozen=True)
class ResearchFailure:
    task_key: str
    stage: str
    reason: str
    message: str
    url: str | None = None
    provider: str | None = None
    http_status: int | None = None
    service_code: str | None = None
    request_id: str | None = None
    retry_after: str | None = None


@dataclass(frozen=True)
class LedgerRow:
    row_id: UUID
    task_key: str
    brand: str | None
    model: str | None
    parameter_id: UUID | None
    parameter_version: int | None
    free_key: str | None
    value: str | int | float | None
    unit: str | None
    condition: str | None
    quote: str
    snapshot_id: UUID
    snapshot_url: str
    locator: str
    status: Literal["ok", "partial", "unavailable"]
    error: str | None


@dataclass(frozen=True)
class SearchTrace:
    query: str
    provider: str
    urls: tuple[str, ...]
    error: ResearchFailure | None = None


@dataclass(frozen=True)
class ReadTrace:
    url: str
    snapshot_id: UUID | None
    locator: str | None
    error: ResearchFailure | None = None


@dataclass(frozen=True)
class UnreadLocation:
    snapshot_id: UUID
    url: str
    locator: str


@dataclass(frozen=True)
class Coverage:
    task_key: str
    searches: tuple[SearchTrace, ...]
    reads: tuple[ReadTrace, ...]
    unread_urls: tuple[str, ...]
    unread_locations: tuple[UnreadLocation, ...]
    accepted_rows: int
    rejected_rows: int


@dataclass(frozen=True)
class SnapshotReference:
    id: UUID
    url: str
    final_url: str
    title: str
    content_hash: str
    retrieved_at: datetime
    provider: str
    status: str


@dataclass(frozen=True)
class FanoutResult:
    job_id: UUID
    status: Literal["completed", "partial", "unavailable"]
    ledger: tuple[LedgerRow, ...]
    coverage: tuple[Coverage, ...]
    failures: tuple[ResearchFailure, ...]
    snapshots: tuple[SnapshotReference, ...]

    def to_dict(self):
        """Raw webpage text is deliberately absent from this main-loop result."""

        def serialize(value):
            if isinstance(value, UUID):
                return str(value)
            if isinstance(value, datetime):
                return value.isoformat()
            raise TypeError("Unexpected research output type")

        return json.loads(json.dumps(asdict(self), default=serialize, allow_nan=False))
