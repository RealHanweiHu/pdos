"""Actual SQL-derived query leases; root runs after the unnumbered query guard.

The synthetic model ledger is the established native fixture. Assertions below
use real ordinary-role KernelStore transactions and real persisted call rows.
No fake store or direct business-table mutation substitutes for those guards.
"""

import os
from dataclasses import replace
from uuid import UUID

import pytest
from pdos_agent_runtime.graph import registered_graph_context
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import ModelBinding
from pdos_next.agent_kernel.models import AgentToolCall, ValidationBudget
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.read_execution import build_read_binding
from pdos_next.enterprise_search.assistant_adapter import AssistantReadAdapter
from pdos_next.enterprise_search.embedding_profiles import active
from pdos_next.enterprise_search.embedding_query import QueryEmbedding, QueryPorts
from pdos_next.enterprise_search.embedding_query_binding import TOOL, bind, key, payload
from tests.agent_kernel import test_domain_adapter_transactions as native
from tests.agent_kernel.test_cost_budget import wallet
from tests.agent_kernel.test_read_proof_transactions import read_fixture
from tests.enterprise_search.embedding_harness import command_for, ports_for, save_profile

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Explicit verified local PostgreSQL required"
)


def actual_query(setup, monkeypatch):
    budget_id = wallet(setup)
    original = native.ledger

    def budgeted_ledger():
        value = original()
        value.run.validation_budget_id = budget_id
        value.run.token_limit = 500_000
        return value

    monkeypatch.setattr(native, "ledger", budgeted_ledger)
    f = read_fixture(setup, tool="assistant.search", arguments={"query": "合成实际查询"})
    provider, backend = ports_for(setup)
    receipt, _ = save_profile(setup, backend, command_for(setup))
    profile_id = UUID(receipt["subject_id"])
    ports = QueryPorts(backend, lambda _: profile_id)
    with f.store.transaction(f.scope) as (session, run):
        model = session.get(AgentToolCall, f.read_source.model_call_id)
        bound = build_read_binding(
            f.scope,
            run,
            f.read_spec,
            f.read_source,
            ModelBinding.model_validate(model.execution_binding),
        )
    parent_id, _ = f.store.claim(
        f.scope,
        f.read_key,
        "assistant.search",
        f.read_arguments,
        execution_binding=bound.model_dump(mode="json"),
    )
    adapter = AssistantReadAdapter(f.store, f.adapter)
    runtime = QueryEmbedding(f.store, ports, source_guard=adapter.guard)
    return f, runtime, provider, budget_id, parent_id


def test_completed_query_lease_recovers_from_real_ledger_without_provider_or_key(
    setup,
    monkeypatch,
):
    f, runtime, provider, budget_id, parent_id = actual_query(setup, monkeypatch)
    with registered_graph_context("xiaopai"):
        first = runtime.prepare(f.scope, parent_id, f.read_arguments)
    assert first.status == "ready" and first.vector == (1.0, 0.0) and len(provider.calls) == 1
    with Session(setup.admin) as session:
        parent = session.get(AgentToolCall, parent_id)
        assert parent.state == "started"  # Child completed before its orchestration settled.
        budget = session.get(ValidationBudget, budget_id)
        assert budget.calls == 1 and budget.spent_micro_usd > 0 and budget.held_micro_usd == 0
    provider.resolve = lambda _: pytest.fail("A persisted completed vector must not resolve a key")
    fresh = QueryEmbedding(
        KernelStore(setup.engine),
        replace(runtime.ports, profile_for=lambda _: pytest.fail("Frozen")),
        source_guard=AssistantReadAdapter(KernelStore(setup.engine), f.adapter).guard,
    )
    with registered_graph_context("xiaopai"):
        assert fresh.prepare(f.scope, parent_id, f.read_arguments) == first
    assert len(provider.calls) == 1
    with Session(setup.admin) as session:
        assert session.get(ValidationBudget, budget_id).calls == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("parent_input_digest", "a" * 64),
        ("query_digest", "f" * 64),
        ("cancel_epoch", 2),
        ("extra_authority", "model-provided"),
        ("kind", "unbound"),
    ],
)
def test_query_sql_refuses_forged_binding_and_rolls_back_the_real_wallet(
    setup,
    monkeypatch,
    field,
    value,
):
    f, runtime, provider, budget_id, parent_id = actual_query(setup, monkeypatch)
    with f.store.transaction(f.scope, lock=True) as (session, run):
        frozen = runtime.frozen_profile(session, f.scope, run)
        parent = session.get(AgentToolCall, parent_id)
        binding = bind(parent, frozen, f.read_arguments["query"], f.scope.cancel_epoch)
    with f.store.transaction(f.scope) as (session, _run):
        _profile, metadata = active(session, setup.tenant, frozen.profile_version_id)

    card = runtime.ports.backend.pricing_for(
        setup.tenant,
        metadata,
    )
    upper = 10_000
    with pytest.raises(DBAPIError):
        f.store.claim(
            f.scope,
            key(f.scope.run_id, parent_id),
            TOOL,
            payload(parent_id, frozen, f.read_arguments["query"]),
            reservation=upper,
            cost_lease=(card.reserve(upper, 0), upper, 0, card.snapshot()),
            execution_binding={**binding.model_dump(mode="json"), field: value},
        )
    assert not provider.calls
    with Session(setup.admin) as session:
        budget = session.get(ValidationBudget, budget_id)
        assert budget.calls == 0 and budget.spent_micro_usd == 0 and budget.held_micro_usd == 0
