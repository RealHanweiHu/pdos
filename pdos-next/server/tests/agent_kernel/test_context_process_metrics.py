"""Actual public process projection with synthetic SQL ports, no database/model."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from pdos_next.agent_kernel import run_reconciliation
from pdos_next.agent_kernel.context_observability import call_metrics
from pdos_next.agent_kernel.process_view import (
    KINDS,
    METRIC_KEYS,
    public_context_metrics,
    read_process,
)
from pdos_next.errors import DomainError


def actual_metric():
    metrics = call_metrics(
        budget={"window": 32000, "window_configured": False, "reserve": 6000, "focus": 26000,
                "estimated_total": 16000, "admission_tokens": 18400, "fixed_over_half": True,
                "segments": {"system": 9000, "tools": 4000, "skills": 0, "envelope": 1000,
                             "history": 1000, "loop": 1000},
                "cleanup": {"applied": True, "saved_tokens": 6000,
                            "minimum_tokens": 5200, "reason": "minimum_reached"},
                "reductions": [{"kind": "older_tool_result", "field": "messages[2]",
                                "handle": "result:private-trace-only", "read_more": {
                                    "tool": "result.read", "arguments": {"handle": "private-trace"},
                                }}]},
        usage={"input_tokens": 20000, "output_tokens": 10, "cache_read_tokens": 5000},
        messages=[{"content": json.dumps({"context": {"work_state": {"revision": 7},
                       "conversation": {"turns": [
                           {"outcome_state": "hidden", "historical_outcome": None},
                       ]}}})}], cleanup_count=3, previous_error_streak=1,
    )
    return {"type": "context_observed", "isolation": "main", **metrics}


def test_actual_runtime_metrics_have_closed_public_projection_and_four_honest_warnings():
    raw = actual_metric()
    raw["warnings"].append("context_incomplete")
    projected = public_context_metrics(raw, "context_observed")
    assert projected["window"] == 32000 and projected["focus"] == 26000
    assert projected["segments"]["history"] == {"estimated_tokens": 1000, "actual_tokens": None}
    assert projected["actual_input_tokens"] == 20000 and projected["cache"]["read_tokens"] == 5000
    assert projected["cache"]["read_hit_ratio"] == .25
    assert projected["history"]["hidden"] == 1 and projected["work_state"]["revision"] == 7
    assert set(projected["warnings"]) == {"fixed_over_half_focus", "context_incomplete",
        "cleanup_more_than_twice", "persistent_estimation_error"}
    assert projected["reductions"] == [{"kind": "older_tool_result", "field": "messages[2]",
                                         "recoverable": True}]
    assert "private-trace" not in json.dumps(projected)


def test_nested_unknown_fields_raw_bodies_read_arguments_and_unknown_alarm_strings_do_not_escape():
    raw = actual_metric()
    raw.update(text="PRIVATE", body="PRIVATE", source_content="PRIVATE", charged_tokens=999999,
               provider_reasoning="PRIVATE", warnings=["context_incomplete", "PRIVATE"])
    for key in ["segments", "cache", "cleanup", "history", "work_state"]:
        raw[key]["private_body"] = "PRIVATE"
    raw["segments"]["loop"]["raw"] = "PRIVATE"
    raw["segments"]["unknown_section"] = {"actual_tokens": "PRIVATE"}
    raw["work_state"]["item_counts"]["user_text"] = "PRIVATE"
    raw["reductions"][0]["read_more"]["arguments"]["body"] = "PRIVATE"
    raw["reductions"].append({"kind": "PRIVATE", "field": "PRIVATE body text", "body": "PRIVATE"})
    raw["missing"] = [{"field": "work_state.constraints", "estimated_tokens": 12,
                       "quote": "PRIVATE"}, {"field": "PRIVATE body text"}]
    projected = public_context_metrics(raw, "context_observed")
    assert "PRIVATE" not in json.dumps(projected) and "charged_tokens" not in projected
    assert projected["warnings"] == ["context_incomplete"]
    assert projected["missing"][0] == {"field": "work_state.constraints", "estimated_tokens": 12}
    assert projected["missing"][1]["field"] is None


@pytest.mark.parametrize("value", [True, -1, "32000", float("nan"), float("inf"), 2**1024])
def test_non_numeric_non_finite_unsafe_and_coerced_values_stay_unknown(value):
    projected = public_context_metrics({"window": value, "actual_input_tokens": value,
        "estimation_error_ratio": value, "cache": {"read_hit_ratio": value}}, "context_observed")
    assert projected["window"] is None and projected["actual_input_tokens"] is None
    assert projected["estimation_error_ratio"] is None
    assert projected["cache"]["read_hit_ratio"] is None


def test_context_incomplete_has_no_fabricated_usage_and_bounds_only_metadata_display():
    raw = {"window": 32000, "reserve": 6000, "focus": 26000, "context_incomplete": True,
           "warnings": ["context_incomplete"],
           "missing": [{"field": "work_state.constraints", "estimated_tokens": 9000}] * 300,
           "reductions": [{"kind": "history_directory", "field": "conversation.turns[4]"}] * 110}
    projected = public_context_metrics(raw, "context_admission_observed")
    assert projected["context_incomplete"] and projected["actual_input_tokens"] is None
    assert projected["cache"] is None and projected["segments"] is None
    assert projected["missing_count"] == 300 and len(projected["missing"]) == 256
    assert projected["reductions_count"] == 110 and len(projected["reductions"]) == 100
    assert raw["missing"] == [{"field": "work_state.constraints", "estimated_tokens": 9000}] * 300
    assert public_context_metrics(raw, "text_delta") is None
    assert public_context_metrics(None, "context_observed") is None


class Session:
    def __init__(self, rows):
        self.rows, self.reads = rows, []
        self.executions = 0

    def execute(self, statement):
        self.reads.append(statement)
        self.executions += 1
        return NS(all=lambda: self.rows if self.executions == 1 else [])

    def scalar(self, statement):
        self.reads.append(statement)
        # Before cursor validation, then latest timestamp, are both actual reads.
        return datetime(2026, 10, 29, tzinfo=UTC)

    def add(self, row):
        raise AssertionError("Reading process must not write")


def event(sequence, kind="context_observed", metric=None):
    return NS(id=uuid4(), sequence=sequence, created_at=datetime(2026, 10, 29, tzinfo=UTC),
              kind=kind, tool=None, skill=None, version=None, status=None,
              context_fields=None, context_omitted=None, context_issues=None,
              context_metric_data=metric)


def run():
    return NS(id=uuid4(), tenant_id=uuid4(), state="running", reverted_at=None, error_code=None,
              created_at=datetime(2026, 10, 29, tzinfo=UTC), read_sources=[])


def test_actual_read_process_uses_same_bounded_event_page_and_explicit_sql_projection(monkeypatch):
    monkeypatch.setattr(run_reconciliation, "_receipts", lambda *_: [])
    first, extra = event(5, metric=actual_metric()), event(4, "model_started")
    session = Session([first, extra])
    result = read_process(session, run(), page_size=1)
    assert [row["sequence"] for row in result["steps"]] == [5]
    assert result["steps"][0]["context_metrics"]["actual_input_tokens"] == 20000
    assert result["next_before"] == 5 and result["sources"] == [] and result["receipts"] == []
    assert session.reads[0]._limit_clause.value == 2
    sql = str(session.reads[0].compile(dialect=postgresql.dialect(),
                                      compile_kwargs={"literal_binds": True}))
    assert "context_observed" in sql and "context_admission_observed" in sql
    assert "text_delta" not in sql and "jsonb_build_object" in sql
    assert "agent_run_events.body," not in sql
    assert "agent_tool_calls.result" not in sql and "agent_runs.versions" not in sql
    assert "FOR UPDATE" not in sql and " LIMIT 2" in sql
    assert set(METRIC_KEYS).isdisjoint({"text", "arguments", "result", "charged_tokens"})
    assert result["steps"][0]["context_metrics"]["context_incomplete"] is False


def test_metric_cursor_and_legacy_pages_remain_read_only_and_do_not_invent_metrics(monkeypatch):
    monkeypatch.setattr(run_reconciliation, "_receipts", lambda *_: [])
    session = Session([event(3, "tool_finished")])
    result = read_process(session, run(), before=5)
    assert "context_metrics" not in result["steps"][0]
    assert len(session.reads) == 4 and "context_observed" in KINDS
    bad = Session([])
    bad.scalar = lambda _: None
    with pytest.raises(DomainError) as caught:
        read_process(bad, run(), before=999)
    assert caught.value.code == "FORBIDDEN_SCOPE"
