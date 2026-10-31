"""Local MiniMax development bypasses ceilings, preserving metering and explicit stop."""

from dataclasses import replace

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.gateway import AgentGateway
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall, ValidationBudget
from pdos_next.agent_kernel.types import ModelTurn
from pdos_next.errors import DomainError
from pdos_next.providers.types import ProviderRoute, ProviderUsage
from tests.agent_kernel.test_cost_budget import rate, wallet
from tests.agent_kernel.test_gateway import Client, turn
from tests.agent_kernel.test_model_configuration_transactions import configured, submit
from tests.agent_kernel.test_transactions import run


def route():
    return ProviderRoute("openai-compatible", "https://api.minimax.cn/v1", "MiniMax-M3",
        SecretStr("synthetic-only"), "MiniMax-M3", max_output_tokens=524288,
        budget_policy="development_unlimited")


def test_development_calls_exceed_old_caps_are_metered_once_and_explicit_stop_still_works(setup):
    identity = wallet(setup, micro=0, input=1, output=1, calls=1)
    store, first = run(setup, token_limit=1, validation_budget_id=identity)
    _, second = run(setup, token_limit=1, validation_budget_id=identity)
    _, stopped = run(setup, token_limit=1, validation_budget_id=identity)
    card = replace(rate(), provider="minimax", model="MiniMax-M3",
        configuration_version="MiniMax-M3")
    client = Client(lambda _: ModelTurn(usage=ProviderUsage(100, 10), structured={"ok": True}))
    gateway = AgentGateway(store, route_for=lambda _: route(), provider_for=lambda *_: "minimax",
        rate_card_for=lambda *_: card, client=client)
    turn(gateway, first)
    turn(gateway, first)
    turn(gateway, second)
    assert client.calls == 2
    with Session(setup.admin) as session, session.begin():
        budget = session.get(ValidationBudget, identity)
        assert budget.calls == 2 and budget.call_limit == 1 and budget.limit_micro_usd == 0
        assert budget.spent_micro_usd == 2 * card.actual(ProviderUsage(100, 10))
        assert budget.held_micro_usd == budget.held_input_tokens == budget.held_output_tokens == 0
        calls = list(session.scalars(select(AgentToolCall).where(
            AgentToolCall.run_id.in_([first.run_id, second.run_id]))))
        assert len(calls) == 2 and all(call.cost_state == "actual" for call in calls)
        assert all(call.cost_pricing["budget_policy"] == "development_unlimited" for call in calls)
        assert (
            session.get(AgentRun, first.run_id).versions["budget_policy"] == "development_unlimited"
        )
        budget.active = False
    with pytest.raises(DomainError) as failed:
        turn(gateway, stopped)
    assert failed.value.detail["reason_key"] == "budget_inactive" and client.calls == 2


def test_development_route_requires_verified_local_database_and_changes_route_digest(
    setup, monkeypatch
):
    api, ports, command = configured(setup)
    command["payload"]["metadata"].update(base_url="https://api.minimax.cn/v1", model="MiniMax-M3")
    saved, _ = submit(setup, api, command)
    assert saved.status_code == 200, saved.text
    ports = replace(ports, development_budget_for=lambda *_: True,
        output_limit_for=lambda *_: 524288)
    owner = Bootstrap(setup.engine, ports=ports)
    _, scope = run(setup)
    selected = owner.route_for(scope)
    assert selected.max_output_tokens == 524288
    assert selected.budget_policy == "development_unlimited"
    assert selected.digest != replace(selected, budget_policy="enforced").digest
    monkeypatch.delenv("TEST_DATABASE_MARKER")
    with pytest.raises(DomainError) as failed:
        owner.route_for(scope)
    assert failed.value.code == "FORBIDDEN_SCOPE"
