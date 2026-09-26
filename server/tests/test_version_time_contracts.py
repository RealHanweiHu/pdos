from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.time_operations import (
    TIME_OPERATIONS,
    ActualCorrectRequest,
    ActualRecordRequest,
    CommitmentConfirmRequest,
    ForecastRecomputeRequest,
    VersionValidityChangedPayload,
    VersionValidityChangeRequest,
)
from app.contracts.version_lifecycle import (
    LegacyContextCompatibility,
    RuntimeReleaseBundle,
    VersionValidity,
)
from app.events.catalog import EVENT_REGISTRY
from scripts.export_common_contracts import candidate_models

TENANT, PROJECT = uuid4(), uuid4()
NOW = datetime(2026, 9, 10, tzinfo=UTC)
DIGEST = "a" * 64


def source(kind: str = "product_definition", version: int = 1) -> dict[str, Any]:
    return {
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "kind": kind,
        "ref_id": uuid4(),
        "version": version,
    }


def control() -> dict[str, Any]:
    return {
        "id": uuid4(),
        "tenant_id": TENANT,
        "subject": source(),
        "body_digest": DIGEST,
        "control_revision": 1,
        "previous_control_id": None,
        "state": "active",
        "replacement": None,
        "reason": "initial publication",
        "policy_version": "v1",
        "decided_by_kind": "user",
        "decided_by_id": uuid4(),
        "decided_at": NOW,
        "effective_at": NOW,
        "operation_id": uuid4(),
        "source_dependencies": [],
    }


def command() -> dict[str, Any]:
    return {"expected_version": 1, "payload_digest": DIGEST, "idempotency_key": "operation-1"}


def test_supersession_creates_control_revision_without_mutating_published_body() -> None:
    original = VersionValidity.model_validate(control())
    original_json = original.model_dump_json()
    replacement = source(version=2)
    revised = VersionValidity.model_validate(
        {
            **original.model_dump(),
            "id": uuid4(),
            "control_revision": 2,
            "previous_control_id": original.id,
            "state": "superseded",
            "replacement": replacement,
            "reason": "new definition version",
        }
    )
    assert revised.body_digest == original.body_digest
    assert original.model_dump_json() == original_json
    assert original.state == "active"
    with pytest.raises(ValidationError):
        original.state = "superseded"


@pytest.mark.parametrize(
    "change,error",
    [
        ({"control_revision": 2}, "validity_previous_control_required"),
        ({"state": "superseded"}, "supersession_requires_replacement_only"),
        ({"replacement": source(version=2)}, "supersession_requires_replacement_only"),
        ({"tenant_id": uuid4()}, "validity_subject_requires_tenant_and_version"),
        (
            {"source_dependencies": [{**source(), "tenant_id": uuid4()}]},
            "validity_source_tenant_mismatch",
        ),
    ],
)
def test_invalid_control_metadata_is_rejected(change: dict[str, Any], error: str) -> None:
    with pytest.raises(ValidationError, match=error):
        VersionValidity.model_validate({**control(), **change})


@pytest.mark.parametrize(
    "replacement",
    [
        source(version=1),
        {**source(version=2), "tenant_id": uuid4()},
        {**source(version=2), "project_id": uuid4()},
        source(kind="baseline", version=2),
    ],
)
def test_replacement_cannot_cross_scope_type_or_point_backward(replacement: dict[str, Any]) -> None:
    with pytest.raises(
        ValidationError, match="replacement_requires_same_scope_kind_and_newer_version"
    ):
        VersionValidity.model_validate(
            {**control(), "state": "superseded", "replacement": replacement}
        )


def bundle() -> dict[str, Any]:
    kinds = [
        "capability",
        "schema",
        "prompt",
        "tool",
        "projection",
        "policy",
        "model_qualification",
        "golden_suite",
    ]
    return {
        "id": uuid4(),
        "version": "local.v1",
        "code_digest": DIGEST,
        "migration_head": "0058_ai_test_plan_changes",
        "compatible_context_versions": [3],
        "components": [
            {"kind": kind, "key": kind, "version": "v1", "digest": DIGEST} for kind in kinds
        ],
        "released_by_user_id": uuid4(),
        "released_at": NOW,
    }


def test_release_bundle_requires_exact_qualified_components() -> None:
    payload = bundle()
    release = RuntimeReleaseBundle.model_validate(payload)
    with pytest.raises(ValidationError, match="release_bundle_required_components_missing"):
        RuntimeReleaseBundle.model_validate({**payload, "components": payload["components"][:-1]})
    with pytest.raises(ValidationError, match="duplicate_release_component"):
        RuntimeReleaseBundle.model_validate({**payload, "components": payload["components"] * 2})
    with pytest.raises(ValidationError):
        release.version = "hot-swap"


def test_legacy_read_adapter_cannot_mint_new_authorization() -> None:
    payload = {
        "run_id": uuid4(),
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "original_digest": DIGEST,
        "adapter_version": "v1",
        "missing_fields": ["authorization_envelope"],
    }
    legacy = LegacyContextCompatibility.model_validate(payload)
    assert legacy.resumable is False
    assert legacy.continuation_action == "create_new_authorized_run"
    for change in (
        {"resumable": True},
        {"authorization_status": "approved"},
        {"authorization_id": uuid4()},
    ):
        with pytest.raises(ValidationError):
            LegacyContextCompatibility.model_validate({**payload, **change})


def test_forecast_recompute_does_not_accept_predicted_dates_or_business_approval() -> None:
    payload = {
        **command(),
        "project_id": PROJECT,
        "expected_input_digest": DIGEST,
        "expected_algorithm_version": "schedule.v1",
    }
    ForecastRecomputeRequest.model_validate(payload)
    for field in ("forecast_end", "baseline_id", "commitment_date", "approved_by_user_id"):
        with pytest.raises(ValidationError, match="extra_forbidden"):
            ForecastRecomputeRequest.model_validate({**payload, field: str(NOW)})


def test_commitment_requires_explicit_finish_and_no_duplicate_nodes() -> None:
    node_time = {"node_id": uuid4(), "window": {"start": None, "end": NOW}}
    payload = {
        **command(),
        "project_id": PROJECT,
        "proposed_node_times": [node_time],
        "source_refs": [source()],
        "reason": "confirmed delivery date",
    }
    CommitmentConfirmRequest.model_validate(payload)
    with pytest.raises(ValidationError, match="commitment_requires_promised_end"):
        CommitmentConfirmRequest.model_validate(
            {
                **payload,
                "proposed_node_times": [{**node_time, "window": {"start": None, "end": None}}],
            }
        )
    with pytest.raises(ValidationError, match="duplicate_commitment_node"):
        CommitmentConfirmRequest.model_validate(
            {**payload, "proposed_node_times": [node_time, node_time]}
        )


def test_actual_correction_requires_original_version_and_new_evidence() -> None:
    payload = {
        **command(),
        "project_id": PROJECT,
        "node_times": [{"node_id": uuid4(), "window": {"start": NOW, "end": None}}],
        "evidence_refs": [source("test_run")],
    }
    ActualRecordRequest.model_validate(payload)
    correct = {
        **payload,
        "previous_actual_ref": source("actual"),
        "correction_reason": "correct mistaken start from original report",
    }
    ActualCorrectRequest.model_validate(correct)
    with pytest.raises(ValidationError, match="correction_requires_original_actual_version"):
        ActualCorrectRequest.model_validate({**correct, "previous_actual_ref": source("forecast")})
    with pytest.raises(ValidationError):
        ActualCorrectRequest.model_validate({**correct, "evidence_refs": []})


def test_validity_command_and_event_cannot_silently_replace_versions() -> None:
    payload = {
        **command(),
        "subject_ref": source(),
        "expected_control_revision": 1,
        "expected_body_digest": DIGEST,
        "new_state": "superseded",
        "replacement_ref": source(version=2),
        "reason": "replace by reviewed revision",
    }
    VersionValidityChangeRequest.model_validate(payload)
    with pytest.raises(ValidationError, match="validity_change_replacement_mismatch"):
        VersionValidityChangeRequest.model_validate({**payload, "replacement_ref": None})
    event = {
        "object_id": uuid4(),
        "object_version": 1,
        "operation_id": uuid4(),
        "correlation_id": uuid4(),
        "causation_event_row_id": None,
        "subject_kind": "product_definition",
        "subject_version": 1,
        "control_revision": 2,
        "state": "withdrawn",
        "replacement_id": None,
    }
    VersionValidityChangedPayload.model_validate(event)
    with pytest.raises(ValidationError, match="validity_event_replacement_mismatch"):
        VersionValidityChangedPayload.model_validate({**event, "replacement_id": uuid4()})


def test_time_operations_remain_review_contracts_and_all_shapes_resolve() -> None:
    models = candidate_models()
    adopted_events = {"SUPPLY_SNAPSHOT_CAPTURED"}
    assert {op.event_type for op in TIME_OPERATIONS if op.event_type in EVENT_REGISTRY} == (
        adopted_events
    )
    for operation in TIME_OPERATIONS:
        assert operation.request_schema in models
        assert operation.event_payload_schema in models
        if operation.event_type not in adopted_events:
            assert operation.event_type not in EVENT_REGISTRY
        assert operation.policy_checks


def test_event_and_audit_references_match_real_writer_identifiers() -> None:
    from app.contracts.common_objects import SourceRef
    from app.contracts.object_operations import CommandResult
    from app.events.writer import WrittenEventAudit

    written = WrittenEventAudit(event_row_id=21, audit_row_id=22)
    result = CommandResult.model_validate(
        {
            "operation_id": uuid4(),
            "disposition": "created",
            "status": "applied",
            "targets": [source()],
            "event_row_ids": [written.event_row_id],
            "audit_row_ids": [written.audit_row_id],
            "next_action": None,
        }
    )
    assert result.event_row_ids == (21,)
    assert result.audit_row_ids == (22,)
    SourceRef.model_validate({**source("event"), "ref_id": written.event_row_id})
    with pytest.raises(ValidationError, match="event_reference_requires_internal_row_id"):
        SourceRef.model_validate(source("event"))
    with pytest.raises(ValidationError, match="business_reference_requires_uuid"):
        SourceRef.model_validate({**source(), "ref_id": 21})
    with pytest.raises(ValidationError):
        CommandResult.model_validate({**result.model_dump(), "audit_row_ids": [uuid4()]})
    with pytest.raises(ValidationError):
        SourceRef.model_validate({**source("event"), "ref_id": True})


def test_plan_validation_and_scenario_fail_closed_on_missing_facts() -> None:
    from app.contracts.time_operations import PlanValidationResult, ScheduleEvaluationResult

    plan = {
        "candidate_digest": DIGEST,
        "input_digest": DIGEST,
        "policy_version": "v1",
        "source_versions": [source()],
        "valid": False,
        "blocking_issues": ["owner unassigned"],
        "warnings": ["future certification"],
    }
    PlanValidationResult.model_validate(plan)
    with pytest.raises(ValidationError, match="plan_validity_blockers_inconsistent"):
        PlanValidationResult.model_validate({**plan, "valid": True})
    result = {
        "candidate_digest": DIGEST,
        "input_digest": DIGEST,
        "algorithm_version": "v1",
        "source_versions": [source()],
        "completeness": "not_computable",
        "node_times": [],
        "critical_path": [],
        "conflicts": [],
        "missing": ["capacity"],
    }
    ScheduleEvaluationResult.model_validate(result)
    with pytest.raises(ValidationError, match="complete_scenario_has_missing_inputs_or_nodes"):
        ScheduleEvaluationResult.model_validate({**result, "completeness": "complete"})
    with pytest.raises(ValidationError, match="uncomputable_scenario_requires_missing_not_dates"):
        ScheduleEvaluationResult.model_validate(
            {**result, "node_times": [{"node_key": "ID", "forecast": {"start": NOW, "end": NOW}}]}
        )
