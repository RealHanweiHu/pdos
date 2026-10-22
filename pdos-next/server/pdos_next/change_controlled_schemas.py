"""Typed publisher/auxiliary payloads; no SQL or self-grant registration."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from pdos_next.change_command_schemas import Target
from pdos_next.schemas.change_control.contracts import Discipline, PlanItem
from pdos_next.schemas.verification.contracts import DTO, Scope, SourceRef, Text

# Auxiliary names proposed for a future unified freeze. None are registered.
POLICY_OPERATION = "change.policy.import"
POLICY_EVENT = "change.policy_imported"
POLICY_FAMILY = "change_policy_fact"
SELECTION_OPERATION = "change.selection.decide"
SELECTION_EVENT = "change.selection_decided"
SELECTION_FAMILY = "change_selection_fact"


class Exact(DTO):
    @model_validator(mode="before")
    @classmethod
    def integers(cls, raw):
        def visit(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if (
                        key
                        in {
                            "revision",
                            "expected_change_revision",
                            "expected_issue_revision",
                            "expected_previous_revision",
                        }
                        and child is not None
                    ):
                        if type(child) is not int or child < 1:
                            raise ValueError("Fixed revisions must be actual positive integers")
                    visit(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    visit(child)

        visit(raw)
        return raw


class PolicyMaterial(Exact):
    schema_version: Literal["pdos-controlled-change-policy-v1"]
    scope: Scope
    purpose: Text
    owner_id: UUID
    visibility: Literal["private", "category", "audience"]
    publisher_id: UUID
    required_disciplines: tuple[Discipline, ...] = Field(min_length=2)
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    nature: Literal["real", "synthetic"]

    @model_validator(mode="after")
    def fixed(self):
        if not {"engineering", "manufacturing"} <= set(self.required_disciplines) or len(
            set(self.required_disciplines)
        ) != len(self.required_disciplines):
            raise ValueError("Controlled policy must preserve both actual disciplines")
        if self.valid_until <= self.valid_from:
            raise ValueError("Policy validity must be a nonempty actual interval")
        return self


class PolicyImport(Exact):
    """Trusted host request only: source is parsed; no client policy/issuer flags."""

    project_id: UUID
    purpose: Text
    source: SourceRef
    expected_previous_id: UUID | None = None
    expected_previous_revision: int | None = Field(default=None, strict=True, ge=1)
    reason: Text

    @model_validator(mode="after")
    def previous(self):
        if (self.expected_previous_id is None) != (self.expected_previous_revision is None):
            raise ValueError("Previous policy needs both exact identity and revision")
        return self


class ActionTarget(Exact):
    issue_id: UUID
    expected_issue_revision: int = Field(strict=True, ge=1)
    capa_id: UUID
    action_id: UUID


class FieldFeedbackRef(Exact):
    id: UUID
    revision: int = Field(strict=True, ge=1)


class FieldIntentTarget(Exact):
    kind: Literal["field_intent"]
    feedback: FieldFeedbackRef
    executor_id: UUID


class SelectionPayload(Target, Exact):
    """A named proposal: actual applicability is established only by T2 consumption."""

    item: PlanItem
    action: ActionTarget | FieldIntentTarget
    status: Literal["applicable", "not_applicable", "unknown"]
    source: SourceRef
    valid_until: AwareDatetime | None = None
    reason: Text
    expected_previous_id: UUID | None = None
    expected_previous_revision: int | None = Field(default=None, strict=True, ge=1)
    approval_token: str | None = Field(default=None, min_length=16, max_length=512)

    @model_validator(mode="after")
    def previous(self):
        if (self.expected_previous_id is None) != (self.expected_previous_revision is None):
            raise ValueError("Previous selection requires exact identity and revision")
        return self


class SelectionMaterial(Exact):
    schema_version: Literal["pdos-controlled-change-selection-v1"]
    scope: Scope
    purpose: Text
    change_id: UUID
    item: PlanItem
    issue_id: UUID
    capa_id: UUID
    action_id: UUID
    action_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    executor_id: UUID
    decider_id: UUID
    status: Literal["applicable", "not_applicable", "unknown"]
    valid_until: AwareDatetime
    reason: Text
    nature: Literal["real", "synthetic"]


class FieldSelectionMaterial(Exact):
    """A future PlanItem explicitly declared by a named person, never a response."""

    schema_version: Literal["pdos-field-change-selection-v1"]
    scope: Scope
    purpose: Text
    change_id: UUID
    item: PlanItem
    feedback: FieldFeedbackRef
    feedback_version_id: UUID
    feedback_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    executor_id: UUID
    decider_id: UUID
    status: Literal["applicable", "not_applicable", "unknown"]
    valid_until: AwareDatetime | None
    reason: Text
    nature: Literal["real", "synthetic"]


class UnitBinding(Exact):
    unit: Text
    object_identity: Text


BIND = ("tenant_id", "product_id", "project_id", "owner_id", "visibility")
