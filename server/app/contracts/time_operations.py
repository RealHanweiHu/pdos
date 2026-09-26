"""N0-01 remaining shared time, supply and validity commands. Not runtime routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.contracts.common_objects import (
    Contract,
    Digest,
    Key,
    NodeTime,
    Positive,
    SourceRef,
    Text,
    TimeWindow,
)
from app.contracts.object_operations import (
    CommandPrecondition,
    ContractEventPayload,
    OperationContract,
)


class BaselineApplyVersionRequest(CommandPrecondition):
    project_id: UUID
    candidate_digest: Digest
    approval_id: UUID
    accepted_finding_id: UUID | None
    expected_baseline_id: UUID | None


class ForecastRecomputeRequest(CommandPrecondition):
    project_id: UUID
    expected_input_digest: Digest
    expected_algorithm_version: Key
    # No caller-supplied dates or approval; the deterministic engine computes them.


class CommitmentConfirmRequest(CommandPrecondition):
    project_id: UUID
    proposed_node_times: tuple[NodeTime, ...] = Field(min_length=1)
    source_refs: tuple[SourceRef, ...] = Field(min_length=1)
    reason: Text

    @model_validator(mode="after")
    def commitment_is_explicit(self) -> Self:
        ids = [item.node_id for item in self.proposed_node_times]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_commitment_node")
        if any(item.window.end is None for item in self.proposed_node_times):
            raise ValueError("commitment_requires_promised_end")
        return self


class ActualRecordRequest(CommandPrecondition):
    project_id: UUID
    node_times: tuple[NodeTime, ...] = Field(min_length=1)
    evidence_refs: tuple[SourceRef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def actual_requires_observed_time(self) -> Self:
        ids = [item.node_id for item in self.node_times]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_actual_node")
        if any(item.window.start is None and item.window.end is None for item in self.node_times):
            raise ValueError("actual_requires_observed_time")
        return self


class ActualCorrectRequest(ActualRecordRequest):
    previous_actual_ref: SourceRef
    correction_reason: Text

    @model_validator(mode="after")
    def correction_preserves_original_reference(self) -> Self:
        if (
            self.previous_actual_ref.kind != "actual"
            or self.previous_actual_ref.project_id != self.project_id
            or self.previous_actual_ref.version is None
        ):
            raise ValueError("correction_requires_original_actual_version")
        return self


class SupplySnapshotCaptureRequest(CommandPrecondition):
    source_id: UUID
    authorized_capture_ref: SourceRef
    # Capture loads the exact authorized source; callers cannot submit an ERP write.


class VersionValidityChangeRequest(CommandPrecondition):
    subject_ref: SourceRef
    expected_control_revision: Positive
    expected_body_digest: Digest
    new_state: Literal["superseded", "withdrawn", "invalidated"]
    replacement_ref: SourceRef | None
    reason: Text

    @model_validator(mode="after")
    def supersession_reference_is_explicit(self) -> Self:
        if self.subject_ref.version is None:
            raise ValueError("validity_change_requires_subject_version")
        if (self.new_state == "superseded") != (self.replacement_ref is not None):
            raise ValueError("validity_change_replacement_mismatch")
        return self


class BaselineVersionApprovedPayload(ContractEventPayload):
    project_id: UUID
    baseline_id: UUID
    approved_candidate_digest: Digest
    approval_id: UUID


class ForecastRecalculatedPayload(ContractEventPayload):
    project_id: UUID
    forecast_id: UUID
    input_digest: Digest
    algorithm_version: Key
    completeness: Literal["complete", "partial", "not_computable"]


class CommitmentConfirmedPayload(ContractEventPayload):
    project_id: UUID
    commitment_id: UUID
    confirmation_id: UUID


class ActualRecordedPayload(ContractEventPayload):
    project_id: UUID
    actual_id: UUID
    previous_actual_id: UUID | None
    evidence_digest: Digest


class SupplySnapshotCapturedPayload(ContractEventPayload):
    source_id: UUID
    snapshot_id: UUID
    source_digest: Digest


class VersionValidityChangedPayload(ContractEventPayload):
    subject_kind: Key
    subject_version: int = Field(ge=1, strict=True)
    control_revision: int = Field(ge=1, strict=True)
    state: Literal["superseded", "withdrawn", "invalidated"]
    replacement_id: UUID | None

    @model_validator(mode="after")
    def valid_replacement(self) -> Self:
        if (self.state == "superseded") != (self.replacement_id is not None):
            raise ValueError("validity_event_replacement_mismatch")
        return self


TIME_OPERATIONS = (
    OperationContract(
        "baseline.apply_version",
        "BaselineApplyVersionRequest",
        "BASELINE_VERSION_APPROVED",
        "BaselineVersionApprovedPayload",
        "baseline_service",
        ("schedule_projection",),
        "N2-04",
        (
            "current_project_acl",
            "approved_candidate_digest",
            "accepted_if_model_finding",
            "current_source_versions",
            "immutable_previous_baseline",
            "no_commitment_or_actual_write",
        ),
    ),
    OperationContract(
        "schedule.recompute",
        "ForecastRecomputeRequest",
        "FORECAST_RECALCULATED",
        "ForecastRecalculatedPayload",
        "schedule_engine",
        ("four_time_comparison", "execution_followup"),
        "N2-06",
        (
            "current_project_acl",
            "input_and_algorithm_versions",
            "same_input_reuse",
            "no_baseline_commitment_or_actual_write",
        ),
    ),
    OperationContract(
        "commitment.confirm",
        "CommitmentConfirmRequest",
        "COMMITMENT_CONFIRMED",
        "CommitmentConfirmedPayload",
        "commitment_service",
        ("four_time_comparison",),
        "N2-07",
        (
            "authorized_commitment_confirmer",
            "current_sources",
            "explicit_human_action",
            "no_external_send",
            "no_baseline_or_actual_write",
        ),
    ),
    OperationContract(
        "actual.record",
        "ActualRecordRequest",
        "ACTUAL_RECORDED",
        "ActualRecordedPayload",
        "actual_service",
        ("forecast_recompute", "four_time_comparison"),
        "N2-07",
        (
            "actual_recorder",
            "current_evidence_acl",
            "observed_times",
            "no_model_measurement_fabrication",
        ),
    ),
    OperationContract(
        "actual.correct",
        "ActualCorrectRequest",
        "ACTUAL_RECORDED",
        "ActualRecordedPayload",
        "actual_service",
        ("forecast_recompute", "four_time_comparison"),
        "N2-07",
        (
            "actual_correction_authority",
            "original_actual_current_version",
            "current_evidence_acl",
            "append_new_revision_not_overwrite",
            "downstream_invalidation",
        ),
    ),
    OperationContract(
        "supply.capture_snapshot",
        "SupplySnapshotCaptureRequest",
        "SUPPLY_SNAPSHOT_CAPTURED",
        "SupplySnapshotCapturedPayload",
        "supply_snapshot_service",
        ("kit_recompute",),
        "N5-02",
        (
            "authorized_connector_or_import",
            "exact_source_capture",
            "current_source_acl",
            "source_asof_digest_dedup",
            "no_erp_writes",
        ),
    ),
    OperationContract(
        "version.change_validity",
        "VersionValidityChangeRequest",
        "VERSION_VALIDITY_CHANGED",
        "VersionValidityChangedPayload",
        "version_validity_service",
        ("current_reference_projection", "dependent_readiness"),
        "N0-03",
        (
            "domain_specific_validity_authority",
            "current_control_version",
            "expected_body_digest",
            "replacement_same_logical_lineage",
            "append_control_only",
            "preserve_body_and_downstream_references",
        ),
    ),
)


class PlanValidateRequest(CommandPrecondition):
    candidate_finding_id: UUID
    candidate_digest: Digest
    expected_source_digest: Digest


class CandidateTime(Contract):
    node_key: Key
    forecast: TimeWindow


class ScheduleEvaluateRequest(PlanValidateRequest):
    expected_calendar_capacity_digest: Digest


class PlanValidationResult(Contract):
    candidate_digest: Digest
    input_digest: Digest
    policy_version: Key
    source_versions: tuple[SourceRef, ...]
    valid: bool
    blocking_issues: tuple[Text, ...]
    warnings: tuple[Text, ...]

    @model_validator(mode="after")
    def blockers_are_not_green(self) -> Self:
        if self.valid == bool(self.blocking_issues):
            raise ValueError("plan_validity_blockers_inconsistent")
        return self


class ScheduleEvaluationResult(Contract):
    candidate_digest: Digest
    input_digest: Digest
    algorithm_version: Key
    source_versions: tuple[SourceRef, ...]
    completeness: Literal["complete", "partial", "not_computable"]
    node_times: tuple[CandidateTime, ...]
    critical_path: tuple[Key, ...]
    conflicts: tuple[Text, ...]
    missing: tuple[Text, ...]

    @model_validator(mode="after")
    def forecast_is_not_a_fabricated_complete_result(self) -> Self:
        keys = [item.node_key for item in self.node_times]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate_scenario_node")
        if not set(self.critical_path).issubset(keys):
            raise ValueError("critical_path_requires_computed_nodes")
        if self.completeness == "complete" and (self.missing or not self.node_times):
            raise ValueError("complete_scenario_has_missing_inputs_or_nodes")
        if self.completeness == "not_computable" and (self.node_times or not self.missing):
            raise ValueError("uncomputable_scenario_requires_missing_not_dates")
        return self


@dataclass(frozen=True)
class QueryContract:
    key: str
    request_schema: str
    response_schema: str
    work_item: str
    policy_checks: tuple[str, ...]
    side_effect: str = "read_or_simulate_no_business_write"
    status: str = "candidate-not-registered"


QUERY_CONTRACTS = (
    QueryContract(
        "plan.validate",
        "PlanValidateRequest",
        "PlanValidationResult",
        "N2-03",
        ("current_candidate_acl", "current_source_digest", "current_vs_future_inputs"),
    ),
    QueryContract(
        "schedule.evaluate",
        "ScheduleEvaluateRequest",
        "ScheduleEvaluationResult",
        "N2-01",
        (
            "current_candidate_acl",
            "calendar_capacity_source_versions",
            "deterministic_engine",
            "no_formal_reservation_or_time_write",
        ),
    ),
)
