"""Real-metric accounting invariants, without databases or model calls."""

import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest


@pytest.fixture
def metrics(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    return importlib.import_module("xiaopai_real_eval_metrics")


def call(identity="m1", **changes):
    value = {"id": identity, "run_id": "r1", "tool": "model", "state": "completed",
             "created_at": "2026-11-01T10:00:00+00:00", "cost_state": "actual",
             "cost_charged_micro_usd": 10, "cost_reserved_micro_usd": 99,
             "cost_pricing": {"currency": "USD", "digest": "price-a",
                              "configuration_version": "test-v1"},
             "execution_binding": {"isolation": "main", "model_route_digest": "route-a"},
             "result": {"usage": {"input_tokens": 100, "output_tokens": 20,
                                  "cache_read_tokens": 50, "cache_creation_tokens": 10}}}
    value.update(changes)
    return value


def export(*calls, runs=None, **changes):
    return {"version": "xiaopai-real-eval-export/v1",
            "runs": runs or [{"id": "r1", "case_id": "CTX-01", "suite": "context12",
                              "elapsed_ms": 1000, "first_visible_ms": 250}],
            "tool_calls": list(calls), **changes}


def test_inclusive_input_cost_is_not_added_to_cache_or_counted_twice(metrics):
    document = export(call(), call("count", tool="model.context.count", cost_state="unmetered"))
    original = deepcopy(document)
    result = metrics.summarize(document)
    assert result["summary"]["model_calls"] == 1
    assert result["summary"]["tokens"]["input_tokens"]["known_sum"] == 100
    assert result["summary"]["tokens"]["cache_read_tokens"]["known_sum"] == 50
    cost = result["summary"]["cost_buckets"][0]
    assert cost["actual_ledger_micro_usd"]["known_sum"] == 10
    assert cost["reserved_micro_usd"]["known_sum"] is None
    assert document == original
    json.dumps(result, allow_nan=False)


def test_unknown_default_token_columns_and_costs_do_not_become_provider_actuals(metrics):
    result = metrics.summarize(export(call(
        state="unknown", cost_state="estimated_unknown", cost_charged_micro_usd=99,
        actual_input_tokens=0, actual_output_tokens=0, result=None,
    )))
    for field in metrics.TOKEN_FIELDS:
        assert result["summary"]["tokens"][field] == {
            "known_sum": None, "known_count": 0, "unknown_count": 1, "complete": False,
        }
    assert result["model_calls"][0]["usage"]["cache_read_hit"] is None
    bucket = result["summary"]["cost_buckets"][0]
    assert bucket["actual_ledger_micro_usd"]["known_sum"] is None
    assert bucket["estimated_unknown_micro_usd"]["known_sum"] == 99


def test_normalized_zero_cache_is_ambiguous_but_explicit_raw_zero_is_known(metrics):
    normalized = {"input_tokens": 100, "output_tokens": 20,
                  "cache_read_tokens": 0, "cache_creation_tokens": 0}
    ambiguous = call(result={"usage": normalized})
    explicit = call("m2", result={"usage": normalized}, protocol="openai-compatible",
                    raw_usage={"prompt_tokens": 100, "completion_tokens": 20,
                               "prompt_tokens_details": {"cached_tokens": 0}})
    result = metrics.summarize(export(ambiguous, explicit))
    assert result["summary"]["provider_cache_read"]["positive_calls"] == 0
    assert result["summary"]["provider_cache_read"]["explicit_zero_calls"] == 1
    assert result["summary"]["provider_cache_read"]["unknown_calls"] == 1
    assert result["summary"]["tokens"]["cache_creation_tokens"]["known_sum"] is None


def test_anthropic_inclusive_input_and_conflicting_measurements(metrics):
    row = call(protocol="anthropic-native", raw_usage={
        "input_tokens": 40, "output_tokens": 20,
        "cache_read_input_tokens": 50, "cache_creation_input_tokens": 10,
    })
    result = metrics.summarize(export(row))
    assert result["model_calls"][0]["usage"]["input_tokens"] == 100
    row["raw_usage"]["input_tokens"] = 41
    with pytest.raises(ValueError, match="disagree"):
        metrics.summarize(export(row))


def test_mixed_route_isolation_price_currency_buckets_and_round_order(metrics):
    second = call("m2", created_at="2026-11-01T10:00:01+00:00", elapsed_ms=700)
    sub = call("m3", execution_binding={"isolation": "assistant_extract",
                                       "model_route_digest": "route-b"},
               cost_pricing={"currency": "CNY", "digest": "price-b",
                             "configuration_version": "test-v2"})
    result = metrics.summarize(export(second, sub, call(elapsed_ms=300)))
    assert len(result["summary"]["cost_buckets"]) == 2
    rows = {row["id"]: row for row in result["model_calls"]}
    assert rows["m1"]["model_round"] == rows["m3"]["model_round"] == "first"
    assert rows["m2"]["model_round"] == "subsequent"
    assert result["summary"]["model_call_elapsed_ms"] == {
        "n": 2, "p50": 300, "p95": 700, "min": 300, "max": 700, "unknown_count": 1,
    }
    assert result["summary"]["run_elapsed_ms"]["n"] == 1


def test_failed_usage_from_native_context_and_no_failed_cache_fabrication(metrics):
    result = metrics.summarize(export(call(state="failed", result=None), events=[{
        "run_id": "r1", "body": {"type": "context_observed", "model_call_id": "m1",
                                   "usage_status": "recorded", "actual_input_tokens": 80,
                                   "actual_output_tokens": 5, "cache": {"read_tokens": None}},
    }]))
    row = result["model_calls"][0]
    assert row["usage"]["input_tokens"] == 80
    assert row["usage"]["cache_read_tokens"] is None


def test_quality_compares_typed_observations_and_keeps_semantics_pending(metrics):
    runs = [{"id": "r1", "case_id": "CTX-01", "mechanical_checks": [
        {"id": "F1", "kind": "fact_value", "expected": 70, "observed": 70,
         "observation_basis": "reviewed_extraction", "evidence": ["answer.json#/facts/F1"]},
        {"id": "typed", "kind": "action", "expected": 0, "observed": False,
         "observation_basis": "native_ledger", "evidence": ["ledger.json#/receipts"]},
        {"id": "unread", "kind": "source_binding", "expected": "v2"},
        {"id": "revision", "kind": "identifier", "status": "needs_case_revision"},
    ]}]
    quality = metrics.summarize(export(runs=runs))["runs"][0]["quality"]
    assert quality["mechanical_statuses"] == {
        "passed": 1, "failed": 1, "not_run": 1, "needs_case_revision": 1,
    }
    assert quality["semantic_status"] == "pending_independent_review"


def test_missing_empty_control_run_never_appears_as_zero_cost_or_model_answer(metrics):
    result = metrics.summarize(export(runs=[{
        "id": "r1", "case_id": "CTX-10", "state": "failed", "error_code": "CONTEXT_INCOMPLETE",
    }]))
    assert result["summary"]["model_calls"] == 0
    assert result["summary"]["run_elapsed_ms"]["p95"] is None
    assert result["runs"][0]["metrics"]["cost_buckets"] == []


@pytest.mark.parametrize("field,value", [("elapsed_ms", -1), ("elapsed_ms", True),
                                         ("elapsed_ms", float("nan"))])
def test_invalid_latency_cannot_pollute_percentiles(metrics, field, value):
    with pytest.raises(ValueError):
        metrics.summarize(export(call(**{field: value})))


def test_duplicate_and_orphan_ledger_rows_are_rejected(metrics):
    with pytest.raises(ValueError, match="Duplicate ledger"):
        metrics.summarize(export(call(), call()))
    with pytest.raises(ValueError, match="exported run"):
        metrics.summarize(export(call(run_id="other")))


def test_case_manifest_preserves_missing_case_coverage_and_ambiguous_rounds(metrics):
    result = metrics.summarize(export(call("m1"), call("m2"), cases=[
        {"case_id": "CTX-01"}, {"case_id": "CTX-10"},
    ]))
    assert result["summary"]["expected_cases"] == 2
    assert result["summary"]["cases_without_run"] == ["CTX-10"]
    assert all(row["model_round"] == "unknown" for row in result["model_calls"])
    assert len(result["strata"]) == 1


def test_context_estimates_never_become_per_segment_actuals_or_leak_content(metrics):
    row = call(result={"usage": {"input_tokens": 100, "output_tokens": 20},
                       "context_budget": {"window": 70048, "reserve": 6048, "focus": 64000,
                                          "estimated_total": 90, "segments": {"tools": 50},
                                          "secret": "private-context"}})
    result = metrics.summarize(export(row))
    context = result["model_calls"][0]["context"]
    assert context["segments"]["tools"] == {"estimated_tokens": 50, "actual_tokens": None}
    assert context["estimated_input_tokens"] == 90
    assert "private-context" not in json.dumps(result)


def test_semantic_reviews_require_accountability_and_never_confer_qualification(metrics):
    runs = [{"id": "r1", "case_id": "CTX-01", "review": {
        "reviewer": "reviewer-a", "method": "agent_review", "status": "reviewed",
        "evidence": ["review.md#CTX-01"], "task_score": 2, "hard_fail": True,
    }}]
    result = metrics.summarize(export(runs=runs))
    assert result["runs"][0]["quality"]["semantic_review"]["task_score"] == 0
    runs[0]["review"]["method"] = "uncalibrated_llm_judge"
    with pytest.raises(ValueError, match="human or agent reviews"):
        metrics.summarize(export(runs=runs))


def test_cli_records_input_hash_without_overwriting_previous_evidence(metrics, tmp_path):
    source = tmp_path / "export.json"
    output = tmp_path / "metrics.json"
    source.write_text(json.dumps(export(call())))
    metrics.main(["--input", str(source), "--output", str(output)])
    result = json.loads(output.read_text())
    assert len(result["input_sha256"]) == 64
    with pytest.raises(FileExistsError):
        metrics.main(["--input", str(source), "--output", str(output)])
