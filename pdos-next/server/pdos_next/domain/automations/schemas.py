"""Closed manual automation declarations; catalog, scope and authority stay server-owned."""

from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from pdos_next.schema_base import StrictModel

MAX_INTEGER = 2_147_483_647
DRAFT_SAVE = "ai.automation.draft.save"
ACTIVATE = "ai.automation.activate"
PAUSE = "ai.automation.pause"


class DTO(StrictModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, str_strip_whitespace=True, revalidate_instances="always"
    )


class SkillRef(DTO):
    key: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=160)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class BudgetLimits(DTO):
    limit_micro_usd: int = Field(ge=0, strict=True)
    input_token_limit: int = Field(ge=1, strict=True)
    output_token_limit: int = Field(ge=1, strict=True)
    call_limit: int = Field(ge=1, strict=True)


class AutomationSpec(DTO):
    name: str = Field(min_length=1, max_length=160)
    goal: str = Field(min_length=1, max_length=12_000)
    purpose: str = Field(min_length=1, max_length=2000)
    stop_condition: str = Field(min_length=1, max_length=2000)
    trigger_kind: Literal["manual"]
    product_id: UUID | None = None
    skill_keys: list[SkillRef] = Field(min_length=1, max_length=12)
    validation_budget_id: UUID
    token_limit: int = Field(ge=1, le=MAX_INTEGER, strict=True)
    budget: BudgetLimits
    cooldown_seconds: int = Field(ge=0, le=MAX_INTEGER, strict=True)
    max_runs: int = Field(ge=1, le=MAX_INTEGER, strict=True)
    allow_network: Literal[False] = False
    mcp_tools: list[str] = Field(default_factory=list, max_length=0)
    cross_object_write: Literal[False] = False

    @field_validator("allow_network", "cross_object_write", mode="before")
    @classmethod
    def disabled(cls, value):
        if value is not False:
            raise ValueError("This manual read-only slice does not enable this capability")
        return value

    @model_validator(mode="after")
    def distinct_skills(self):
        if len({ref.key for ref in self.skill_keys}) != len(self.skill_keys):
            raise ValueError("Each skill key must pin exactly one version and digest")
        return self


# The shorter name is useful to consumers without introducing a second schema.
Spec = AutomationSpec


class DraftSave(DTO):
    rule_id: UUID | None = None
    expected_rule_revision: int = Field(ge=0, strict=True)
    spec: AutomationSpec
    restored_from: UUID | None = None


class Control(DTO):
    rule_id: UUID
    expected_rule_revision: int = Field(gt=0, strict=True)
    version_id: UUID
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)


class Trigger(DTO):
    expected_rule_revision: int = Field(gt=0, strict=True)
    version_id: UUID
    idempotency_key: str = Field(min_length=8, max_length=120)


PAYLOADS = {DRAFT_SAVE: DraftSave, ACTIVATE: Control, PAUSE: Control}
