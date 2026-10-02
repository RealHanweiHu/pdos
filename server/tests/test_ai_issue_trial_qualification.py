"""Pure invented trusted facts only; never a real provider attestation or grant."""

import socket
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.domain.ai_issue_trial_qualification import EVALUATOR_VERSION, evaluate
from app.domain.product_workspace import digest

NOW = datetime(2026, 9, 27, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Pure qualification must not access DB, provider or network")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def protocol() -> dict[str, Any]:
    binding = {
        "operation_key": "event.issue.create",
        "provider": "openai",
        "model": "fixture-model",
        "model_version": "fixture-version",
        "release_bundle_version": "sha256:" + "a" * 64,
        "suite_version": "fixture-gateway-v1",
        "suite_digest": "b" * 64,
        "adapter_version": "fixture-reader-v1",
        "policy_version": "fixture-policy-v1",
        "policy_revision": 1,
    }
    return {
        "version": "event-issue-trial-protocol-v1",
        "id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "project_id": str(uuid4()),
        "policy_id": str(uuid4()),
        "scope_revision_id": str(uuid4()),
        "principal_id": str(uuid4()),
        "binding": binding,
        "created_at": (NOW - timedelta(days=3)).isoformat(),
        "window_start": (NOW - timedelta(days=2)).isoformat(),
        "window_end": (NOW - timedelta(hours=1)).isoformat(),
        "evidence_kind": "real_business",
        "evaluation_publication": {
            "valid_from": (NOW - timedelta(days=4)).isoformat(),
            "valid_until": (NOW + timedelta(days=1)).isoformat(),
            "evaluation": {
                "binding": deepcopy(binding),
                "execution_source": "live_model_evaluation",
                "real_provider_call": True,
                "outcome": "passed",
            },
        },
        "configuration": {
            "minimum_handled_runs": 1,
            "minimum_followup_seconds": 3600,
            "minimum_confirmation_basis_points": 9000,
            "maximum_retraction_basis_points": 500,
            "confirmation_basis": "ever_confirmed",
            "sampling_basis_points": 100,
            "recovery_protocol_version": "fixture-recovery-v1",
            "recovery_conditions": "模拟恢复",
        },
    }


def item(p: dict[str, Any]) -> dict[str, Any]:
    value = {
        "run_id": str(uuid4()),
        "created_at": (NOW - timedelta(hours=2)).isoformat(),
        "status": "succeeded",
        "result_id": str(uuid4()),
        "disposition": "create_issue",
        "binding_kind": "trial_candidate",
        "review_state": "unreviewed",
        "application_kind": "created",
        "same_source_applied": False,
        "withdrawn": False,
        "human_edited": False,
        "source_digest": "c" * 64,
        "event_row_id": 42,
        "match": {"matches_protocol": True},
        "provenance": {
            "provenance_verified": True,
            "provider_verified": True,
            "binding": deepcopy(p["binding"]),
        },
    }
    value["generation_binding"] = {
        "tenant_id": p["tenant_id"],
        "project_id": p["project_id"],
        "run_id": value["run_id"],
        "source_digest": value["source_digest"],
        "event_row_id": 42,
        "policy": {"id": p["policy_id"]},
        "scope": {"id": p["scope_revision_id"]},
        "principal": {"id": p["principal_id"]},
    }
    return value


def collection(p: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": "event-issue-trial-collection-v1",
        "id": str(uuid4()),
        "tenant_id": p["tenant_id"],
        "project_id": p["project_id"],
        "protocol_id": p["id"],
        "protocol_digest": digest(p),
        "window_start": p["window_start"],
        "window_end": p["window_end"],
        "as_of": NOW.isoformat(),
        "created_at": NOW.isoformat(),
        "items": items,
        "total_runs": len(items),
        "selection_complete": True,
        # These historic conclusions must be recomputed, never adopted as authority.
        "counts": {"total_runs": 999},
        "matching_runs": 999,
        "criteria": {"invented_pass": True},
        "blockers": [{"code": "sampling_evidence_missing"}, {"code": "unmatched_runs"}],
        "qualification_granted": False,
    }


def codes(result: dict[str, Any]) -> set[str]:
    return {v["code"] for v in result["reasons"]}


def test_recomputes_without_mutation_or_historic_sampling_veto() -> None:
    p = protocol()
    c = collection(p, [item(p)])
    before = deepcopy((p, c))
    result = evaluate(p, c)
    assert result["status"] == "meets_candidate_criteria"
    assert result["evaluator_version"] == EVALUATOR_VERSION
    assert result["counts"]["total_runs"] == 1 and result["matching_runs"] == 1
    assert result["criteria"]["confirmation"]["basis_points"] == 10000
    assert result["qualification_granted"] is False
    assert result["reasons"] == []
    assert result["operational_requirements"][0]["code"] == "t0_continuous_sampling"
    assert result["operational_requirements"][0]["sampling_basis_points"] == 100
    assert (p, c) == before
    c.pop("version")
    c.pop("created_at")
    c.pop("id")
    assert evaluate(p, c) == result  # The read-only fresh collection shape.


@pytest.mark.parametrize("status", ["failed", "degraded", "running"])
def test_no_all_success_or_all_handled_gate(status: str) -> None:
    p = protocol()
    bad = item(p)
    bad.update(
        status=status,
        result_id=None,
        disposition=None,
        application_kind=None,
        binding_kind="not_recorded",
        generation_binding=None,
        provenance={},
    )
    pending = item(p)
    pending.update(application_kind=None, provenance={})
    result = evaluate(p, collection(p, [item(p), bad, pending]))
    assert result["status"] == "meets_candidate_criteria"
    assert result["total_runs"] == 3 and result["matching_runs"] == 1
    assert result["criteria"]["confirmation"]["denominator"] == 1
    assert result["counts"]["failed_runs"] == (0 if status == "running" else 1)
    assert result["counts"]["pending_runs"] == (1 if status == "running" else 0)


@pytest.mark.parametrize("declined", [False, True])
def test_counted_handled_original_requires_trusted_provider(declined: bool) -> None:
    p = protocol()
    value = item(p)
    value["provenance"]["provider_verified"] = False
    if declined:
        value.update(application_kind=None, review_state="declined")
    result = evaluate(p, collection(p, [item(p), value]))
    assert result["status"] == "insufficient_evidence"
    assert "provider_calls_unverified" in codes(result)
    assert result["provider_unverified_handled_run_ids"] == [value["run_id"]]
    assert result["criteria"]["confirmation"]["denominator"] == 2


@pytest.mark.parametrize("declined", [False, True])
def test_unknown_handled_target_cannot_be_excluded_to_improve_ratio(declined: bool) -> None:
    p = protocol()
    value = item(p)
    value["provenance"] = {
        "provenance_verified": False,
        "provider_verified": False,
        "binding": None,
    }
    if declined:
        value.update(application_kind=None, review_state="declined")
    result = evaluate(p, collection(p, [item(p), value]))
    assert result["criteria"]["confirmation"]["basis_points"] == 10000
    assert result["status"] == "insufficient_evidence"
    assert "handled_target_unverified" in codes(result)
    assert result["uncertain_handled_run_ids"] == [value["run_id"]]


@pytest.mark.parametrize("difference", ["policy", "scope", "binding"])
def test_explicit_different_version_stays_raw_without_entering_target_denominator(
    difference: str,
) -> None:
    p = protocol()
    other = item(p)
    other.update(application_kind=None, review_state="declined")
    if difference == "binding":
        other["provenance"]["binding"]["model_version"] = "another-version"
    else:
        other["generation_binding"][difference]["id"] = str(uuid4())
        other["provenance"] = {}
    result = evaluate(p, collection(p, [item(p), other]))
    assert result["status"] == "meets_candidate_criteria"
    assert result["counts"]["declined_runs"] == 1
    assert result["matching_counts"]["declined_runs"] == 0
    assert result["total_runs"] == 2 and result["matching_runs"] == 1


@pytest.mark.parametrize("complete", [False, True])
def test_missing_generation_requires_complete_verified_other_binding_to_exclude(
    complete: bool,
) -> None:
    p = protocol()
    other = item(p)
    other.update(application_kind=None, review_state="declined", generation_binding=None)
    if complete:
        other["provenance"]["binding"]["model_version"] = "another-version"
    else:
        other["provenance"]["binding"] = {"model_version": "another-version"}
    result = evaluate(p, collection(p, [item(p), other]))
    assert result["total_runs"] == 2 and result["matching_runs"] == 1
    assert result["status"] == ("meets_candidate_criteria" if complete else "insufficient_evidence")
    assert ("handled_target_unverified" in codes(result)) is (not complete)


def test_current_decline_and_same_source_reuse_use_existing_run_denominator() -> None:
    p = protocol()
    declined, other_run = item(p), item(p)
    declined.update(application_kind=None, review_state="declined")
    other_run.update(application_kind=None, same_source_applied=True)
    result = evaluate(p, collection(p, [item(p), declined, other_run]))
    assert result["criteria"]["confirmation"]["denominator"] == 2
    assert result["criteria"]["confirmation"]["numerator"] == 1
    assert result["status"] == "does_not_meet_criteria"
    assert codes(result) == {"confirmation_not_met"}


@pytest.mark.parametrize(
    "basis,expected",
    [
        ("ever_confirmed", "meets_candidate_criteria"),
        ("retained_original", "does_not_meet_criteria"),
    ],
)
def test_confirmation_choice_uses_actual_edits(basis: str, expected: str) -> None:
    p = protocol()
    p["configuration"]["confirmation_basis"] = basis
    value = item(p)
    value["human_edited"] = True
    result = evaluate(p, collection(p, [value]))
    assert result["status"] == expected


@pytest.mark.parametrize(
    "count,expected", [(20, "meets_candidate_criteria"), (19, "does_not_meet_criteria")]
)
def test_withdrawal_boundary_uses_created_denominator(count: int, expected: str) -> None:
    p = protocol()
    values = [item(p) for _ in range(count)]
    values[0]["withdrawn"] = True
    result = evaluate(p, collection(p, values))
    assert result["criteria"]["withdrawal"]["numerator"] == 1
    assert result["criteria"]["withdrawal"]["denominator"] == count
    assert result["status"] == expected


def test_confirmation_threshold_uses_cross_multiplication() -> None:
    p = protocol()
    values = [item(p) for _ in range(10)]
    values[-1].update(application_kind=None, review_state="declined")
    assert evaluate(p, collection(p, values))["status"] == "meets_candidate_criteria"
    p["configuration"]["minimum_confirmation_basis_points"] = 9001
    result = evaluate(p, collection(p, values))
    assert result["status"] == "does_not_meet_criteria"
    assert result["criteria"]["confirmation"]["basis_points"] == 9000


@pytest.mark.parametrize(
    "condition,reason",
    [
        ("followup", "followup_incomplete"),
        ("minimum", "insufficient_handled_runs"),
        ("synthetic", "non_business_evidence"),
        ("incomplete", "selection_incomplete"),
    ],
)
def test_existing_registered_conditions_remain_requirements(condition: str, reason: str) -> None:
    p = protocol()
    if condition == "followup":
        p["configuration"]["minimum_followup_seconds"] = 3601
    elif condition == "minimum":
        p["configuration"]["minimum_handled_runs"] = 2
    elif condition == "synthetic":
        p["evidence_kind"] = "synthetic"
    c = collection(p, [item(p)])
    if condition == "incomplete":
        c["selection_complete"] = False
    result = evaluate(p, c)
    assert result["status"] == "insufficient_evidence"
    assert reason in codes(result)


def test_independent_evaluation_failure_is_not_ignored() -> None:
    p = protocol()
    p["evaluation_publication"]["evaluation"]["outcome"] = "failed"
    result = evaluate(p, collection(p, [item(p)]))
    assert result["status"] == "does_not_meet_criteria"
    assert codes(result) == {"evaluation_failed"}


def test_empty_cohort_and_duplicate_run_do_not_generate_a_pass() -> None:
    p = protocol()
    result = evaluate(p, collection(p, []))
    assert result["status"] == "insufficient_evidence"
    assert result["criteria"]["confirmation"]["basis_points"] is None
    value = item(p)
    with pytest.raises(ValueError):
        evaluate(p, collection(p, [value, deepcopy(value)]))


@pytest.mark.parametrize(
    "change",
    [
        {"protocol_id": str(uuid4())},
        {"protocol_digest": "0" * 64},
        {"total_runs": 2},
        {"version": "future-version"},
        {"as_of": (NOW - timedelta(days=2)).isoformat()},
    ],
)
def test_malformed_originals_raise_instead_of_silently_changing_scope(
    change: dict[str, Any],
) -> None:
    p = protocol()
    c = collection(p, [item(p)])
    c.update(change)
    with pytest.raises(ValueError):
        evaluate(p, c)
