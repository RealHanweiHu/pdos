from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from pdos_agent_runtime.graph import registered_graph_context
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.gateway import AgentGateway
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.agent_kernel.types import ModelTurn
from pdos_next.errors import DomainError
from pdos_next.models import Grant, now
from pdos_next.providers.types import ProviderError, ProviderRoute, ProviderUsage
from tests.agent_kernel.test_transactions import run


def configured_route():
    return ProviderRoute(
        "openai-compatible",
        "https://synthetic-provider.test/v1",
        "synthetic-model",
        SecretStr("synthetic-not-a-real-secret"),
        "synthetic@1",
        context_window_tokens=200_000,
    )


def turn(gateway, scope):
    with registered_graph_context("xiaopai"):
        return gateway.turn(
            scope,
            system="frozen",
            messages=[{"role": "user", "content": "synthetic"}],
            tools=[],
            output_schema={"type": "object"},
        )


class Client:
    def __init__(self, callback):
        self.callback, self.calls = callback, 0

    def turn(self, *args, **kwargs):
        self.calls += 1
        return self.callback(kwargs)

    def close(self):
        pass


def test_provider_call_requires_registered_graph_and_replays_saved_request(setup):
    store, scope = run(setup)
    continuation = {"protocol": "openai-compatible", "route_digest": configured_route().digest,
                    "message": {"role": "assistant", "content": "done",
                                "reasoning_content": "synthetic private replay context"}}
    client = Client(
        lambda _: ModelTurn("done", usage=ProviderUsage(12, 3), structured={"ok": True},
                            continuation=continuation)
    )
    gateway = AgentGateway(
        store, cost_required=False, route_for=lambda _: configured_route(), client=client
    )
    with pytest.raises(DomainError):
        gateway.turn(scope, system="x", messages=[], tools=[], output_schema={})
    assert client.calls == 0
    first = turn(gateway, scope)
    restored = turn(gateway, scope)
    assert first.structured == restored.structured == {"ok": True} and client.calls == 1
    assert first.continuation == restored.continuation == continuation
    with store.transaction(scope) as (session, row):
        assert row.held_tokens == 0 and row.used_tokens == 15
        saved = session.scalar(select(AgentToolCall.result).where(
            AgentToolCall.run_id == row.id, AgentToolCall.tool == "model"))
        assert set(saved["context_budget"]["segments"]) == {
            "system", "tools", "skills", "envelope", "history", "loop",
        }
        assert saved["context_budget"]["window"] == 200_000
        assert saved["context_budget"]["window_configured"] is True
    changed = AgentGateway(
        store, route_for=lambda _: replace(configured_route(), version="synthetic@2"), client=client
    )
    with pytest.raises(DomainError) as e:
        turn(changed, scope)
    assert e.value.code == "VERSION_CONFLICT" and client.calls == 1
    same_revision_wrong_model = AgentGateway(
        store,
        cost_required=False,
        route_for=lambda _: replace(configured_route(), model="different-model"),
        client=client,
    )
    with pytest.raises(DomainError) as error:
        turn(same_revision_wrong_model, scope)
    assert error.value.code == "VERSION_CONFLICT" and client.calls == 1


def test_private_run_without_agreement_proceeds_and_receipts_none(setup):
    # P26: the agreement registry is optional; an unsigned provider is not blocked.
    store, scope = run(setup, private_context=True, data_categories=("customer_original",))
    client = Client(lambda _: ModelTurn(usage=ProviderUsage(1, 1), structured={"ok": True}))
    turn(
        AgentGateway(
            store, cost_required=False, route_for=lambda _: configured_route(), client=client
        ),
        scope,
    )
    assert client.calls == 1
    with store.transaction(scope) as (_, row):
        assert row.held_tokens == 0 and row.versions["provider_key"]


def test_run_provider_identity_cannot_change_between_model_calls(setup):
    store, scope = run(setup)
    client = Client(lambda _: ModelTurn(usage=ProviderUsage(1, 1), structured={"ok": True}))
    provider = ["synthetic@1"]
    gateway = AgentGateway(
        store,
        cost_required=False,
        route_for=lambda _: configured_route(),
        provider_for=lambda *_: provider[0],
        client=client,
    )
    turn(gateway, scope)
    provider[0] = "different-provider"
    with pytest.raises(DomainError) as error:
        turn(gateway, scope)
    assert error.value.code == "VERSION_CONFLICT" and client.calls == 1
    with store.transaction(scope) as (_, row):
        assert row.versions["provider_key"] == "synthetic@1" and row.held_tokens == 0


def test_generic_capability_graph_cannot_bypass_registered_xiaopai_gateway(setup):
    from pdos_agent_runtime.graph import execute_graph

    store, scope = run(setup)
    client = Client(lambda _: pytest.fail("Only the registered 小Pai graph may call this model"))
    gateway = AgentGateway(
        store, cost_required=False, route_for=lambda _: configured_route(), client=client
    )

    def old_capability(_):
        return gateway.turn(scope, system="fixed", messages=[], tools=[], output_schema={})

    with pytest.raises(DomainError) as error:
        execute_graph(old_capability, {}, thread_id="synthetic-old-capability")
    assert error.value.code == "FORBIDDEN_SCOPE" and client.calls == 0


def test_prompt_is_fixed_and_tool_disclosure_only_grows_per_isolation(setup):
    store, scope = run(setup)
    client = Client(lambda _: ModelTurn(structured={"ok": True}, usage=ProviderUsage(1, 1)))
    gateway = AgentGateway(
        store, cost_required=False, route_for=lambda _: configured_route(), client=client
    )
    turn(gateway, scope)
    with registered_graph_context("xiaopai"):
        gateway.turn(
            scope.child("research"),
            system="child frozen",
            messages=[],
            tools=[{"name": "research.read"}],
            output_schema={},
        )
        # The trusted graph progressively discloses tools after loading a skill.
        # Extending an empty main list is allowed; shrinking it or changing the
        # system prefix remains a conflict, independently of the child list.
        gateway.turn(scope, system="frozen",
            messages=[{"role": "user", "content": "synthetic"}],
            tools=[{"name": "different"}], output_schema={})
        for changes in ({"system": "changed"}, {"tools": []}):
            with pytest.raises(DomainError) as error:
                gateway.turn(
                    scope,
                    **{
                        "system": "frozen",
                        "messages": [{"role": "user", "content": "synthetic"}],
                        "tools": [{"name": "different"}],
                        "output_schema": {},
                        **changes,
                    },
                )
            assert error.value.code == "VERSION_CONFLICT"
    assert client.calls == 3


def test_scope_revocation_during_call_frees_slot_without_revealing_result(setup):
    store, scope = run(setup)

    def revoke(_):
        with Session(setup.admin) as s, s.begin():
            grant = s.scalar(
                select(Grant).where(
                    Grant.tenant_id == setup.tenant, Grant.principal_id == setup.agent
                )
            )
            grant.expires_at = now() - timedelta(seconds=1)
        return ModelTurn(
            "private result", usage=ProviderUsage(12, 3), structured={"private": "result"}
        )

    client = Client(revoke)
    with pytest.raises(DomainError) as e:
        turn(
            AgentGateway(
                store, cost_required=False, route_for=lambda _: configured_route(), client=client
            ),
            scope,
        )
    assert e.value.code == "FORBIDDEN_SCOPE"
    with Session(setup.admin) as s:
        row = s.get(AgentRun, scope.run_id)
        call = s.scalar(select(AgentToolCall).where(AgentToolCall.run_id == scope.run_id))
        assert (
            row.held_tokens == 0
            and row.used_tokens > 0
            and call.state == "unknown"
            and call.result is None
        )
    assert (
        store.release_call(
            replace(scope, requester_id=uuid4()), call.id, error="SOURCE_UNAVAILABLE"
        )
        is False
    )


def test_unknown_network_attempt_frees_slot_and_never_blindly_retries(setup):
    store, scope = run(setup)

    def unknown(_):
        raise ProviderError("PROVIDER_RESULT_UNKNOWN", unknown=True, request_id="synthetic-request")

    client = Client(unknown)
    gateway = AgentGateway(
        store, cost_required=False, route_for=lambda _: configured_route(), client=client
    )
    for _ in range(2):
        with pytest.raises(DomainError) as e:
            turn(gateway, scope)
        assert e.value.code == "EXTERNAL_OUTCOME_UNKNOWN"
    assert client.calls == 1
    with store.transaction(scope) as (s, row):
        call = s.scalar(select(AgentToolCall).where(AgentToolCall.run_id == scope.run_id))
        assert row.held_tokens == 0 and call.provider_request_id == "synthetic-request"
