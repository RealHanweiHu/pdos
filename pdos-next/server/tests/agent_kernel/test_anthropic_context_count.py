"""Registered gateway + real native HTTP adapter; synthetic ports and MockTransport only."""

import json
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pdos_agent_runtime.graph import registered_graph_context
from pydantic import SecretStr

from pdos_next.agent_kernel import gateway as gateway_module
from pdos_next.agent_kernel.gateway import AgentGateway
from pdos_next.agent_kernel.types import ModelTurn, RunScope
from pdos_next.errors import DomainError
from pdos_next.providers.agent_client import (
    AgentProviderClient,
    prompt_cache_policy,
    request_body,
)
from pdos_next.providers.types import ProviderError, ProviderRoute, ProviderUsage
from pdos_next.service import digest

SYSTEM = "a" * 3000
MESSAGES = [{"role": "user", "content": "q" * 200}]
SCHEMA = {"type": "object"}


def route():
    return ProviderRoute(
        "anthropic-native", "https://synthetic-provider.test/v1", "synthetic-model",
        SecretStr("synthetic-not-a-real-secret"), "synthetic@1",
        context_window_tokens=7048, max_output_tokens=2048,
    )


@dataclass
class Decision:
    provider: str = "synthetic@1"
    data_categories: tuple = ("synthetic",)
    agreement_id: str | None = None
    agreement_revision: int | None = None
    checked_at: datetime = datetime(2026, 10, 29, tzinfo=UTC)
    prompt_cache_allowed: bool = True


class Store:
    """Durable-call port double, not evidence of real PG/ACL or domain READs."""

    def __init__(self):
        self.run = SimpleNamespace(versions={})
        self.calls, self.events, self.released = {}, [], []
        self.cancelled = False
        self.on_claim = lambda _: None

    def current(self, _):
        if self.cancelled:
            raise DomainError("CANCELLED_RUN", "Synthetic cancellation")

    @contextmanager
    def transaction(self, scope, **_):
        self.current(scope)
        yield self, self.run

    def scalar(self, statement):
        keys = next(value for value in statement.compile().params.values()
                    if isinstance(value, list))
        return next((key for key in keys if key in self.calls), None)

    def emit(self, _, event):
        self.events.append(deepcopy(event))

    def claim(self, scope, key, tool, payload, **options):
        self.current(scope)
        call = self.calls.get(key)
        if call:
            assert call["digest"] == digest(payload)
            assert call["binding"] == options["execution_binding"]
            if call["state"] != "completed":
                raise DomainError("EXTERNAL_OUTCOME_UNKNOWN", "Synthetic no-blind-retry fence")
            return call["id"], deepcopy(call["result"])
        call = {"id": uuid4(), "tool": tool, "digest": digest(payload),
                "payload": deepcopy(payload), "binding": options["execution_binding"],
                "state": "started", "result": None, "reservation": options.get("reservation", 0)}
        self.calls[key] = call
        self.on_claim(tool)
        return call["id"], None

    def settle(self, _, call_id, *, result, usage, **_options):
        call = next(row for row in self.calls.values() if row["id"] == call_id)
        call.update(state="completed", result=deepcopy(result), usage=usage)

    def release_call(self, _, call_id, **options):
        call = next(row for row in self.calls.values() if row["id"] == call_id)
        call["state"] = "unknown" if options.get("unknown") else "failed"
        self.released.append((call["tool"], options))


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setattr("pdos_next.domain.automations.runtime.guard_tool", lambda *_: None)
    monkeypatch.setattr("pdos_next.agent_kernel.proposal_context.check", lambda *_: None)
    decision, store, configured = Decision(), Store(), [route()]
    monkeypatch.setattr(gateway_module, "egress", lambda *_, **__: replace(decision))
    scope = RunScope(*(uuid4() for _ in range(6)), data_categories=frozenset({"synthetic"}))
    return SimpleNamespace(decision=decision, store=store, configured=configured, scope=scope)


def invoke(gateway, scope, *, system=SYSTEM):
    with registered_graph_context("xiaopai"):
        return gateway.turn(scope, system=system, messages=MESSAGES, tools=[], output_schema=SCHEMA)


def native_client(callback=None, *, count=900):
    seen = []

    def transport(request):
        seen.append((request.url.path, json.loads(request.content)))
        if callback:
            response = callback(request)
            if response is not None:
                return response
        if request.url.path.endswith("/count_tokens"):
            return httpx.Response(200, json={"input_tokens": count},
                                  headers={"request-id": "synthetic-count-1"})
        return httpx.Response(200, json={
            "id": "synthetic-model-1", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": '{"ok":true}'}],
            "usage": {"input_tokens": 30, "output_tokens": 7},
        })

    return AgentProviderClient(httpx.MockTransport(transport)), seen


def gateway(harness, client):
    return AgentGateway(harness.store, route_for=lambda _: harness.configured[0],
                        cost_required=False, client=client)


def test_registered_near_focus_counts_same_native_inputs_separately_and_replays_once(harness):
    client, seen = native_client()
    service = gateway(harness, client)
    try:
        first = invoke(service, harness.scope)
        second = invoke(service, harness.scope)
    finally:
        client.close()
    assert first.structured == second.structured == {"ok": True}
    assert [path for path, _ in seen] == ["/v1/messages/count_tokens", "/v1/messages"]
    count_body, model_body = [body for _, body in seen]
    assert set(count_body) == {"model", "system", "messages", "tools", "output_config"}
    assert count_body == {key: value for key, value in model_body.items()
                          if key not in {"max_tokens", "stream"}}
    count_call = next(row for row in harness.store.calls.values()
                      if row["tool"] == "model.count_tokens")
    model_call = next(row for row in harness.store.calls.values() if row["tool"] == "model")
    assert count_call["binding"] == {
        "kind": "unbound", "dispatch": "anthropic-count-tokens/v1",
        "model_binding": model_call["binding"],
    }
    assert count_call["result"] == {"input_tokens": 900}
    assert count_call["usage"] == count_call["reservation"] == 0
    assert model_call["usage"] == 37
    assert model_call["result"]["context_budget"]["provider_counted_input_tokens"] == 900
    assert model_call["result"]["context_budget"]["actual_input_tokens"] == 30
    observation = harness.store.run.versions["context_observations"]["main"]
    assert observation["actual_input_tokens"] == 30


@pytest.mark.parametrize("failure", ["over_focus", "http", "invalid", "redirect"])
def test_count_failure_or_overflow_never_dispatches_generation(harness, failure):
    def fail(request):
        assert request.url.path.endswith("/count_tokens")
        if failure == "http":
            return httpx.Response(429)
        if failure == "invalid":
            return httpx.Response(200, json={"input_tokens": True})
        if failure == "redirect":
            return httpx.Response(302, headers={"location": "https://other.test/messages"})

    client, seen = native_client(fail, count=1001)
    try:
        with pytest.raises(DomainError) as error:
            invoke(gateway(harness, client), harness.scope)
    finally:
        client.close()
    assert len(seen) == 1
    expected = ("CONTEXT_INCOMPLETE" if failure == "over_focus" else
                "RATE_LIMITED" if failure == "http" else "SOURCE_UNAVAILABLE")
    assert error.value.reason == expected
    model_release = next(options for tool, options in harness.store.released if tool == "model")
    assert model_release["unknown"] is False
    assert model_release["usage"] == 0
    assert "context_observations" not in harness.store.run.versions


@pytest.mark.parametrize("change", ["cache", "route", "categories", "cancel"])
def test_count_then_policy_route_or_cancellation_change_prevents_generation(harness, change):
    def mutate(request):
        if request.url.path.endswith("/count_tokens"):
            if change == "cache":
                harness.decision.prompt_cache_allowed = False
            elif change == "route":
                harness.configured[0] = replace(route(), version="synthetic@2")
            elif change == "categories":
                harness.decision.data_categories = ("customer_original",)
            else:
                harness.store.cancelled = True

    client, seen = native_client(mutate)
    try:
        with pytest.raises(DomainError):
            invoke(gateway(harness, client), harness.scope)
    finally:
        client.close()
    assert len(seen) == 1
    assert all(path.endswith("/count_tokens") for path, _ in seen)


def test_count_reservation_route_rotation_stops_before_count_transport(harness):
    harness.store.on_claim = lambda tool: harness.configured.__setitem__(
        0, replace(route(), version="synthetic@2"),
    ) if tool == "model.count_tokens" else None
    client, seen = native_client()
    try:
        with pytest.raises(DomainError) as error:
            invoke(gateway(harness, client), harness.scope)
    finally:
        client.close()
    assert error.value.code == "VERSION_CONFLICT" and seen == []


def test_cache_revocation_after_model_reservation_prevents_all_transport(harness):
    harness.store.on_claim = lambda tool: setattr(
        harness.decision, "prompt_cache_allowed", False,
    ) if tool == "model" else None
    client, seen = native_client()
    try:
        with pytest.raises(DomainError) as error:
            invoke(gateway(harness, client), harness.scope)
    finally:
        client.close()
    assert error.value.reason == "SOURCE_STALE" and seen == []


@pytest.mark.parametrize("allowed", [True, False])
def test_server_cache_fact_controls_every_marker_and_request_hash(harness, allowed):
    harness.decision.prompt_cache_allowed = allowed
    client, seen = native_client()
    try:
        invoke(gateway(harness, client), harness.scope)
    finally:
        client.close()
    assert all(('"cache_control"' in json.dumps(body)) is allowed for _, body in seen)
    assert all(row["payload"].get("prompt_cache_allowed", True) is allowed
               for row in harness.store.calls.values())
    messages = [*MESSAGES, {"role": "assistant", "content": "old"},
                {"role": "user", "content": "latest"}]
    with prompt_cache_policy(allowed):
        body = request_body(route(), SYSTEM, messages, [], SCHEMA, False)
    assert json.dumps(body).count('"cache_control"') == (3 if allowed else 0)


def test_legacy_true_hash_replays_under_current_false_without_regeneration(harness):
    client, seen = native_client()
    service = gateway(harness, client)
    try:
        first = invoke(service, harness.scope)
        model = next(row for row in harness.store.calls.values() if row["tool"] == "model")
        assert "prompt_cache_allowed" not in model["payload"]  # Existing True/default hash.
        assert invoke(service, harness.scope).ledger_call_id == first.ledger_call_id
        harness.decision.prompt_cache_allowed = False
        assert invoke(service, harness.scope).ledger_call_id == first.ledger_call_id
    finally:
        client.close()
    assert len(seen) == 2  # One count and one generation, including all replays.


@pytest.mark.parametrize("state", ["started", "unknown"])
def test_cache_policy_change_cannot_dispatch_around_original_pending_call(harness, state):
    client, seen = native_client()
    service = gateway(harness, client)
    try:
        invoke(service, harness.scope)
        model = next(row for row in harness.store.calls.values() if row["tool"] == "model")
        model["state"] = state
        harness.decision.prompt_cache_allowed = False
        with pytest.raises(DomainError) as error:
            invoke(service, harness.scope)
        assert error.value.reason == "EXTERNAL_OUTCOME_UNKNOWN"
    finally:
        client.close()
    assert len(seen) == 2 and len(harness.store.calls) == 2


def test_far_from_focus_preserves_old_explicit_synthetic_turn_interface(harness):
    class OldClient:
        def turn(self, configured, *, system, messages, tools, output_schema, emit, cancelled):
            return ModelTurn(usage=ProviderUsage(5, 1), structured={"ok": True})

    assert invoke(gateway(harness, OldClient()), harness.scope, system="short").structured == {
        "ok": True,
    }
    assert [row["tool"] for row in harness.store.calls.values()] == ["model"]


@pytest.mark.parametrize("payload", [
    {"input_tokens": -1}, {"input_tokens": 0.5}, {"input_tokens": "900"}, {},
])
def test_native_count_response_requires_a_nonnegative_integer(harness, payload):
    client, seen = native_client(lambda _: httpx.Response(200, json=payload))
    try:
        with pytest.raises(DomainError) as error:
            invoke(gateway(harness, client), harness.scope)
    finally:
        client.close()
    assert error.value.reason == "SOURCE_UNAVAILABLE" and len(seen) == 1


def test_unregistered_graph_never_counts_and_endpoint_remains_exact_same_host(harness):
    client, seen = native_client()
    try:
        with pytest.raises(DomainError, match="登记"):
            gateway(harness, client).turn(harness.scope, system=SYSTEM, messages=MESSAGES,
                                        tools=[], output_schema=SCHEMA)
        for target in ("https://other.test/v1/messages/count_tokens",
                       "https://synthetic-provider.test/v1/messages/count_tokens/other"):
            with pytest.raises(ValueError):
                route().assert_target_allowed(target)
        with pytest.raises(ProviderError) as error:
            client.count_tokens(route(), system=SYSTEM, messages=MESSAGES, tools=[],
                                output_schema=SCHEMA, cancelled=lambda: True)
        assert error.value.code == "MODEL_CANCELLED"
    finally:
        client.close()
    assert seen == []
