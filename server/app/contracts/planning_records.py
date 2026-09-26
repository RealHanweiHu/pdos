"""N0-01 conversion, compatibility and shared resource contract candidates."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.auth.roles import Role
from app.contracts.common_objects import (
    ApprovalRef,
    Contract,
    Digest,
    Key,
    Positive,
    Quantity,
    ScopeRef,
    SourceRef,
    Text,
    TimeWindow,
)


class ProjectRoleAssignment(Contract):
    """Candidate fields only; no role is granted by validating this document."""

    tenant_id: UUID
    project_id: UUID
    user_id: UUID
    tenant_role: Role
    project_role: Role | None
    disciplines: tuple[Key, ...]
    effective_from: AwareDatetime
    effective_until: AwareDatetime | None

    @model_validator(mode="after")
    def responsibility_is_time_bounded(self) -> Self:
        if self.effective_until is not None and self.effective_until <= self.effective_from:
            raise ValueError("project_role_effective_window_invalid")
        return self


class CaseProjectConversion(Contract):
    id: UUID
    tenant_id: UUID
    case_ref: SourceRef
    project_id: UUID
    converted_by_user_id: UUID
    converted_at: AwareDatetime
    event_row_id: Positive
    audit_row_id: Positive

    @model_validator(mode="after")
    def conversion_anchor(self) -> Self:
        if self.case_ref.kind != "development_case" or self.case_ref.tenant_id != self.tenant_id:
            raise ValueError("conversion_case_scope_invalid")
        return self


class WorkItemTransfer(Contract):
    source_work_item_id: UUID
    source_version: Positive
    source_state: Literal[
        "pending_assignment", "ready", "in_progress", "submitted", "completed", "cancelled"
    ]
    disposition: Literal["retain_history", "transfer_remaining"]
    target_task_id: UUID | None
    remaining_work: Text | None
    evidence_refs: tuple[SourceRef, ...]

    @model_validator(mode="after")
    def one_active_execution_truth(self) -> Self:
        if self.source_state in {"completed", "cancelled"} and self.disposition != "retain_history":
            raise ValueError("terminal_work_cannot_be_reopened_by_transfer")
        if self.disposition == "retain_history":
            if self.target_task_id is not None or self.remaining_work is not None:
                raise ValueError("retained_history_cannot_create_active_task")
        elif self.target_task_id is None or self.remaining_work is None:
            raise ValueError("transfer_requires_target_and_remaining_work")
        return self


class InitialPlanApplication(Contract):
    id: UUID
    tenant_id: UUID
    project_id: UUID
    conversion_id: UUID
    source_scope: ScopeRef
    finding_id: UUID | None
    candidate_digest: Digest
    execution_approval: ApprovalRef
    baseline_id: UUID
    operation_receipt_id: UUID
    work_transfers: tuple[WorkItemTransfer, ...]

    @model_validator(mode="after")
    def bind_application_to_approved_payload(self) -> Self:
        if self.execution_approval.payload_digest != self.candidate_digest:
            raise ValueError("initial_plan_approved_digest_mismatch")
        if self.source_scope.kind == "tenant" and self.source_scope.ref_id != self.tenant_id:
            raise ValueError("initial_plan_source_tenant_mismatch")
        if self.source_scope.kind == "project" and self.source_scope.ref_id != self.project_id:
            raise ValueError("initial_plan_source_project_mismatch")
        ids = [transfer.source_work_item_id for transfer in self.work_transfers]
        targets = [
            transfer.target_task_id
            for transfer in self.work_transfers
            if transfer.target_task_id is not None
        ]
        if len(ids) != len(set(ids)) or len(targets) != len(set(targets)):
            raise ValueError("initial_plan_duplicate_transfer_mapping")
        if any(
            ref.tenant_id != self.tenant_id
            for transfer in self.work_transfers
            for ref in transfer.evidence_refs
        ):
            raise ValueError("initial_plan_transfer_source_tenant_mismatch")
        return self


class ProjectContractAdoption(Contract):
    """Independent compatibility record; never adds a new Project lifecycle state."""

    id: UUID
    tenant_id: UUID
    project_id: UUID
    contract_version: Key
    policy_version: Key
    captured_at: AwareDatetime
    historical_status: Literal[
        "draft", "proposed", "approved", "active", "on_hold", "completed", "archived"
    ]
    snapshot_ref: SourceRef
    preserved_approval_ids: tuple[UUID, ...]
    missing: tuple[Text, ...]
    state: Literal["inventoried", "preparing", "adopted"]
    remediation_receipt_id: UUID | None
    adopted_at: AwareDatetime | None
    adopted_by_user_id: UUID | None

    @model_validator(mode="after")
    def adoption_never_fabricates_old_approval(self) -> Self:
        if (
            self.snapshot_ref.tenant_id != self.tenant_id
            or self.snapshot_ref.project_id != self.project_id
        ):
            raise ValueError("adoption_snapshot_scope_mismatch")
        if self.state == "adopted":
            if (
                self.missing
                or self.remediation_receipt_id is None
                or self.adopted_at is None
                or self.adopted_by_user_id is None
            ):
                raise ValueError("adoption_requires_resolved_gaps_and_receipt")
            if self.adopted_at < self.captured_at:
                raise ValueError("adoption_precedes_inventory")
        elif self.adopted_at is not None or self.adopted_by_user_id is not None:
            raise ValueError("unfinished_adoption_has_completion")
        return self


class ResourceIdentity(Contract):
    id: UUID
    tenant_id: UUID
    version: Positive
    code: Key
    name: Text
    resource_kind: Literal[
        "person",
        "skill_group",
        "laboratory",
        "test_bench",
        "equipment",
        "mold",
        "fixture",
        "pilot_line",
    ]
    owner_user_id: UUID
    calendar_id: UUID
    calendar_version: Positive
    capabilities: tuple[Key, ...]
    status: Literal["active", "unavailable", "retired"]
    legacy_resource_ids: tuple[UUID, ...] = ()


class ResourceReservation(Contract):
    id: UUID
    tenant_id: UUID
    project_id: UUID
    version: Positive
    resource_id: UUID
    capacity_version: Positive
    calendar_version: Positive
    node_id: UUID
    owner_user_id: UUID
    window: TimeWindow
    amount: Quantity = Field(gt=0)
    unit: Literal["person_hours", "equipment_hours", "slots"]
    priority_policy_version: Key
    state: Literal["proposed", "reserved", "released", "cancelled"]
    approval: ApprovalRef | None
    reservation_receipt_id: UUID | None
    reserved_at: AwareDatetime | None
    released_at: AwareDatetime | None
    release_reason: Text | None

    @model_validator(mode="after")
    def reservation_is_not_scenario(self) -> Self:
        if (self.reserved_at is None) != (self.reservation_receipt_id is None):
            raise ValueError("reservation_time_receipt_pair_required")
        if self.reserved_at is not None and self.approval is None:
            raise ValueError("recorded_reservation_requires_approval")
        if (
            self.window.start is None
            or self.window.end is None
            or self.window.start >= self.window.end
        ):
            raise ValueError("reservation_requires_positive_window")
        if self.state == "proposed" and (
            self.reservation_receipt_id is not None
            or self.reserved_at is not None
            or self.released_at is not None
        ):
            raise ValueError("scenario_cannot_occupy_capacity")
        if self.state in {"reserved", "released"} and (
            self.approval is None or self.reservation_receipt_id is None or self.reserved_at is None
        ):
            raise ValueError("reservation_requires_approval_and_receipt")
        if self.state == "reserved" and self.released_at is not None:
            raise ValueError("active_reservation_has_release")
        if self.state in {"released", "cancelled"} and (
            self.released_at is None or self.release_reason is None
        ):
            raise ValueError("reservation_release_reason_required")
        if (
            self.released_at is not None
            and self.reserved_at is not None
            and self.released_at < self.reserved_at
        ):
            raise ValueError("reservation_release_precedes_reservation")
        return self
