"""Ledger-derived metrics with synthetic storage ports; no DB or provider calls."""

import json
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from pdos_next.agent_kernel.bindings import ModelBinding
from pdos_next.agent_kernel.context_observability import (
    RUNTIME_KEY,
    call_metrics,
    carried_counts,
    record_call,
    record_incomplete,
)
from pdos_next.agent_kernel.models import AgentEvent, AgentToolCall
from pdos_next.agent_kernel.types import ModelTurn
from pdos_next.errors import DomainError
from pdos_next.providers.types import ProviderUsage
from tests.agent_kernel.test_graph import scope


def messages():
    return [{"role": "user", "content": json.dumps({"goal": "PRIVATE original goal", "context": {
        "work_state": {"revision": 7, "constraints": [{"text": "PRIVATE constraint"}],
                       "exclusions": [], "citations": [{"citation_id": "PRIVATE ID"}]},
        "conversation": {"turns": [
            {"outcome_state": "current", "goal": "PRIVATE historical goal",
             "historical_outcome": {"summary": "PRIVATE outcome"}},
            {"outcome_state": "updated", "historical_outcome": {"truncated": True}},
            {"outcome_state": "hidden", "historical_outcome": None},
        ]},
    }})}]


def budget(*, cleanup=False, estimated=100):
    return {"window": 32000, "window_configured": False, "reserve": 6000, "focus": 26000,
            "segments": {"system": 40, "tools": 20, "skills": 5, "envelope": 15,
                         "history": 10, "loop": 10},
            "estimated_total": estimated, "admission_tokens": 115, "fixed_over_half": True,
            "calibration_factor": 1.15, "estimation_basis": "first_call_estimate",
            "cleanup": {"applied": cleanup, "saved_tokens": 6000 if cleanup else 0},
            "reductions": [{"kind": "older_tool_result", "handle": "controlled"}]
            if cleanup else []}


class Session:
    def __init__(self):
        self.rows, self.events = {}, []

    def get(self, kind, identity):
        return self.rows.get((kind, identity))

    def scalar(self, statement):
        # Only max AgentEvent.sequence is issued by the production helper.
        assert "max(agent_run_events.sequence)" in str(statement)
        return len(self.events)

    def add(self, row):
        assert isinstance(row, AgentEvent)
        self.events.append(row)


class Store:
    def __init__(self, bound):
        self.run = NS(id=bound.run_id, tenant_id=bound.tenant_id, versions={},
                      token_limit=500, used_tokens=200, held_tokens=50)
        self.session, self.locks = Session(), []
        self.revoked = False

    @contextmanager
    def transaction(self, bound, *, lock=False):
        if self.revoked:
            raise DomainError("FORBIDDEN_SCOPE", "Synthetic current authority withdrawn")
        self.locks.append(lock)
        yield self.session, self.run


def completed(store, bound, *, cleanup=False, estimated=100, usage=None):
    row = AgentToolCall(
        id=uuid4(), tenant_id=bound.tenant_id, run_id=bound.run_id, tool="model", state="completed",
        error_code=None, result={"context_budget": budget(cleanup=cleanup, estimated=estimated),
                                 "usage": asdict(usage or ProviderUsage(200, 20, 80, 20))},
        execution_binding=ModelBinding(
            model_version="synthetic", model_route_digest="a" * 64,
            tool_definitions_digest="b" * 64, prompt_digest="c" * 64,
            isolation=bound.isolation, cancel_epoch=bound.cancel_epoch,
        ).model_dump(mode="json"),
    )
    store.session.rows[AgentToolCall, row.id] = row
    return row


def test_metrics_report_actual_cache_breakdown_without_double_counting_or_invented_segments():
    metrics = call_metrics(budget=budget(), usage=asdict(ProviderUsage(200, 20, 80, 20)),
                           messages=messages())
    assert (metrics["window"], metrics["reserve"], metrics["focus"]) == (32000, 6000, 26000)
    assert metrics["actual_input_tokens"] == 200 and metrics["actual_output_tokens"] == 20
    assert metrics["cache"] == {"read_tokens": 80, "creation_tokens": 20,
                                "read_hit_ratio": .4, "input_includes_cache": True,
                                "reporting": "positive_usage_reported"}
    assert metrics["segments"]["tools"] == {"estimated_tokens": 20, "actual_tokens": None}
    assert metrics["actual_segment_tokens"] == "provider_not_reported"
    assert metrics["history"] == {"carried": 3, "kept": 2, "updated": 1, "hidden": 1,
                                  "directories": 0, "truncated": 1, "unclassified": 0}
    assert metrics["work_state"]["revision"] == 7
    assert metrics["work_state"]["item_counts"]["constraints"] == 1
    assert "PRIVATE" not in json.dumps(metrics)


def test_no_usage_keeps_cache_rate_unknown_and_no_error_streak():
    metrics = call_metrics(budget=budget(), usage={}, messages=[], previous_error_streak=3)
    assert metrics["cache"]["read_hit_ratio"] is None
    assert metrics["estimation_error_ratio"] is None and metrics["estimation_error_streak"] == 0
    assert carried_counts([])["history"]["carried"] == 0


def test_actual_ledger_usage_is_authority_not_provider_turn_and_replay_is_exactly_once():
    bound = scope()
    store = Store(bound)
    row = completed(store, bound, cleanup=True)
    original = deepcopy(row.result)
    turn = ModelTurn(ledger_call_id=row.id, usage=ProviderUsage(999, 888))
    first = record_call(store, bound, turn, messages())
    second = record_call(store, bound, turn, messages())
    assert first == second and first["actual_input_tokens"] == 200
    assert store.run.versions[RUNTIME_KEY]["cleanup_count"] == 1
    assert first["run_budget"] == {"limit": 500, "used": 200, "held": 50, "remaining": 250}
    assert len(store.session.events) == 1 and store.locks == [True, True]
    assert row.result == original
    assert store.session.events[0].body["model_call_id"] == str(row.id)
    assert "PRIVATE" not in json.dumps(store.session.events[0].body)


def test_cleanup_and_persistent_estimation_warnings_only_count_distinct_completed_calls():
    bound = scope()
    store = Store(bound)
    for index in range(3):
        row = completed(store, bound, cleanup=True)
        metrics = record_call(store, bound, ModelTurn(ledger_call_id=row.id), messages())
        assert metrics["cleanup_count"] == index + 1
    assert metrics["estimation_error_streak"] == 3
    assert metrics["warnings"] == ["fixed_over_half_focus", "cleanup_more_than_twice",
                                    "persistent_estimation_error"]
    row = completed(store, bound, estimated=200)
    metrics = record_call(store, bound, ModelTurn(ledger_call_id=row.id), messages())
    assert metrics["estimation_error_streak"] == 0
    assert "persistent_estimation_error" not in metrics["warnings"]


@pytest.mark.parametrize("field,value", [
    ("tenant_id", uuid4()), ("run_id", uuid4()), ("tool", "category.read"),
    ("state", "started"), ("error_code", "SOURCE_UNAVAILABLE"),
])
def test_foreign_or_unsettled_ledger_never_becomes_context_observation(field, value):
    bound = scope()
    store = Store(bound)
    row = completed(store, bound)
    setattr(row, field, value)
    with pytest.raises(DomainError) as caught:
        record_call(store, bound, ModelTurn(ledger_call_id=row.id), messages())
    assert caught.value.code == "FORBIDDEN_SCOPE" and store.session.events == []


def test_metrics_cannot_cross_isolation_or_current_revocation():
    bound = scope()
    store = Store(bound)
    row = completed(store, bound)
    row.execution_binding = {**row.execution_binding, "isolation": "extract"}
    with pytest.raises(DomainError):
        record_call(store, bound, ModelTurn(ledger_call_id=row.id), messages())
    store.revoked = True
    with pytest.raises(DomainError):
        record_call(store, bound, ModelTurn(ledger_call_id=row.id), messages())
    assert store.session.events == []


def test_legacy_without_budget_or_pure_graph_without_ledger_is_preserved():
    bound = scope()
    store = Store(bound)
    row = completed(store, bound)
    row.result = {"text": "old"}
    assert record_call(store, bound, ModelTurn(ledger_call_id=row.id), messages()) is None
    assert record_call(store, bound, ModelTurn(), messages()) is None
    assert store.session.events == [] and store.run.versions == {}


def test_context_incomplete_observes_no_provider_and_same_failed_admission_is_idempotent():
    bound = scope()
    store = Store(bound)
    error = DomainError("CONTEXT_INCOMPLETE", "required context does not fit", detail={
        "context_budget": budget(),
        "missing": [{"field": "work_state.constraints", "estimated_tokens": 9000}],
    })
    record_incomplete(store, bound, error, messages())
    record_incomplete(store, bound, error, messages())
    assert len(store.session.events) == 1 and store.session.rows == {}
    body = store.session.events[0].body
    assert set(body["warnings"]) == {"context_incomplete", "fixed_over_half_focus"}
    assert body["context_incomplete"] and body["fixed_over_half"] is True
    assert body["missing"][0]["field"] == "work_state.constraints"
    assert "PRIVATE" not in json.dumps(body)


def test_actual_host_model_step_captures_admission_and_records_ledger_observation():
    from pdos_next.agent_kernel.host import BoundHost, KernelAdapters
    from pdos_next.service import digest
    from tests.agent_kernel.test_gateway import configured_route

    bound = scope()
    store = Store(bound)
    reference = str(uuid4())
    original = [{"role": "user", "content": json.dumps({
        "goal": "goal", "context_ref": reference, "context": {}, "omitted_fields": [],
    })}]
    store.run.versions = {"context_snapshots": {"saved": {
        "event_id": reference, "content_digest": digest({}), "omitted": [], "skills": [],
    }}}
    host = BoundHost(store, KernelAdapters(
        route_for=lambda _: configured_route(), project_context=None, verify_result=None,
        prepare_candidate=None, execute_command=None, provider_client=object(),
    ))
    row = completed(store, bound)

    def gateway_turn(scope, *, emit, **kwargs):
        actual, admitted_budget = host.admit_context(
            scope, route=configured_route(), loaded_skills=(), **kwargs,
        )
        row.result = {"context_budget": admitted_budget,
                      "usage": asdict(ProviderUsage(100, 5, 40))}
        assert actual == original and actual is not original
        return ModelTurn(ledger_call_id=row.id)

    host.gateway.turn = gateway_turn
    turn, actual = host.model_step(
        bound, system="fixed", tools=[], messages=original, output_schema={},
    )
    assert turn.ledger_call_id == row.id and actual == original and actual is not original
    assert store.session.events[-1].body["type"] == "context_observed"
    assert store.session.events[-1].body["cache"]["read_tokens"] == 40
    # Plain child wrappers keep the original ModelTurn return contract.
    assert host.model(bound, system="fixed", tools=[], messages=original, output_schema={}) == turn
    assert len(store.session.events) == 1


def test_actual_host_incomplete_admission_records_metrics_without_starting_model():
    from dataclasses import replace

    from pdos_next.agent_kernel.host import BoundHost, KernelAdapters
    from tests.agent_kernel.test_gateway import configured_route

    bound = scope()
    store = Store(bound)
    host = BoundHost(store, KernelAdapters(
        route_for=lambda _: configured_route(), project_context=None, verify_result=None,
        prepare_candidate=None, execute_command=None, provider_client=object(),
    ))
    original = [{"role": "user", "content": json.dumps({
        "goal": "verbatim", "context": {"work_state": {"constraints": ["不可缩减" * 5000]}},
    }, ensure_ascii=False)}]
    with pytest.raises(DomainError) as caught:
        host.admit_context(
            bound, route=replace(configured_route(), context_window_tokens=8192),
            system="fixed", tools=[], messages=original, output_schema={}, loaded_skills=(),
        )
    assert caught.value.reason == "CONTEXT_INCOMPLETE"
    assert store.session.rows == {} and len(store.session.events) == 1
    assert store.session.events[0].body["type"] == "context_admission_observed"


@pytest.mark.parametrize("known,state", [(False, "unknown"), (False, "failed"), (True, "failed")])
def test_failed_calls_use_only_actual_ledger_usage_and_unknown_cache_stays_unknown(known, state):
    from pdos_next.agent_kernel.context_observability import record_failed

    bound = scope()
    store = Store(bound)
    row = completed(store, bound)
    row.state, row.error_code = state, "SOURCE_UNAVAILABLE"
    row.result = None
    row.cost_state = "actual" if known else "unmetered"
    row.charged_tokens, row.actual_input_tokens, row.actual_output_tokens = 9000, 200, 10
    error = DomainError("SOURCE_UNAVAILABLE", "synthetic failed transport", detail={
        "call_id": str(row.id),
    })
    metrics = record_failed(store, bound, error, messages(), budget(cleanup=True))
    repeated = record_failed(store, bound, error, messages(), budget(cleanup=True))
    assert repeated == metrics and len(store.session.events) == 1
    assert metrics["cleanup_count"] == 1 and metrics["call_state"] == state
    assert metrics["usage_status"] == ("recorded" if known else "unavailable")
    assert metrics["actual_input_tokens"] == (200 if known else None)
    assert metrics["actual_output_tokens"] == (10 if known else None)
    assert metrics["cache"]["read_hit_ratio"] is None
    assert metrics["cache"]["read_tokens"] is None
    assert row.result is None and row.charged_tokens == 9000


def test_failed_preclaim_error_never_fabricates_model_call_observation():
    from pdos_next.agent_kernel.context_observability import record_failed

    bound = scope()
    store = Store(bound)
    error = DomainError("FORBIDDEN_SCOPE", "synthetic preclaim denial")
    assert record_failed(store, bound, error, messages(), budget()) is None
    assert store.session.events == [] and store.locks == []


def test_normalized_zero_cache_does_not_claim_measured_miss_when_provider_did_not_report_it():
    metrics = call_metrics(budget=budget(), usage=asdict(ProviderUsage(200, 20)), messages=[])
    assert metrics["cache"]["read_tokens"] == 0
    assert metrics["cache"]["read_hit_ratio"] is None
    assert metrics["cache"]["reporting"] == "zero_or_unreported"
