"""N0-01 candidate contracts derived from complete design v1.0.

These validate document shape and local consistency, NOT authorization, source
existence, database immutability, or business approval. Domain services must
re-read those facts. No model, network, database, or runtime registry changes.
"""

from __future__ import annotations

from datetime import UTC, date
from decimal import Decimal
from hashlib import sha256
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=2048, pattern=r"\S")]
Key = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.:-]+$")]
Unit = Annotated[str, Field(min_length=1, max_length=64, pattern=r"\S")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Positive = Annotated[int, Field(strict=True, ge=1)]
Nonnegative = Annotated[int, Field(strict=True, ge=0)]
Quantity = Annotated[Decimal, Field(allow_inf_nan=False, max_digits=24, decimal_places=8)]
ScopeKind = Literal[
    "tenant",
    "market_space",
    "product_line",
    "opportunity",
    "product_definition",
    "portfolio",
    "project",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ScopeRef(Contract):
    kind: ScopeKind
    ref_id: UUID


class SourceRef(Contract):
    """Internal reference; UUID/type/version alone never proves permission."""

    tenant_id: UUID
    project_id: UUID | None = None
    kind: Key
    ref_id: UUID | Positive
    version: Positive | None = None
    as_of: AwareDatetime | None = None
    digest: Digest | None = None
    locator: Text | None = None

    @model_validator(mode="after")
    def version_or_snapshot(self) -> Self:
        if self.kind == "event":
            if not isinstance(self.ref_id, int):
                raise ValueError("event_reference_requires_internal_row_id")
        elif not isinstance(self.ref_id, UUID):
            raise ValueError("business_reference_requires_uuid")
        if self.version is None and (self.as_of is None or self.digest is None):
            raise ValueError("source_version_or_snapshot_required")
        return self


class ScopedRecord(Contract):
    schema_version: Literal[1] = 1
    id: UUID
    tenant_id: UUID
    scope: ScopeRef
    version: Positive
    owner_user_id: UUID | None = None
    sources: tuple[SourceRef, ...] = ()

    @model_validator(mode="after")
    def local_scope_consistency(self) -> Self:
        if self.scope.kind == "tenant" and self.scope.ref_id != self.tenant_id:
            raise ValueError("tenant_scope_mismatch")
        if any(source.tenant_id != self.tenant_id for source in self.sources):
            raise ValueError("source_tenant_mismatch")
        # Cross-project sources require separate bilateral authorization in services.
        return self


class ApprovalRef(Contract):
    approval_id: UUID
    payload_digest: Digest
    policy_version: Key
    approved_by_user_id: UUID
    approved_at: AwareDatetime


class ScopedWorkItem(ScopedRecord):
    action_type: Key
    title: Text
    receiver_user_id: UUID | None = None
    acceptance_required: bool
    due_at: AwareDatetime | None = None
    expected_output: Text
    completion_criteria: Text
    state: Literal[
        "pending_assignment", "ready", "in_progress", "submitted", "completed", "cancelled"
    ]
    evidence: tuple[SourceRef, ...] = ()
    accepted_by_user_id: UUID | None = None
    accepted_at: AwareDatetime | None = None
    cancellation_reason: Text | None = None

    @model_validator(mode="after")
    def accountability(self) -> Self:
        if self.scope.kind == "project":
            raise ValueError("project_action_uses_existing_task")
        if self.state not in {"pending_assignment", "cancelled"} and self.owner_user_id is None:
            raise ValueError("work_owner_required")
        if (
            self.acceptance_required
            and self.state not in {"pending_assignment", "cancelled"}
            and self.receiver_user_id is None
        ):
            raise ValueError("work_receiver_required")
        if any(ref.tenant_id != self.tenant_id for ref in self.evidence):
            raise ValueError("evidence_tenant_mismatch")
        if (self.accepted_by_user_id is None) != (self.accepted_at is None):
            raise ValueError("acceptance_pair_required")
        if self.state == "completed":
            if not self.evidence:
                raise ValueError("completion_evidence_required")
            if self.acceptance_required and (
                self.accepted_at is None or self.accepted_by_user_id != self.receiver_user_id
            ):
                raise ValueError("receiver_acceptance_required")
        if self.state == "cancelled" and self.cancellation_reason is None:
            raise ValueError("cancellation_reason_required")
        return self


class ReviewRecord(ScopedRecord):
    review_kind: Literal["dcp", "technical_review"]
    round_no: Positive
    policy_version: Key
    state: Literal["draft", "in_review", "finalized", "withdrawn"]
    outcome: Literal["approved", "conditional", "hold", "rejected"] | None = None
    approval: ApprovalRef | None = None
    conditions: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def independent_review_result(self) -> Self:
        if self.state == "finalized":
            if self.outcome is None or self.approval is None or not self.sources:
                raise ValueError("finalized_review_requires_result_approval_sources")
        elif self.outcome is not None or self.approval is not None:
            raise ValueError("unfinalized_review_has_result")
        if self.outcome == "conditional" and not self.conditions:
            raise ValueError("conditional_review_requires_conditions")
        return self


class ScheduleSource(Contract):
    kind: Literal["task", "gate", "build", "test_run", "certification", "tooling"]
    tenant_id: UUID
    project_id: UUID
    ref_id: UUID
    version: Positive | None = None
    as_of: AwareDatetime | None = None
    digest: Digest | None = None

    @model_validator(mode="after")
    def source_stamp(self) -> Self:
        if self.version is None and (self.as_of is None or self.digest is None):
            raise ValueError("schedule_source_stamp_required")
        return self


class ScheduleNode(Contract):
    id: UUID
    tenant_id: UUID
    project_id: UUID
    node_kind: Literal["task", "gate", "build", "test_run", "certification", "tooling", "milestone"]
    source: ScheduleSource | None
    calendar_id: UUID

    @model_validator(mode="after")
    def exactly_one_typed_source(self) -> Self:
        if self.node_kind == "milestone":
            if self.source is not None:
                raise ValueError("independent_milestone_has_no_source")
        elif self.source is None or self.source.kind != self.node_kind:
            raise ValueError("schedule_source_kind_mismatch")
        if self.source is not None and (
            self.source.tenant_id != self.tenant_id or self.source.project_id != self.project_id
        ):
            raise ValueError("schedule_source_scope_mismatch")
        return self


class PlanNode(Contract):
    node_key: Key
    title: Text
    discipline: Key
    owner_user_id: UUID | None
    receiver_user_id: UUID | None
    expected_output: Text
    completion_criteria: Text
    effort_hours: Quantity | None = Field(ge=0)
    waiting_days: Nonnegative = 0
    estimate_basis: Text | None = None
    current_missing: tuple[Text, ...] = ()
    future_inputs: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def estimate_is_not_a_fact(self) -> Self:
        if self.effort_hours is not None and self.estimate_basis is None:
            raise ValueError("estimate_basis_required")
        return self


class PlanDependency(Contract):
    predecessor: Key
    successor: Key
    relation: Literal["fs", "ss", "ff", "sf"]
    lag: Quantity
    lag_unit: Literal["working_hours", "calendar_days"]


class PlanCandidate(ScopedRecord):
    template_version: Key
    nodes: tuple[PlanNode, ...] = Field(min_length=1)
    dependencies: tuple[PlanDependency, ...] = ()

    @model_validator(mode="after")
    def valid_dependency_graph(self) -> Self:
        keys = {node.node_key for node in self.nodes}
        if len(keys) != len(self.nodes):
            raise ValueError("duplicate_plan_node_key")
        seen: set[tuple[str, str, str]] = set()
        outgoing: dict[str, list[str]] = {key: [] for key in keys}
        indegree = dict.fromkeys(keys, 0)
        for edge in self.dependencies:
            if edge.predecessor not in keys or edge.successor not in keys:
                raise ValueError("plan_dependency_orphan")
            identity = (edge.predecessor, edge.successor, edge.relation)
            if identity in seen:
                raise ValueError("duplicate_plan_dependency")
            seen.add(identity)
            outgoing[edge.predecessor].append(edge.successor)
            indegree[edge.successor] += 1
        ready = [key for key, degree in indegree.items() if degree == 0]
        visited = 0
        while ready:
            key = ready.pop()
            visited += 1
            for target in outgoing[key]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
        if visited != len(keys):
            raise ValueError("plan_dependency_cycle")
        return self


class TimeWindow(Contract):
    start: AwareDatetime | None
    end: AwareDatetime | None

    @model_validator(mode="after")
    def chronological(self) -> Self:
        if (
            self.start is not None
            and self.end is not None
            and self.end.astimezone(UTC) < self.start.astimezone(UTC)
        ):
            raise ValueError("time_window_reversed")
        return self


class NodeTime(Contract):
    node_id: UUID
    window: TimeWindow


class TimeRecord(ScopedRecord):
    time_kind: Literal["baseline", "forecast", "commitment", "actual"]
    node_times: tuple[NodeTime, ...] = Field(min_length=1)
    fact_kind: Literal["observed", "derived", "hypothesis"]
    approval: ApprovalRef | None = None
    algorithm_version: Key | None = None
    as_of: AwareDatetime

    @model_validator(mode="after")
    def four_separate_truths(self) -> Self:
        if self.scope.kind != "project":
            raise ValueError("formal_time_requires_project")
        if len({item.node_id for item in self.node_times}) != len(self.node_times):
            raise ValueError("duplicate_node_time")
        if not self.sources:
            raise ValueError("time_sources_required")
        if self.time_kind in {"baseline", "commitment"} and self.approval is None:
            raise ValueError("time_approval_required")
        if self.time_kind == "forecast" and (
            self.algorithm_version is None or self.fact_kind != "derived"
        ):
            raise ValueError("forecast_requires_algorithm_and_derived_kind")
        if self.time_kind == "actual" and self.fact_kind != "observed":
            raise ValueError("actual_requires_observed_evidence")
        return self


class WorkCalendar(Contract):
    id: UUID
    tenant_id: UUID
    version: Positive
    timezone: Text
    working_weekdays: tuple[Annotated[int, Field(strict=True, ge=0, le=6)], ...]
    holidays: tuple[date, ...] = ()
    hours_per_workday: Quantity = Field(gt=0, le=24)

    @model_validator(mode="after")
    def valid_calendar(self) -> Self:
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("unknown_calendar_timezone") from exc
        if len(set(self.working_weekdays)) != len(self.working_weekdays):
            raise ValueError("duplicate_weekday")
        return self


class ResourceCapacity(Contract):
    id: UUID
    tenant_id: UUID
    resource_id: UUID
    calendar_id: UUID
    calendar_version: Positive
    window: TimeWindow
    capacity: Quantity = Field(ge=0)
    unit: Literal["person_hours", "equipment_hours", "slots"]
    source: SourceRef

    @model_validator(mode="after")
    def complete_capacity_window(self) -> Self:
        if self.source.tenant_id != self.tenant_id:
            raise ValueError("capacity_source_tenant_mismatch")
        if self.window.start is None or self.window.end is None:
            raise ValueError("capacity_window_required")
        return self


class SupplySnapshot(ScopedRecord):
    source_system: Key
    external_item_id: Text
    as_of: AwareDatetime
    fresh_until: AwareDatetime
    quantity: Quantity | None = Field(ge=0)
    unit: Unit
    availability: Literal["known", "unknown"]

    @model_validator(mode="after")
    def unknown_is_not_zero(self) -> Self:
        if (self.quantity is None) != (self.availability == "unknown"):
            raise ValueError("supply_quantity_availability_mismatch")
        if self.fresh_until < self.as_of:
            raise ValueError("supply_freshness_reversed")
        if not self.sources:
            raise ValueError("supply_source_required")
        return self


class Metric(Contract):
    metric_key: Key
    raw_value: Text | None
    normalized_value: Quantity | None
    unit: Unit
    conditions: tuple[Text, ...] = ()
    lower_limit: Quantity | None = None
    upper_limit: Quantity | None = None
    criterion_ref: SourceRef | None = None
    source: SourceRef | None = None
    normalization_version: Key | None = None
    verdict: Literal["passed", "failed", "unknown"]

    @model_validator(mode="after")
    def measurement_provenance(self) -> Self:
        if self.normalized_value is not None and (
            self.raw_value is None or self.source is None or self.normalization_version is None
        ):
            raise ValueError("normalized_measurement_requires_raw_source_rule")
        if self.verdict != "unknown" and (
            self.raw_value is None or self.source is None or self.criterion_ref is None
        ):
            raise ValueError("measurement_verdict_requires_evidence_and_criterion")
        if (
            self.lower_limit is not None
            and self.upper_limit is not None
            and self.lower_limit > self.upper_limit
        ):
            raise ValueError("metric_limits_reversed")
        return self


class MetricsDocument(Contract):
    schema_version: Literal[1] = 1
    metrics: tuple[Metric, ...]

    @model_validator(mode="after")
    def unique_metrics(self) -> Self:
        if len({metric.metric_key for metric in self.metrics}) != len(self.metrics):
            raise ValueError("duplicate_metric_key")
        return self


class SampleConfigurationRevision(Contract):
    id: UUID
    tenant_id: UUID
    project_id: UUID
    sample_id: UUID
    revision_no: Positive
    frozen_at: AwareDatetime
    bom_ref: SourceRef | None
    pcb_version: Text | None
    structure_version: Text | None
    firmware_ref: SourceRef | None
    key_supplier_refs: tuple[SourceRef, ...] | None
    build_date: date | None
    provenance: Literal["observed", "legacy_unknown"]
    sources: tuple[SourceRef, ...]

    @model_validator(mode="after")
    def configuration_provenance(self) -> Self:
        refs = self.sources + (self.key_supplier_refs or ())
        refs += tuple(ref for ref in (self.bom_ref, self.firmware_ref) if ref is not None)
        if any(ref.tenant_id != self.tenant_id for ref in refs):
            raise ValueError("configuration_source_tenant_mismatch")
        if any(ref.project_id not in {None, self.project_id} for ref in refs):
            raise ValueError("configuration_source_project_mismatch")
        if self.provenance == "observed" and not self.sources:
            raise ValueError("configuration_evidence_required")
        if self.provenance == "legacy_unknown" and any(
            value is not None
            for value in (
                self.bom_ref,
                self.pcb_version,
                self.structure_version,
                self.firmware_ref,
                self.key_supplier_refs,
                self.build_date,
            )
        ):
            raise ValueError("unknown_history_cannot_copy_current_configuration")
        return self


def contract_digest(contract: Contract) -> str:
    """Digest the validated payload, including defaults, in canonical JSON key order."""
    import json

    payload = json.dumps(
        contract.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return sha256(payload.encode("utf-8")).hexdigest()
