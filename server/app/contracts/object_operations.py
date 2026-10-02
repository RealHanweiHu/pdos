"""Versioned N0-01 logical commands/events, not registered HTTP routes or tools.

Clients request actions; actor/tenant/scope/current state are resolved by the
future domain handler. Approval references must be reloaded, never trusted.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Self
from uuid import UUID

from pydantic import model_validator

from app.contracts.common_objects import Contract, Digest, Key, Positive, SourceRef, Text


class CommandPrecondition(Contract):
    expected_version: Positive
    payload_digest: Digest
    idempotency_key: Key
    schema_version: Literal[1] = 1


class ResearchStartRequest(CommandPrecondition):
    research_task_id: UUID


class ResearchConcludeRequest(CommandPrecondition):
    research_task_id: UUID
    conclusion: Text
    findings: tuple[Text, ...]
    unresolved: tuple[Text, ...]
    source_refs: tuple[SourceRef, ...]

    @model_validator(mode="after")
    def conclusion_sources(self) -> Self:
        if not self.source_refs:
            raise ValueError("research_conclusion_requires_snapshot_sources")
        if any(ref.kind != "evidence_snapshot" for ref in self.source_refs):
            raise ValueError("research_conclusion_requires_snapshot_sources")
        return self


class DefinitionPublishRequest(CommandPrecondition):
    definition_id: UUID
    reviewed_source_digest: Digest


class ReviewFinalizeRequest(CommandPrecondition):
    review_id: UUID
    outcome: Literal["approved", "conditional", "hold", "rejected"]
    rationale: Text
    conditions: tuple[Text, ...]

    @model_validator(mode="after")
    def conditional_result(self) -> Self:
        if self.outcome == "conditional" and not self.conditions:
            raise ValueError("conditional_review_requires_conditions")
        return self


class InitialPlanApplyRequest(CommandPrecondition):
    project_id: UUID
    conversion_id: UUID
    finding_id: UUID
    execution_approval_id: UUID
    candidate_digest: Digest


class ProjectAdoptionRequest(CommandPrecondition):
    project_id: UUID
    adoption_id: UUID
    remediation_receipt_id: UUID


class ReservationReserveRequest(CommandPrecondition):
    reservation_id: UUID
    expected_capacity_version: Positive
    expected_calendar_version: Positive
    approval_id: UUID


class ReservationReleaseRequest(CommandPrecondition):
    reservation_id: UUID
    reason: Text


class CommandResult(Contract):
    operation_id: UUID
    disposition: Literal["created", "reused"]
    status: Literal["applied", "pending", "receipt_unknown"]
    targets: tuple[SourceRef, ...]
    event_row_ids: tuple[Positive, ...]
    audit_row_ids: tuple[Positive, ...]
    next_action: Key | None

    @model_validator(mode="after")
    def successful_write_has_trace(self) -> Self:
        if self.status == "applied" and (
            not self.targets or not self.event_row_ids or not self.audit_row_ids
        ):
            raise ValueError("applied_command_requires_targets_event_audit")
        return self


class ContractEventPayload(Contract):
    """New event payload only; old strict EventDraft payloads remain unchanged."""

    schema_version: Literal[1] = 1
    object_id: UUID
    object_version: Positive
    operation_id: UUID
    correlation_id: UUID
    causation_event_row_id: Positive | None


class ResearchTaskChangedPayload(ContractEventPayload):
    from_state: Literal["draft", "active"]
    to_state: Literal["active", "completed"]

    @model_validator(mode="after")
    def research_transition(self) -> Self:
        assert_contract_transition("research_task", self.from_state, self.to_state)
        return self


class DefinitionPublishedPayload(ContractEventPayload):
    product_id: UUID
    definition_digest: Digest


class ReviewFinalizedPayload(ContractEventPayload):
    review_kind: Literal["dcp", "technical_review"]
    round_no: Positive
    outcome: Literal["approved", "conditional", "hold", "rejected"]
    policy_version: Key


class InitialPlanAppliedPayload(ContractEventPayload):
    project_id: UUID
    conversion_id: UUID
    baseline_id: UUID
    candidate_digest: Digest
    receipt_id: UUID


class ProjectContractAdoptedPayload(ContractEventPayload):
    project_id: UUID
    contract_version: Key
    remediation_receipt_id: UUID


class ReservationChangedPayload(ContractEventPayload):
    project_id: UUID
    resource_id: UUID
    from_state: Literal["proposed", "reserved"]
    to_state: Literal["reserved", "released"]
    capacity_version: Positive

    @model_validator(mode="after")
    def reservation_transition(self) -> Self:
        assert_contract_transition("reservation", self.from_state, self.to_state)
        return self


class CommandFailure(Contract):
    code: Literal[
        "scope_denied",
        "object_not_found",
        "version_conflict",
        "idempotency_conflict",
        "source_stale",
        "approval_required",
        "dependency_unmet",
        "input_invalid",
        "dependency_unavailable",
    ]
    message: Text
    missing: tuple[Key, ...]
    retryable: bool
    next_action: Key | None


@dataclass(frozen=True)
class OperationContract:
    key: str
    request_schema: str
    event_type: str
    event_payload_schema: str
    producer: str
    consumers: tuple[str, ...]
    work_item: str
    policy_checks: tuple[str, ...]
    response_schema: str = "CommandResult"
    failure_schema: str = "CommandFailure"
    status: str = "candidate-not-registered"
    atomicity: str = "objects+relations+event+audit+receipt in one transaction"
    idempotency: str = (
        "unique(tenant,operation,idempotency_key); same digest reuse; different digest 409"
    )


OPERATIONS = (
    OperationContract(
        "research.start",
        "ResearchStartRequest",
        "RESEARCH_TASK_CHANGED",
        "ResearchTaskChangedPayload",
        "research_service",
        ("my_work_projection",),
        "N1-02",
        ("current_scope_acl", "owner", "draft_to_active"),
    ),
    OperationContract(
        "research.conclude",
        "ResearchConcludeRequest",
        "RESEARCH_TASK_CHANGED",
        "ResearchTaskChangedPayload",
        "research_service",
        ("research_projection", "my_work_projection"),
        "N1-02",
        ("current_scope_acl", "current_sources", "active_to_completed"),
    ),
    OperationContract(
        "definition.publish",
        "DefinitionPublishRequest",
        "DEFINITION_PUBLISHED",
        "DefinitionPublishedPayload",
        "product_definition_service",
        ("requirement_candidates",),
        "N1-06",
        (
            "definition_publisher",
            "current_source_digest",
            "required_items_confirmed",
            "published_body_immutable",
        ),
    ),
    OperationContract(
        "review.finalize",
        "ReviewFinalizeRequest",
        "REVIEW_FINALIZED",
        "ReviewFinalizedPayload",
        "review_service",
        ("gate_readiness", "plan_readiness"),
        "N1-07",
        ("review_role_policy", "current_round_sources", "required_signoffs"),
    ),
    OperationContract(
        "plan.apply",
        "InitialPlanApplyRequest",
        "INITIAL_PLAN_APPLIED",
        "InitialPlanAppliedPayload",
        "initial_plan_service",
        ("schedule_projection", "my_work_projection"),
        "N2-04",
        (
            "accepted_finding",
            "current_source_and_target_acl",
            "case_project_conversion",
            "execution_approval_digest",
            "current_required_inputs",
            "single_active_work_truth",
        ),
    ),
    OperationContract(
        "project.adopt_contract",
        "ProjectAdoptionRequest",
        "PROJECT_CONTRACT_ADOPTED",
        "ProjectContractAdoptedPayload",
        "project_contract_service",
        ("project_readiness",),
        "N2-04",
        (
            "current_project_acl",
            "unchanged_project_lifecycle",
            "remediation_receipt",
            "no_fabricated_historical_approval",
        ),
    ),
    OperationContract(
        "reservation.reserve",
        "ReservationReserveRequest",
        "RESOURCE_RESERVATION_CHANGED",
        "ReservationChangedPayload",
        "resource_service",
        ("schedule_projection",),
        "N2-02",
        (
            "current_project_resource_acl",
            "capacity_calendar_versions",
            "capacity_lock_no_overbooking",
            "approval_policy",
        ),
    ),
    OperationContract(
        "reservation.release",
        "ReservationReleaseRequest",
        "RESOURCE_RESERVATION_CHANGED",
        "ReservationChangedPayload",
        "resource_service",
        ("schedule_projection",),
        "N2-02",
        (
            "current_project_resource_acl",
            "current_reservation_version",
            "idempotent_capacity_release",
        ),
    ),
)

# Shape of permitted transitions only; no edge bypasses its operation's live guards.
LIFECYCLES = MappingProxyType(
    {
        "scoped_work_item": {
            "pending_assignment": ("ready", "cancelled"),
            "ready": ("in_progress", "cancelled"),
            "in_progress": ("submitted", "completed", "cancelled"),
            "submitted": ("in_progress", "completed", "cancelled"),
            "completed": (),
            "cancelled": (),
        },
        "research_task": {
            "draft": ("active", "cancelled"),
            "active": ("completed", "cancelled"),
            "completed": (),
            "cancelled": (),
        },
        "experiment": {
            "draft": ("approved", "cancelled"),
            "approved": ("running", "cancelled"),
            "running": ("concluded", "cancelled"),
            "concluded": (),
            "cancelled": (),
        },
        "definition": {
            "draft": ("in_review",),
            "in_review": ("draft", "published"),
            "published": (),
        },
        "review": {
            "draft": ("in_review", "withdrawn"),
            "in_review": ("finalized", "withdrawn"),
            "finalized": (),
            "withdrawn": (),
        },
        "reservation": {
            "proposed": ("reserved", "cancelled"),
            "reserved": ("released", "cancelled"),
            "released": (),
            "cancelled": (),
        },
        "project_adoption": {
            "inventoried": ("preparing",),
            "preparing": ("adopted",),
            "adopted": (),
        },
    }
)


def assert_contract_transition(object_kind: str, current: str, target: str) -> None:
    lifecycle = LIFECYCLES.get(object_kind)
    if lifecycle is None or target not in lifecycle.get(current, ()):
        raise ValueError("invalid_contract_transition")
