"""Finite server summary DTOs; selection narrows reads and never grants access."""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field, model_serializer, model_validator

from pdos_next.schema_base import StrictModel

Group = Literal["action", "waiting", "following"]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class DTO(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Selection(DTO):
    followed_project_ids: tuple[UUID, ...] = Field(default=(), max_length=50)
    category_ids: tuple[UUID, ...] = Field(default=(), max_length=32)
    groups: tuple[Group, ...] = ("action", "waiting", "following")
    excluded_kinds: tuple[Annotated[str, Field(min_length=1, max_length=80)], ...] = Field(
        default=(),
        max_length=40,
    )
    max_items: int = Field(default=100, ge=1, le=300, strict=True)
    dingtalk_binding_id: UUID | None = None

    @model_serializer(mode="wrap")
    def saved_shape(self, handler):
        value = handler(self)
        if value.get("dingtalk_binding_id") is None:
            value.pop("dingtalk_binding_id", None)
        return value

    @model_validator(mode="after")
    def unique(self):
        for key in ("followed_project_ids", "category_ids", "groups", "excluded_kinds"):
            values = getattr(self, key)
            if len(values) != len(set(values)):
                raise ValueError("Summary selections cannot repeat identities or groups")
        return self


class Person(DTO):
    id: UUID
    name: str | None = None


class ObjectRef(DTO):
    kind: str
    id: UUID
    version_id: UUID | None = None
    revision: int | None = Field(default=None, ge=1)
    category_id: UUID
    product_id: UUID | None = None
    project_id: UUID | None = None


class NextStep(DTO):
    kind: Literal["recorded", "navigation", "unknown"]
    text: str
    responsible: Person | None = None
    recorded_by: Person | None = None


class Relationship(DTO):
    kind: str
    text: str


class Change(DTO):
    kind: Literal["initial", "updated", "unchanged"]
    text: str


class Item(DTO):
    id: str
    kind: str
    group: Group
    title: str
    object: ObjectRef
    as_of: AwareDatetime
    recorded_at: AwareDatetime
    state_as_recorded: str
    change: Change
    relationship: Relationship
    next_step: NextStep
    continue_url: str
    facts: dict[str, Any] = Field(default_factory=dict)
    possible_impact: Literal["待确认"] = "待确认"
    # ProjectStatusUpdate has no separate structured health field. Preserve its
    # literal named summary; never turn prose, dates or counts into a risk grade.
    health: None = None
    fingerprint: Digest


class Baseline(DTO):
    tenant_id: UUID
    principal_id: UUID
    selection_digest: Digest
    watermarks: dict[str, Digest] = Field(default_factory=dict, max_length=300)


class Coverage(DTO):
    source: str
    returned: int = Field(ge=0)
    available: int | None = Field(default=None, ge=0)
    has_more: bool = False
    unavailable: int = Field(default=0, ge=0)


class SummaryGroup(DTO):
    id: Group
    title: str
    items: tuple[Item, ...]
    unchanged_items: tuple[Item, ...]
    unchanged_collapsed: Literal[True] = True


class Summary(DTO):
    version: Literal["personal-summary/v1"] = "personal-summary/v1"
    tenant_id: UUID
    principal_id: UUID
    as_of: AwareDatetime
    groups: tuple[SummaryGroup, ...]
    coverage: tuple[Coverage, ...]
    complete: bool
    omitted_current_items: int = Field(ge=0)
    baseline: Baseline
    model_used: Literal[False] = False
    missing_since_previous: Literal["not_classified"] = "not_classified"
