"""Offline plan/authenticity checks only; no setup/DB/model fixture is requested."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "real_context_fixtures", ROOT / "pdos-next/tools/xiaopai_real_context_fixtures.py")
fixtures = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixtures)


def test_original_long_case_expansions_remain_frozen_and_are_not_flat_prompt_history():
    for identity in ("CTX-01", "CTX-12"):
        case = fixtures.cases()[identity]
        expanded = fixtures.materialized(case)  # Validates the frozen source SHA256.
        plan = fixtures.run_spec(identity, 48000)
        assert [row["goal"] for row in plan["steps"]] == [
            row["content"] for row in expanded if row["role"] == "user"]
        assert plan["steps"][-1]["goal"] == case["final_prompt"]
        assert plan["assistant_transcript_injected"] is False
        assert plan["scenario_tool_messages_injected"] is False
    assert len(fixtures.run_spec("CTX-01", 48000)["steps"]) == 31
    ctx12 = fixtures.run_spec("CTX-12", 64000)
    assert "S12-A v1附录01" not in json.dumps(ctx12, ensure_ascii=False)


def test_pair_changes_only_focus_and_window_with_no_invented_model_result():
    for identity in fixtures.cases():
        small = fixtures.run_spec(identity, 48000)
        large = fixtures.run_spec(identity, 64000)
        assert small["route_metadata"] == {
            "context_window_tokens": 54048, "max_output_tokens": 2048}
        assert large["route_metadata"] == {
            "context_window_tokens": 70048, "max_output_tokens": 2048}
        for key in ("f_budget_tokens", "route_metadata"):
            small.pop(key)
            large.pop(key)
        assert small == large
        assert small["actual_model_calls"] == 0 and small["model_quality_score"] is None


def test_ctx09_partial_cannot_turn_into_an_exact_page_failure_plan():
    plan = fixtures.run_spec("CTX-09", 48000)
    assert plan["binding_status"] == "partial"
    assert plan["execution_class"] == "unbound_scenario_control"
    encoded = json.dumps(plan)
    assert "result:00000000" not in encoded and "SOURCE_UNAVAILABLE" not in encoded
    assert not any(step["before"] or step["after"] for step in plan["steps"])
    assert fixtures.run_spec("CTX-10", 48000)["execution_class"] == "control_only"


def test_candidate_payload_requires_actual_citation_and_continues_actual_run():
    plan = fixtures.run_spec("CTX-11", 64000)
    plan["bindings"] = {"project_id": "actual-project", "product_id": "actual-product",
                        "source": {"artifact_id": "actual-source", "expected_revision": 1}}
    with pytest.raises(fixtures.FixtureBlocked, match="actual preceding verified citations"):
        fixtures.run_payload(plan, 1, {"run_id": "actual-run", "output": {}})
    previous = {"run_id": "actual-run", "output": {
        "result": {"assistant": {"citation_ids": ["actual-issued-citation"]}}}}
    payload = fixtures.run_payload(plan, 1, previous)
    assert payload["continue_from_run_id"] == "actual-run"
    assert payload["work_followup_action"] == {
        "project_id": "actual-project", "citation_ids": ["actual-issued-citation"],
        "assignment": None}
    assert "assignee_id" not in json.dumps(payload) and "due_at" not in json.dumps(payload)


def test_ctx12_uses_category_reads_without_eight_pins_and_deep_final():
    plan = fixtures.run_spec("CTX-12", 64000)
    payload = fixtures.run_payload(plan, 0)
    assert "sources" not in payload and "lookup_depth" not in payload
    final = fixtures.run_payload(plan, len(plan["steps"]) - 1, {"run_id": "actual-run"})
    assert final["lookup_depth"] == "deep" and "sources" not in final


@pytest.mark.parametrize("explicit,actual", [
    (None, "postgresql://app:private@localhost:53502/pdos_test"),
    ("postgresql://admin:private@localhost:53502/production",
     "postgresql://app:private@localhost:53502/production"),
    ("postgresql://admin:private@localhost:53502/pdos_test",
     "postgresql://app:private@localhost:53503/pdos_test"),
    ("postgresql://admin:private@remote.example:53502/pdos_test",
     "postgresql://app:private@remote.example:53502/pdos_test"),
])
def test_native_setup_guard_rejects_missing_or_unmatched_target_without_connection(
    monkeypatch, explicit, actual,
):
    if explicit is None:
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("TEST_DATABASE_URL", explicit)
    setup = SimpleNamespace(engine=SimpleNamespace(url=SimpleNamespace(
        render_as_string=lambda **_: actual)))
    with pytest.raises(fixtures.FixtureBlocked) as error:
        fixtures.require_isolated_target(setup)
    assert "private" not in str(error.value)


def test_guard_allows_role_credentials_for_same_explicit_local_target(monkeypatch):
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+psycopg://admin:p@localhost:53502/pdos_test")
    setup = SimpleNamespace(engine=SimpleNamespace(url=SimpleNamespace(
        render_as_string=lambda **_: "postgresql+psycopg://app:q@localhost:53502/pdos_test")))
    fixtures.require_isolated_target(setup)
