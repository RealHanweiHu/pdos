"""N0-02 activation/trigger document rules; not imported by runtime dispatch."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from app.contracts.common_objects import Contract, Digest, Key, Nonnegative, Positive, Text


class ComponentSource(Contract):
    key: Key
    status: Literal["present", "planned"]
    path: Text | None
    symbol: Text | None
    sha256: Digest | None
    version: Key | None
    implementation_work: Text

    @model_validator(mode="after")
    def source_is_not_a_promise(self) -> Self:
        if self.status == "present" and (self.path is None or self.sha256 is None):
            raise ValueError("present_component_requires_file_and_digest")
        if self.status == "planned" and (self.path is not None or self.sha256 is not None):
            raise ValueError("planned_component_cannot_claim_file_evidence")
        return self


class TriggerPolicy(Contract):
    key: Key
    origin: Literal["user", "event", "scheduled", "control"]
    priority: Literal["control", "interactive", "milestone", "background"]
    coalesce_seconds: Nonnegative
    queue_visible_seconds: Positive = 5
    outcome_deadline_seconds: Positive | None
    model_allowed: bool
    deduplication: Literal["tenant_scope_capability_goal_source_versions"] = (
        "tenant_scope_capability_goal_source_versions"
    )
    deadline_includes_queue_and_debounce: Literal[True] = True
    error_cleanup_model_calls: Literal[0] = 0
    cancellation_preempts: Literal[True] = True

    @model_validator(mode="after")
    def do_not_spend_sla_before_starting(self) -> Self:
        if self.origin in {"user", "control"} and self.coalesce_seconds != 0:
            raise ValueError("user_and_control_are_immediate")
        if self.origin == "control" and self.model_allowed:
            raise ValueError("control_cleanup_cannot_call_model")
        if self.outcome_deadline_seconds is not None and (
            self.coalesce_seconds + self.queue_visible_seconds >= self.outcome_deadline_seconds
        ):
            raise ValueError("trigger_wait_exhausts_outcome_deadline")
        return self


class ActivationRequirement(Contract):
    key: Key
    component_sources: tuple[ComponentSource, ...] = Field(min_length=1)
    required_scope_tests: tuple[Key, ...] = Field(min_length=1)
    qualification_scope: Literal["capability_bundle_not_provider_only"] = (
        "capability_bundle_not_provider_only"
    )
    approval_required: Literal[True] = True
    current_rollout: Literal["disabled", "shadow", "live"]
    requested_rollout: Literal["disabled", "shadow", "live"]
    qualification_evidence: Text | None
    regression_evidence: Text | None
    adoption_approval: Text | None

    @model_validator(mode="after")
    def activation_is_not_registration(self) -> Self:
        if self.requested_rollout == "live" and (
            any(c.status != "present" for c in self.component_sources)
            or self.qualification_evidence is None
            or self.regression_evidence is None
            or self.adoption_approval is None
        ):
            raise ValueError("live_adoption_requires_components_qualification_tests_and_approval")
        return self


TRIGGER_POLICIES = (
    TriggerPolicy(
        key="user_request",
        origin="user",
        priority="interactive",
        coalesce_seconds=0,
        outcome_deadline_seconds=None,
        model_allowed=True,
    ),
    TriggerPolicy(
        key="milestone",
        origin="event",
        priority="milestone",
        coalesce_seconds=0,
        outcome_deadline_seconds=180,
        model_allowed=True,
    ),
    TriggerPolicy(
        key="frequent_edit",
        origin="event",
        priority="background",
        coalesce_seconds=900,
        outcome_deadline_seconds=None,
        model_allowed=True,
    ),
    TriggerPolicy(
        key="scheduled",
        origin="scheduled",
        priority="background",
        coalesce_seconds=0,
        outcome_deadline_seconds=None,
        model_allowed=True,
    ),
    TriggerPolicy(
        key="control",
        origin="control",
        priority="control",
        coalesce_seconds=0,
        outcome_deadline_seconds=None,
        model_allowed=False,
    ),
)
