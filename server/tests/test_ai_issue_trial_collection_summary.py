"""Registered Issue criteria stay descriptive, including perfect synthetic inputs."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.ai_issue_trial_collections import CollectIssueTrial, match_run, summarize

NOW = datetime(2026, 9, 27, tzinfo=UTC)


def protocol():
    return {
        "tenant_id": str(uuid4()),
        "project_id": str(uuid4()),
        "policy_id": str(uuid4()),
        "scope_revision_id": str(uuid4()),
        "principal_id": str(uuid4()),
        "binding": {"fixed": "test"},
        "created_at": (NOW - timedelta(days=2)).isoformat(),
        "window_end": (NOW - timedelta(hours=1)).isoformat(),
        "evidence_kind": "synthetic",
        "evaluation_publication": {
            "valid_from": (NOW - timedelta(days=3)).isoformat(),
            "valid_until": (NOW + timedelta(days=3)).isoformat(),
        },
        "configuration": {
            "minimum_handled_runs": 1,
            "minimum_followup_seconds": 3600,
            "minimum_confirmation_basis_points": 9000,
            "maximum_retraction_basis_points": 500,
            "confirmation_basis": "ever_confirmed",
        },
    }


def item(p):
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
        "source_digest": "a" * 64,
        "event_row_id": 42,
        "match": {"matches_protocol": True},
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


def test_perfect_descriptive_ratios_never_grant_provider_or_sampling():
    p = protocol()
    values = [item(p)]
    result = summarize(p, values, NOW)
    assert result["criteria"]["confirmation"]["basis_points"] == 10000
    assert result["criteria"]["withdrawal"]["basis_points"] == 0
    assert result["criteria"]["followup_complete"] is True
    assert result["qualification_granted"] is False
    assert {v["code"] for v in result["blockers"]} == {
        "provider_calls_unverified",
        "non_business_evidence",
    }
    assert {v["code"] for v in result["operational_requirements"]} == {
        "runtime_sampling_required"
    }
    assert result["formula"]["version"] == "event-issue-registered-observation-formula-v1"


def test_all_raw_runs_kept_and_other_run_application_not_adopted():
    p = protocol()
    created = item(p)
    same = item(p)
    failed = item(p)
    same.update(application_kind=None, same_source_applied=True)
    failed.update(
        status="failed",
        result_id=None,
        disposition=None,
        application_kind=None,
        binding_kind="not_recorded",
        match={"matches_protocol": False},
    )
    result = summarize(p, [created, same, failed], NOW)
    assert result["total_runs"] == 3 and result["matching_runs"] == 2
    assert result["counts"]["failed_runs"] == 1
    assert result["matching_counts"]["same_source_applied_runs"] == 1
    assert result["criteria"]["confirmation"]["denominator"] == 1


@pytest.mark.parametrize("basis,expected", [("ever_confirmed", 10000), ("retained_original", 0)])
def test_original_creation_edit_and_withdrawal_are_not_retained(basis, expected):
    p = protocol()
    p["configuration"]["confirmation_basis"] = basis
    edited, withdrawn = item(p), item(p)
    edited["human_edited"] = True
    withdrawn["withdrawn"] = True
    result = summarize(p, [edited, withdrawn], NOW)
    assert result["criteria"]["confirmation"]["basis_points"] == expected
    assert result["criteria"]["withdrawal"]["numerator"] == 1
    assert result["criteria"]["withdrawal"]["denominator"] == 2
    assert result["criteria"]["withdrawal"]["met"] is False


def test_reopen_removes_current_decline_but_keeps_source():
    p = protocol()
    v = item(p)
    v.update(application_kind=None, review_state="declined")
    assert summarize(p, [v], NOW)["criteria"]["confirmation"]["denominator"] == 1
    v["review_state"] = "reopened"
    after = summarize(p, [v], NOW)
    assert after["total_runs"] == 1
    assert after["criteria"]["confirmation"]["basis_points"] is None
    assert after["criteria"]["withdrawal"]["basis_points"] is None


def test_zero_followup_boundary_and_duplicate_originals():
    p = protocol()
    result = summarize(p, [], NOW - timedelta(microseconds=1))
    assert result["criteria"]["followup_complete"] is False
    assert result["criteria"]["confirmation"]["met"] is None
    v = item(p)
    with pytest.raises(ValueError):
        summarize(p, [v, deepcopy(v)], NOW)


def test_match_original_ids_runtime_and_validity():
    p = protocol()
    v = item(p)
    proof = {"provenance_verified": True, "provider_verified": False, "binding": p["binding"]}
    assert match_run(p, v, proof, NOW)["matches_protocol"] is True
    v["generation_binding"]["scope"]["id"] = str(uuid4())
    assert "generation_control_mismatch" in {
        r["code"] for r in match_run(p, v, proof, NOW)["reasons"]
    }
    v["binding_kind"] = "not_recorded"
    proof.update(provenance_verified=False, binding=None)
    codes = {r["code"] for r in match_run(p, v, proof, NOW)["reasons"]}
    assert {
        "generation_not_trial_candidate",
        "runtime_chain_unverified",
        "runtime_binding_mismatch",
    } <= codes


def test_real_business_label_and_expired_eval_do_not_backfill():
    p = protocol()
    v = item(p)
    p["evidence_kind"] = "real_business"
    p["created_at"] = NOW.isoformat()
    p["evaluation_publication"]["valid_until"] = (NOW - timedelta(days=1)).isoformat()
    proof = {"provenance_verified": True, "provider_verified": False, "binding": p["binding"]}
    assert {"run_precedes_registration", "evaluation_outside_validity"} <= {
        r["code"] for r in match_run(p, v, proof, NOW)["reasons"]
    }


@pytest.mark.parametrize(
    "extra",
    [
        {"as_of": NOW.isoformat()},
        {"qualification_granted": True},
        {"items": []},
        {"protocol_id": str(uuid4())},
    ],
)
def test_caller_cannot_supply_cutoff_or_originals(extra):
    with pytest.raises(ValidationError):
        CollectIssueTrial.model_validate({"request_id": str(uuid4()), **extra})


def test_large_followup_choice_stays_pending_without_datetime_overflow():
    p = protocol()
    p["configuration"]["minimum_followup_seconds"] = 10**30
    assert summarize(p, [], NOW)["criteria"]["followup_complete"] is False
