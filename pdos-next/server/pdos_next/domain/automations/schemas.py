"""Fixed read-only automation declarations; catalog, scope and authority stay server-owned."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pdos_next.personal_summary_schemas import Selection as PersonalSummarySelection
from pdos_next.schema_base import StrictModel
from pydantic import ConfigDict, Field, field_validator, model_serializer, model_validator

from .trigger_time import Schedule

MAX_INTEGER = 2_147_483_647
ZERO_MODEL_BUDGET = {
    "limit_micro_usd": 0,
    "input_token_limit": 0,
    "output_token_limit": 0,
    "call_limit": 0,
}
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
    input_token_limit: int = Field(ge=0, strict=True)
    output_token_limit: int = Field(ge=0, strict=True)
    call_limit: int = Field(ge=0, strict=True)


class EventTrigger(DTO):
    event_types: list[str] = Field(min_length=1, max_length=100)
    subject_id: UUID | None = None
    merge_window_seconds: int = Field(default=0, ge=0, le=MAX_INTEGER, strict=True)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def valid(self):
        if len(set(self.event_types)) != len(self.event_types):
            raise ValueError("Duplicate event types")
        if self.expires_at is not None and self.expires_at.utcoffset() is None:
            raise ValueError("Expiry must have a timezone")
        return self


class RelativeTrigger(DTO):
    source_kind: Literal["plan_task", "commitment"]
    project_id: UUID
    task_id: UUID
    clock: Literal[
        "earliest_start", "earliest_finish", "latest_start", "latest_finish", "promised_at"
    ]
    promisor_id: UUID | None = None
    recipient_id: UUID | None = None
    offset_seconds: int = Field(ge=-MAX_INTEGER, le=MAX_INTEGER, strict=True)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.source_kind == "commitment":
            if self.clock != "promised_at" or self.promisor_id is None or self.recipient_id is None:
                raise ValueError(
                    "A promise requires the actual promisor, recipient and promise clock"
                )
        elif (
            self.clock == "promised_at"
            or self.promisor_id is not None
            or self.recipient_id is not None
        ):
            raise ValueError("Plan forecasts cannot be used as promises")
        if self.expires_at is not None and self.expires_at.utcoffset() is None:
            raise ValueError("Expiry must have a timezone")
        return self


class Conditions(DTO):
    task_id: UUID | None = None
    only_states: list[
        Literal["proposed", "assigned", "accepted", "in_progress", "submitted", "completed"]
    ] = Field(default_factory=list)
    stop_states: list[
        Literal["proposed", "assigned", "accepted", "in_progress", "submitted", "completed"]
    ] = Field(default_factory=lambda: ["completed"])

    @model_validator(mode="after")
    def valid(self):
        if self.task_id is None and self.only_states:
            raise ValueError("State conditions require an actual task")
        if set(self.only_states) & set(self.stop_states):
            raise ValueError("Eligible and stop states must not overlap")
        return self


class AutomationSpec(DTO):
    name: str = Field(min_length=1, max_length=160)
    goal: str = Field(min_length=1, max_length=12_000)
    purpose: str = Field(min_length=1, max_length=2000)
    stop_condition: str = Field(min_length=1, max_length=2000)
    trigger_kind: Literal["manual", "schedule", "domain_event", "relative_milestone"]
    trigger_config: dict | None = None
    personal_summary: PersonalSummarySelection | None = None
    conditions: Conditions = Field(default_factory=Conditions)
    max_cascade_depth: int = Field(default=3, ge=0, le=MAX_INTEGER, strict=True)
    external_sources_enabled: Literal[False] = False
    product_id: UUID | None = None
    skill_keys: list[SkillRef] = Field(max_length=12)
    validation_budget_id: UUID | None
    token_limit: int = Field(ge=1, le=MAX_INTEGER, strict=True)
    budget: BudgetLimits
    cooldown_seconds: int = Field(ge=0, le=MAX_INTEGER, strict=True)
    max_runs: int = Field(ge=1, le=MAX_INTEGER, strict=True)
    allow_network: Literal[False] = False
    mcp_tools: list[str] = Field(default_factory=list, max_length=0)
    cross_object_write: Literal[False] = False

    @property
    def walletless_summary(self):
        return self.personal_summary is not None and self.validation_budget_id is None

    @model_serializer(mode="wrap")
    def saved_shape(self, handler):
        value = handler(self)
        # An omitted new selection cannot change any installed rule's digest.
        if value.get("personal_summary") is None:
            value.pop("personal_summary", None)
        # Preserve the canonical request digest of installed manual rules and
        # their original idempotency keys. New optional defaults add no authority.
        if self.trigger_kind == "manual":
            defaults = {
                "trigger_config": None,
                "conditions": Conditions().model_dump(),
                "max_cascade_depth": 3,
                "external_sources_enabled": False,
            }
            for key, default in defaults.items():
                if value.get(key) == default:
                    value.pop(key, None)
        return value

    @field_validator(
        "allow_network", "cross_object_write", "external_sources_enabled", mode="before"
    )
    @classmethod
    def disabled(cls, value):
        if value is not False:
            raise ValueError("This read-only slice does not enable this capability")
        return value

    @model_validator(mode="after")
    def distinct_skills(self):
        if self.walletless_summary:
            if (
                self.skill_keys
                or self.token_limit != 1
                or self.budget.model_dump() != ZERO_MODEL_BUDGET
            ):
                raise ValueError(
                    "Deterministic summaries have no skills or model spending capacity"
                )
        elif (
            self.validation_budget_id is None
            or not self.skill_keys
            and self.personal_summary is None
            or min(
                self.budget.input_token_limit,
                self.budget.output_token_limit,
                self.budget.call_limit,
            )
            < 1
        ):
            raise ValueError("Model rules require fixed skills and an actual model budget")
        if len({ref.key for ref in self.skill_keys}) != len(self.skill_keys):
            raise ValueError("Each skill key must pin exactly one version and digest")
        if self.personal_summary is not None and self.trigger_kind == "manual":
            raise ValueError("Personal summaries require the actual automatic service grant")
        if self.trigger_kind == "manual":
            if self.trigger_config is not None:
                raise ValueError("Manual rules have no automatic trigger configuration")
        else:
            parsed = {
                "schedule": Schedule,
                "domain_event": EventTrigger,
                "relative_milestone": RelativeTrigger,
            }[self.trigger_kind].model_validate(self.trigger_config)
            object.__setattr__(self, "trigger_config", parsed.model_dump(mode="json"))
        if self.trigger_kind == "relative_milestone" and self.product_id is None:
            raise ValueError("Relative clocks require the actual product scope")
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
