"""Offline prefix admission is an impossibility proof, never a model-quality result."""

import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def baseline():
    import sys

    tools = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(tools))
    return importlib.import_module("xiaopai_context_admission_baseline")


@pytest.fixture(scope="module")
def inputs(baseline):
    return (json.loads(baseline.QUESTIONS.read_text()),
            json.loads(baseline.EXPANDED.read_text()))


def test_inline_expansion_and_existing_long_input_measurements_match(baseline, inputs):
    questions, expanded = inputs
    before = deepcopy(inputs)
    observed = {case["id"]: baseline.raw_measurement(case, expanded[case["id"]])
                for case in questions["cases"]}
    assert len(observed) == 12
    assert observed["CTX-01"]["current_estimator_tokens"] == 33682
    assert observed["CTX-12"]["current_estimator_tokens"] == 29836
    assert all(row["expanded_input_matches"] for row in observed.values())
    for case in questions["cases"]:
        measurement = case.get("replay_input", {}).get("input_measurement", {})
        if "raw_estimate_exceeds_both_F" in measurement:
            raw = observed[case["id"]]["current_estimator_tokens"]
            assert measurement["raw_estimate_exceeds_both_F"] is all(
                raw > focus for focus in case["f_budget_tokens"])
    assert inputs == before


def test_tampered_materialization_fails_before_admission(baseline, inputs):
    questions, expanded = deepcopy(inputs)
    case = questions["cases"][0]
    case["replay_input"]["records"][0]["lines"][0] += "变化"
    with pytest.raises(ValueError, match="differs from expanded input"):
        baseline.raw_measurement(case, expanded[case["id"]])
    with pytest.raises(ValueError, match="recorded characters differs"):
        baseline.raw_measurement(case, baseline.materialize(case))


def test_probe_never_promotes_scenario_tool_or_hidden_history_to_input(baseline, inputs):
    questions, _ = inputs
    case = next(row for row in questions["cases"] if row["id"] == "CTX-08")
    messages = baseline.question_only_messages(case)
    assert len(messages) == 1 and messages[0]["role"] == "user"
    assert json.loads(messages[0]["content"]) == {"goal": case["final_prompt"], "context": {}}
    assert "SYNT-LANTERN-47" not in messages[0]["content"]
    assert "17套" not in messages[0]["content"]


def test_production_prefix_rejects_old_profiles_and_admits_large_lower_bounds(baseline, inputs):
    value = baseline.evaluate(*inputs)
    assert value["production_fixed_prefix"]["tool_count"] == 61
    assert value["provider_calls"] == value["database_operations"] == 0
    assert value["production_fixed_prefix"]["fixed_admission_tokens"] > 16384
    for case in value["cases"]:
        for focus in (8192, 16384):
            probe = case["profiles"][str(focus)]
            assert probe["status"] == "CONTEXT_INCOMPLETE"
            assert probe["reason_key"] == "fixed_context_exceeds_window"
            assert probe["context_budget"]["focus"] == focus
            assert probe["recovery"]["action"] == "configure_model_context_window"
        for focus in (48000, 64000):
            probe = case["profiles"][str(focus)]
            assert probe["status"] == "admitted_lower_bound_only"
            assert probe["context_budget"]["focus"] == focus
            assert not probe["context_budget"]["over_focus"]
        assert case["native_provider_input_status"] == "blocked_missing_native_fixture_bindings"
        assert case["native_replay_admission"] is case["task_score"] is None
        assert case["full_completion"] is None
        assert case["actual_input_tokens"] is case["actual_output_tokens"] is None
        assert case["model_quality"] == "not_run"
