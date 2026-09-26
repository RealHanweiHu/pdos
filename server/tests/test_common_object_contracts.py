from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.common_objects import (
    Contract,
    Metric,
    MetricsDocument,
    PlanCandidate,
    ResourceCapacity,
    ReviewRecord,
    SampleConfigurationRevision,
    ScheduleNode,
    ScopedRecord,
    ScopedWorkItem,
    SourceRef,
    SupplySnapshot,
    TimeRecord,
    TimeWindow,
    WorkCalendar,
    contract_digest,
)
from app.contracts.runtime_records import (
    AuthorizationEnvelope,
    CompactionRecord,
    ContextManifest,
    Observation,
    OperationReceipt,
    RunControl,
)
from scripts.export_common_contracts import candidate_models, candidate_openapi

NOW = datetime(2026, 9, 10, tzinfo=UTC)
TENANT = uuid4()
PROJECT = uuid4()
USER = uuid4()
SOURCE: dict[str, Any] = {
    "tenant_id": TENANT,
    "project_id": PROJECT,
    "kind": "requirement",
    "ref_id": uuid4(),
    "version": 1,
}
SCOPED: dict[str, Any] = {
    "id": uuid4(),
    "tenant_id": TENANT,
    "scope": {"kind": "project", "ref_id": PROJECT},
    "version": 1,
    "sources": [SOURCE],
}
APPROVAL: dict[str, Any] = {
    "approval_id": uuid4(),
    "payload_digest": "a" * 64,
    "policy_version": "policy.v1",
    "approved_by_user_id": USER,
    "approved_at": NOW,
}


def node(key: str) -> dict[str, Any]:
    return {
        "node_key": key,
        "title": key,
        "discipline": "ID",
        "owner_user_id": None,
        "receiver_user_id": None,
        "expected_output": "design",
        "completion_criteria": "review",
        "effort_hours": None,
    }


def edge(a: str, b: str) -> dict[str, Any]:
    return {
        "predecessor": a,
        "successor": b,
        "relation": "fs",
        "lag": "0",
        "lag_unit": "working_hours",
    }


def test_draft_plan_preserves_unknown_owners_and_future_inputs() -> None:
    plan = PlanCandidate.model_validate(
        {
            **SCOPED,
            "template_version": "npd.v1",
            "nodes": [node("ID"), node("PCB")],
            "dependencies": [edge("ID", "PCB")],
        }
    )
    assert plan.nodes[0].effort_hours is None
    assert plan.nodes[0].owner_user_id is None
    assert contract_digest(plan) == contract_digest(
        PlanCandidate.model_validate_json(plan.model_dump_json())
    )
    assert contract_digest(plan) != contract_digest(plan.model_copy(update={"version": 2}))
    with pytest.raises(ValidationError):
        plan.version = 2


@pytest.mark.parametrize(
    "dependencies,error",
    [
        ([edge("ID", "MISSING")], "plan_dependency_orphan"),
        ([edge("ID", "PCB"), edge("PCB", "ID")], "plan_dependency_cycle"),
        ([edge("ID", "ID")], "plan_dependency_cycle"),
        ([edge("ID", "PCB"), edge("ID", "PCB")], "duplicate_plan_dependency"),
    ],
)
def test_plan_rejects_broken_graph(dependencies: list[dict[str, Any]], error: str) -> None:
    with pytest.raises(ValidationError, match=error):
        PlanCandidate.model_validate(
            {
                **SCOPED,
                "template_version": "v1",
                "nodes": [node("ID"), node("PCB")],
                "dependencies": dependencies,
            }
        )


def test_duplicate_nodes_and_fabricated_estimate_rejected() -> None:
    for nodes, error in [
        ([node("ID"), node("ID")], "duplicate_plan_node_key"),
        ([{**node("ID"), "effort_hours": "10"}], "estimate_basis_required"),
    ]:
        with pytest.raises(ValidationError, match=error):
            PlanCandidate.model_validate({**SCOPED, "template_version": "v1", "nodes": nodes})


@pytest.mark.parametrize(
    "model,payload,error",
    [
        (
            ScopedRecord,
            {**SCOPED, "scope": {"kind": "tenant", "ref_id": uuid4()}},
            "tenant_scope_mismatch",
        ),
        (
            ScopedRecord,
            {**SCOPED, "sources": [{**SOURCE, "tenant_id": uuid4()}]},
            "source_tenant_mismatch",
        ),
        (SourceRef, {**SOURCE, "version": None}, "source_version_or_snapshot_required"),
        (TimeWindow, {"start": NOW, "end": NOW - timedelta(seconds=1)}, "time_window_reversed"),
        (TimeWindow, {"start": datetime(2026, 9, 10), "end": None}, "timezone_aware"),
        (ScopedRecord, {**SCOPED, "approved_by_model": True}, "extra_forbidden"),
        (ScopedRecord, {**SCOPED, "version": True}, "int_type"),
        (
            WorkCalendar,
            {
                "id": uuid4(),
                "tenant_id": TENANT,
                "version": 1,
                "timezone": "Mars/Base",
                "working_weekdays": [0],
                "hours_per_workday": "8",
            },
            "unknown_calendar_timezone",
        ),
    ],
)
def test_invalid_common_shape(model: type[Contract], payload: dict[str, Any], error: str) -> None:
    with pytest.raises(ValidationError, match=error):
        model.model_validate(payload)


def test_schedule_requires_one_matching_local_source() -> None:
    payload: dict[str, Any] = {
        "id": uuid4(),
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "calendar_id": uuid4(),
        "node_kind": "task",
        "source": {**SOURCE, "kind": "task"},
    }
    ScheduleNode.model_validate(payload)
    ScheduleNode.model_validate({**payload, "node_kind": "milestone", "source": None})
    for source in (
        None,
        {**payload["source"], "kind": "gate"},
        {**payload["source"], "project_id": uuid4()},
    ):
        with pytest.raises(ValidationError, match="schedule_source"):
            ScheduleNode.model_validate({**payload, "source": source})
    with pytest.raises(ValidationError, match="independent_milestone"):
        ScheduleNode.model_validate({**payload, "node_kind": "milestone"})


def test_scoped_work_requires_real_acceptance_and_evidence() -> None:
    payload: dict[str, Any] = {
        **SCOPED,
        "scope": {"kind": "opportunity", "ref_id": uuid4()},
        "owner_user_id": USER,
        "action_type": "sqe_review",
        "title": "review supplier",
        "acceptance_required": True,
        "receiver_user_id": USER,
        "expected_output": "report",
        "completion_criteria": "reviewed",
        "state": "completed",
        "evidence": [SOURCE],
        "accepted_by_user_id": USER,
        "accepted_at": NOW,
    }
    ScopedWorkItem.model_validate(payload)
    changes: list[tuple[dict[str, Any], str]] = [
        ({"evidence": []}, "completion_evidence_required"),
        ({"accepted_at": None, "accepted_by_user_id": None}, "receiver_acceptance_required"),
        ({"scope": SCOPED["scope"]}, "project_action_uses_existing_task"),
        ({"owner_user_id": None}, "work_owner_required"),
    ]
    for change, error in changes:
        with pytest.raises(ValidationError, match=error):
            ScopedWorkItem.model_validate({**payload, **change})


def test_dcp_and_tr_results_cannot_be_inferred_from_meeting() -> None:
    payload: dict[str, Any] = {
        **SCOPED,
        "review_kind": "dcp",
        "round_no": 1,
        "policy_version": "v1",
        "state": "finalized",
        "outcome": "approved",
        "approval": APPROVAL,
    }
    ReviewRecord.model_validate(payload)
    change: dict[str, Any]
    for change in (
        {"approval": None},
        {"sources": []},
        {"state": "in_review"},
        {"outcome": "conditional"},
    ):
        with pytest.raises(ValidationError):
            ReviewRecord.model_validate({**payload, **change})


@pytest.mark.parametrize("kind", ["baseline", "commitment", "forecast", "actual"])
def test_four_time_truths_require_their_own_authority(kind: str) -> None:
    payload: dict[str, Any] = {
        **SCOPED,
        "time_kind": kind,
        "node_times": [{"node_id": uuid4(), "window": {"start": NOW, "end": None}}],
        "fact_kind": "observed" if kind == "actual" else "derived",
        "as_of": NOW,
        "approval": APPROVAL if kind in {"baseline", "commitment"} else None,
        "algorithm_version": "schedule.v1" if kind == "forecast" else None,
    }
    TimeRecord.model_validate(payload)
    change = (
        {"approval": None} if kind in {"baseline", "commitment"} else {"fact_kind": "hypothesis"}
    )
    with pytest.raises(ValidationError):
        TimeRecord.model_validate({**payload, **change})


def test_supply_unknown_stays_null_and_capacity_requires_source_scope() -> None:
    payload: dict[str, Any] = {
        **SCOPED,
        "source_system": "ERP",
        "external_item_id": "P1",
        "as_of": NOW,
        "fresh_until": NOW,
        "quantity": None,
        "unit": "piece",
        "availability": "unknown",
    }
    SupplySnapshot.model_validate(payload)
    with pytest.raises(ValidationError, match="supply_quantity_availability_mismatch"):
        SupplySnapshot.model_validate({**payload, "quantity": "0"})
    with pytest.raises(ValidationError, match="capacity_source_tenant_mismatch"):
        ResourceCapacity.model_validate(
            {
                "id": uuid4(),
                "tenant_id": TENANT,
                "resource_id": uuid4(),
                "calendar_id": uuid4(),
                "calendar_version": 1,
                "window": {"start": NOW, "end": NOW},
                "capacity": "8",
                "unit": "person_hours",
                "source": {**SOURCE, "tenant_id": uuid4()},
            }
        )


def test_metrics_require_raw_source_criterion_and_keep_zero() -> None:
    metric = {
        "metric_key": "pressure",
        "raw_value": "0",
        "normalized_value": "0",
        "unit": "kPa",
        "source": SOURCE,
        "normalization_version": "v1",
        "criterion_ref": SOURCE,
        "verdict": "failed",
    }
    assert Metric.model_validate(metric).normalized_value == 0
    change: dict[str, Any]
    for change in (
        {"raw_value": None},
        {"source": None},
        {"criterion_ref": None},
        {"normalized_value": "NaN"},
    ):
        with pytest.raises(ValidationError):
            Metric.model_validate({**metric, **change})
    with pytest.raises(ValidationError, match="duplicate_metric_key"):
        MetricsDocument.model_validate({"metrics": [metric, metric]})


def test_unknown_legacy_configuration_never_copies_today() -> None:
    payload: dict[str, Any] = {
        "id": uuid4(),
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "sample_id": uuid4(),
        "revision_no": 1,
        "frozen_at": NOW,
        "bom_ref": None,
        "pcb_version": None,
        "structure_version": None,
        "firmware_ref": None,
        "key_supplier_refs": None,
        "build_date": None,
        "provenance": "legacy_unknown",
        "sources": [],
    }
    SampleConfigurationRevision.model_validate(payload)
    with pytest.raises(ValidationError, match="unknown_history"):
        SampleConfigurationRevision.model_validate({**payload, "pcb_version": "current-pcb"})


def test_authorization_envelope_is_bounded_and_not_model_scope() -> None:
    payload: dict[str, Any] = {
        **SCOPED,
        "run_id": uuid4(),
        "lineage_id": uuid4(),
        "principal_kind": "service",
        "principal_id": uuid4(),
        "trigger_actor_user_id": None,
        "policy_version": "v1",
        "purpose": "research",
        "issued_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
        "capability_version": "v1",
        "toolset_version": "v1",
    }
    AuthorizationEnvelope.model_validate(payload)
    change: dict[str, Any]
    for change in (
        {"expires_at": NOW},
        {"scope": {"kind": "tenant", "ref_id": TENANT}, "sources": []},
    ):
        with pytest.raises(ValidationError):
            AuthorizationEnvelope.model_validate({**payload, **change})


def test_manifest_revision_and_observation_provenance() -> None:
    payload: dict[str, Any] = {
        "id": uuid4(),
        "tenant_id": TENANT,
        "run_id": uuid4(),
        "authorization_id": uuid4(),
        "revision_no": 1,
        "parent_revision_id": None,
        "goal_revision": 1,
        "release_bundle_version": "v1",
        "capability_version": "v1",
        "prompt_version": "v1",
        "skill_versions": [],
        "toolset_version": "v1",
        "projection_version": "v1",
        "model_qualification_version": "v1",
        "output_schema_version": "v1",
        "policy_version": "v1",
        "observation_ids": [],
        "event_watermark": 0,
        "selected_sources": [SOURCE],
        "omission_reasons": [],
        "estimated_input_tokens": 100,
        "reserved_output_tokens": 100,
        "completeness": "complete",
        "missing": [],
        "built_at": NOW,
        "digest": "a" * 64,
    }
    ContextManifest.model_validate(payload)
    change: dict[str, Any]
    for change in (
        {"revision_no": 2},
        {"missing": ["no source"]},
        {"selected_sources": [{**SOURCE, "tenant_id": uuid4()}]},
    ):
        with pytest.raises(ValidationError):
            ContextManifest.model_validate({**payload, **change})
    observation: dict[str, Any] = {
        "id": uuid4(),
        "tenant_id": TENANT,
        "run_id": uuid4(),
        "tool_call_id": uuid4(),
        "parent_observation_id": None,
        "sequence": 1,
        "tool_version": "v1",
        "status": "completed",
        "sources": [SOURCE],
        "observed_at": NOW,
        "as_of": NOW,
        "fresh_until": None,
        "acl_policy_version": "v1",
        "allowed_purpose": "research",
        "taint": "untrusted_external",
        "input_digest": "a" * 64,
        "output_digest": "b" * 64,
        "shown_count": 0,
        "total_count": 0,
        "truncated": False,
        "continuation": None,
    }
    Observation.model_validate(observation)
    for change in (
        {"status": "unavailable"},
        {"total_count": 2},
        {"truncated": True, "total_count": 2},
    ):
        with pytest.raises(ValidationError):
            Observation.model_validate({**observation, **change})


def test_compaction_retains_acl_dependencies_and_original_read_path() -> None:
    observation_id = uuid4()
    payload: dict[str, Any] = {
        "id": uuid4(),
        "tenant_id": TENANT,
        "run_id": uuid4(),
        "manifest_id": uuid4(),
        "observation_ids": [observation_id],
        "source_acl_dependencies": [SOURCE],
        "compressor_version": "v1",
        "summary_digest": "a" * 64,
        "exact_facts": [],
        "approval_ids": [],
        "unresolved": [],
        "omitted": [],
        "reread_observation_ids": [observation_id],
    }
    CompactionRecord.model_validate(payload)
    change: dict[str, Any]
    for change in (
        {"source_acl_dependencies": []},
        {"source_acl_dependencies": [{**SOURCE, "tenant_id": uuid4()}]},
        {"reread_observation_ids": [uuid4()]},
    ):
        with pytest.raises(ValidationError):
            CompactionRecord.model_validate({**payload, **change})


def test_waiting_releases_lease_and_completion_has_specific_outcome() -> None:
    payload: dict[str, Any] = {
        "run_id": uuid4(),
        "tenant_id": TENANT,
        "lineage_id": uuid4(),
        "generation": 1,
        "attempt": 1,
        "lease_token": None,
        "lease_expires_at": None,
        "checkpoint_id": uuid4(),
        "budget_ledger_id": uuid4(),
        "absolute_deadline": NOW,
        "state": "waiting_input",
    }
    RunControl.model_validate(payload)
    change: dict[str, Any]
    for change in (
        {"checkpoint_id": None},
        {"lease_token": uuid4(), "lease_expires_at": NOW},
        {"state": "completed"},
    ):
        with pytest.raises(ValidationError):
            RunControl.model_validate({**payload, **change})


def test_receipt_requires_separate_review_apply_and_execution_evidence() -> None:
    payload: dict[str, Any] = {
        "id": uuid4(),
        "tenant_id": TENANT,
        "source_run_id": uuid4(),
        "finding_id": uuid4(),
        "candidate_digest": "a" * 64,
        "idempotency_key": "apply-1",
        "reviewed_by_user_id": USER,
        "reviewed_at": NOW,
        "applied_by_user_id": USER,
        "applied_at": NOW,
        "status": "applied",
        "targets": [{"node_key": "ID", "target": SOURCE}],
        "event_row_ids": [11],
        "audit_row_ids": [12],
        "execution_state": "pending",
        "execution_evidence": [],
    }
    assert OperationReceipt.model_validate(payload).execution_state == "pending"
    change: dict[str, Any]
    for change in (
        {"reviewed_at": None, "reviewed_by_user_id": None},
        {"execution_state": "completed"},
        {"status": "receipt_unknown"},
    ):
        with pytest.raises(ValidationError):
            OperationReceipt.model_validate({**payload, **change})


def test_export_resolves_every_schema_ref_and_advertises_no_fake_endpoint() -> None:
    document = candidate_openapi()
    assert document["paths"] == {}
    assert set(candidate_models()).issubset(document["components"]["schemas"])

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if "$ref" in value:
                assert value["$ref"].startswith("#/components/schemas/")
                assert value["$ref"].split("/")[-1] in document["components"]["schemas"]
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(document)
