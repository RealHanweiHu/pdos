"""Actual admission meter -> runtime event -> public metadata, zero provider/DB."""

import json
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from pdos_next.agent_kernel.context_budget import fit_messages
from pdos_next.agent_kernel.context_observability import record_incomplete
from pdos_next.agent_kernel.models import AgentEvent
from pdos_next.agent_kernel.process_view import public_context_metrics
from pdos_next.errors import DomainError
from tests.agent_kernel.test_gateway import configured_route
from tests.agent_kernel.test_graph import scope


class Store:
    def __init__(self):
        self.events = []
        self.run = NS(id=uuid4(), tenant_id=uuid4(), versions={})
        self.locks = []

    def scalar(self, statement):
        assert "max(agent_run_events.sequence)" in str(statement)
        return len(self.events)

    def add(self, event):
        assert isinstance(event, AgentEvent)
        self.events.append(event)

    @contextmanager
    def transaction(self, bound, *, lock=False):
        self.locks.append(lock)
        yield self, self.run


def admission(*, fixed=True):
    messages = [{"role": "user", "content": json.dumps({
        "goal": "PRIVATE original user words", "context": {"work_state": {
            "constraints": ["PRIVATE required constraint " * 3000] if not fixed else [],
        }},
    })}]
    with pytest.raises(DomainError) as caught:
        fit_messages(replace(configured_route(), context_window_tokens=8192),
                     "PRIVATE fixed system content " * 3000 if fixed else "short system",
                     [], messages, allow_envelope=True)
    return caught.value, messages


def test_real_blocked_fixed_budget_emits_exact_estimated_segments_true_warning_once_no_text():
    store, bound = Store(), scope()
    error, messages = admission(fixed=True)
    original = error.detail["context_budget"]
    record_incomplete(store, bound, error, messages)
    record_incomplete(store, bound, error, messages)
    assert len(store.events) == 1 and store.locks == [True, True]
    body = store.events[0].body
    assert body["estimated_input_tokens"] == original["estimated_total"]
    assert body["fixed_over_half"] is True
    assert set(body["warnings"]) == {"context_incomplete", "fixed_over_half_focus"}
    for key, estimated in original["segments"].items():
        assert body["segments"][key] == {"estimated_tokens": estimated, "actual_tokens": None}
    assert "PRIVATE" not in json.dumps(body)
    public = public_context_metrics(body, body["type"])
    assert public["fixed_over_half"] is True and public["actual_input_tokens"] is None
    assert public["segments"]["system"]["estimated_tokens"] == original["segments"]["system"]
    assert public["cache"] is None  # No provider call, cache actuals or model claim.


def test_actual_required_content_overflow_does_not_invent_fixed_content_alarm():
    store, bound = Store(), scope()
    error, messages = admission(fixed=False)
    assert error.detail["context_budget"]["fixed_over_half"] is False
    record_incomplete(store, bound, error, messages)
    body = store.events[0].body
    assert body["fixed_over_half"] is False and body["warnings"] == ["context_incomplete"]
    assert body["segments"]["envelope"]["estimated_tokens"] > 8192
    assert all(row["actual_tokens"] is None for row in body["segments"].values())


def test_missing_meter_fields_stay_unknown_with_no_guessed_segments_total_or_fixed_alarm():
    store, bound = Store(), scope()
    error = DomainError("CONTEXT_INCOMPLETE", "PRIVATE failure message", detail={
        "context_budget": {}, "missing": [{"field": "work_state.constraints"}],
    })
    record_incomplete(store, bound, error, [])
    body = store.events[0].body
    assert body["segments"] is None and body["estimated_input_tokens"] is None
    assert body["fixed_over_half"] is None and body["warnings"] == ["context_incomplete"]
    assert "PRIVATE" not in json.dumps(body)


def test_unregistered_segment_body_and_non_numeric_meter_values_are_not_telemetry():
    store, bound = Store(), scope()
    error = DomainError("CONTEXT_INCOMPLETE", "PRIVATE message", detail={"context_budget": {
        "segments": {"system": 12, "tools": "PRIVATE body", "PRIVATE segment": "PRIVATE"},
        "estimated_total": "PRIVATE", "fixed_over_half": "true", "raw_body": "PRIVATE",
    }})
    record_incomplete(store, bound, error, [])
    body = store.events[0].body
    assert body["segments"]["system"] == {"estimated_tokens": 12, "actual_tokens": None}
    assert body["segments"]["tools"]["estimated_tokens"] is None
    assert body["fixed_over_half"] is None and body["estimated_input_tokens"] is None
    assert body["warnings"] == ["context_incomplete"]
    assert "PRIVATE" not in json.dumps(body)
