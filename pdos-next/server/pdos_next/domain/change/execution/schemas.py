"""Public inputs never carry authority, graph completeness, actor or generated IDs."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, field_validator, model_validator

from pdos_next.schemas.change_control.contracts import (
    ChangeRequest,
    GraphSnapshot,
    Hypothesis,
    Ref,
    RequestCreate,
)
from pdos_next.schemas.verification.contracts import DTO, SourceRef


class ChangeCreatePayload(RequestCreate):
    visibility: Literal["private", "category", "audience"] = "private"

    @field_validator("roots", "references", "sources", mode="before")
    @classmethod
    def strict_revisions(cls, values):
        for value in values:
            if isinstance(value, dict) and type(value.get("revision")) is not int:
                raise ValueError("固定引用版本须为严格整数")
        return values

    @model_validator(mode="after")
    def fixed_native_basis(self) -> Self:
        refs = (*self.roots, *self.references)
        if not any(ref.kind in {"issue", "capa", "field_feedback"} for ref in refs):
            raise ValueError("变更须固定真实Issue、CAPA或已定位现场反馈作为依据")
        for group in (self.roots, self.references):
            if len({ref.identity for ref in group}) != len(group):
                raise ValueError("固定引用不能重复")
        if any(ref.kind != "artifact" for ref in self.sources):
            raise ValueError("人工变更依据须引用已登记原文Artifact的精确行")
        return self


class ImpactComputePayload(DTO):
    change_id: UUID
    expected_change_revision: int = Field(ge=1, strict=True)
    snapshot: Ref
    hypotheses: tuple[Hypothesis, ...] = Field(default=())

    @field_validator("snapshot", mode="before")
    @classmethod
    def strict_revision(cls, value):
        if isinstance(value, dict) and type(value.get("revision")) is not int:
            raise ValueError("固定图版本须为严格整数")
        return value

    @field_validator("hypotheses", mode="before")
    @classmethod
    def strict_hypothesis_sources(cls, values):
        for hypothesis in values:
            if isinstance(hypothesis, dict):
                for source in hypothesis.get("sources", []):
                    if isinstance(source, dict) and type(source.get("revision")) is not int:
                        raise ValueError("假设来源版本须为严格整数")
        return values

    @model_validator(mode="after")
    def fixed_graph(self) -> Self:
        if self.snapshot.kind != "graph_snapshot" or self.snapshot.key is not None:
            raise ValueError("影响计算须引用已保存固定图ID及版本")
        if any(source.kind != "artifact" for h in self.hypotheses for source in h.sources):
            raise ValueError("假设须有可定位的原文出处，不能代替事实或批准")
        return self


class GraphCaptureInput(DTO):
    capture_key: str = Field(min_length=8, max_length=160)
    change_id: UUID
    expected_change_revision: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=3, max_length=2000)


class FixedIssue(DTO):
    """Server-owned fixed Issue port response; never an HTTP/client DTO."""

    issue_id: UUID
    version_id: UUID
    revision: int = Field(ge=1, strict=True)
    project_id: UUID
    owner_id: UUID
    visibility: Literal["private", "category", "audience"]
    snapshot: dict
    required_source_read_set: list[dict]
    source_basis: dict
    current: bool = Field(strict=True)
    reason_codes: tuple[str, ...] = ()


class ChangeView(DTO):
    id: UUID
    change_id: UUID
    revision: int = Field(strict=True, ge=1)
    project_id: UUID
    request: ChangeRequest
    owner_id: UUID
    visibility: Literal["private", "category", "audience"]
    status: Literal["draft", "analysis", "review", "approved", "implementing"]
    created_at: AwareDatetime
    current: bool
    source_status: Literal["current", "needs_recheck"]
    required_source_read_set: list[dict[str, JsonValue]]
    authority: dict[str, JsonValue]
    capabilities: dict[str, bool]
    blockers: list[dict[str, str]]


class GraphCaptureView(DTO):
    id: UUID
    revision: int = Field(strict=True, ge=1)
    change_id: UUID
    change_revision: int = Field(strict=True, ge=1)
    graph: GraphSnapshot
    expires_at: AwareDatetime
    created_at: AwareDatetime
    current: bool
    source_status: Literal["current", "needs_recheck"]
    owner_id: UUID
    visibility: Literal["private", "category", "audience"]
    reason: str
    required_source_read_set: list[dict[str, JsonValue]]
    impact_payload: ImpactComputePayload


class SourceOption(DTO):
    title: str
    quote: str
    source: SourceRef
    required_source_read_set: list[dict[str, JsonValue]]


class ChangeReading(DTO):
    changes: list[ChangeView]
    captures: list[GraphCaptureView]
    current_by_change: dict[str, dict[str, JsonValue]]
    reference_options: list[dict[str, JsonValue]]
    source_options: list[SourceOption]
    capabilities: dict[str, bool]
    authority: dict[str, JsonValue]
    unavailable_count: int = Field(ge=0)
    has_more: bool
