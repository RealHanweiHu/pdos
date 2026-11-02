"""Evidence aggregation must not turn partial fixtures into quality passes."""

import json

import pytest
from xiaopai_context_native_baseline import UNSCORED, summarize


def record(folder, *, focus=48_000, **changes):
    value = {
        "version": "context-native-observation/v1", "case_id": "CTX-09",
        "f_budget_tokens": focus, "native_binding_status": "partial",
        "status": "native_mechanics_passed_scenario_item_alignment_unbound",
        "scripted_provider": True, "real_model_calls": 0, "provider_dispatches": 3,
        "context_budget": [], "bindings": {"page_unit": "json_fragment"},
        "model_quality_score": None, "not_scored": sorted(UNSCORED), **changes,
    }
    (folder / f"CTX-09-F{focus}.json").write_text(json.dumps(value))


def questions():
    return {"cases": [{"id": "CTX-09", "f_budget_tokens": [48_000, 64_000]}]}


def test_complete_capture_of_both_profiles_still_leaves_partial_scenario_unbound(tmp_path):
    record(tmp_path)
    record(tmp_path, focus=64_000)
    value = summarize(tmp_path, questions())
    assert value["recorded_observations"] == 2 and value["missing"] == []
    assert value["binding_counts"] == {"partial": 2}
    assert value["all_cases_natively_bound"] is False
    assert value["quality_status"] == "not_scored"


def test_successful_small_profile_does_not_stand_in_for_missing_large_profile(tmp_path):
    record(tmp_path, native_binding_status="bound")
    value = summarize(tmp_path, questions())
    assert value["missing"] == [{"case_id": "CTX-09", "f_budget_tokens": 64_000}]
    assert value["all_cases_natively_bound"] is False


@pytest.mark.parametrize("changes", [{"model_quality_score": 2}, {"real_model_calls": 1}])
def test_model_quality_or_real_call_claim_cannot_enter_scripted_baseline(tmp_path, changes):
    record(tmp_path, **changes)
    with pytest.raises(ValueError, match="model-quality"):
        summarize(tmp_path, questions())
