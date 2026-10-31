"""Actual Run, projected context receipts and registered graph; no real model or KMS."""

import json
from copy import deepcopy
from dataclasses import replace
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import SkillBinding
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.context_projection import check_messages
from pdos_next.agent_kernel.disclosure import disclosure, skill_operations
from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.management import register_agreement
from pdos_next.agent_kernel.models import (
    AgentEvent,
    AgentRun,
    TenantAdministrator,
    TenantSkillEnablement,
)
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.errors import DomainError
from pdos_next.providers.types import ProviderUsage
from tests.agent_kernel.test_domain_adapter_transactions import fixture
from tests.agent_kernel.test_gateway import configured_route
from tests.agent_kernel.test_proposal_runs_pg import start
from tests.agent_kernel.test_transactions import agreement, human_session
from tests.preproject.test_g0 import create


def host_for(setup):
    fixture(setup)
    with Session(setup.admin) as session, session.begin():
        session.add(TenantSkillEnablement(tenant_id=setup.tenant, skill_key="proposal_drafting",
                                         enabled=True))
    proposal, _ = create(setup, {"title": "Synthetic context target", "entry_kind": "new_product"})
    identity, _ = start(setup, proposal)
    owner = Bootstrap(setup.engine)
    scope = owner.store.scope(tenant_id=setup.tenant, requester_id=setup.human,
        writer_id=setup.agent, category_id=setup.category, run_id=UUID(identity))
    return owner, scope, BoundHost(owner.store, owner.adapters())


def load(host, scope, key):
    skill = host.catalog.load(key, scope, host.enabled)
    event = host.emit(scope, {"type": "skill_loaded", "key": key, "version": skill.version,
                             "digest": skill.digest, "isolation": "main"})
    return SkillBinding(key=key, version=skill.version, digest=skill.digest, load_event_id=event)


def test_context_uses_loaded_methods_and_snapshot_is_idempotent_private_and_checked(setup):
    owner, scope, host = host_for(setup)
    first = load(host, scope, "public_research")
    initial = host.skill_context(scope, "Synthetic focused research", bindings=(first,))
    assert "proposal" not in initial["context"]
    assert initial == host.skill_context(scope, "Synthetic focused research", bindings=(first,))
    second = load(host, scope, "proposal_drafting")
    expanded = host.skill_context(scope, "Synthetic focused research", bindings=(first, second))
    assert expanded["context"]["proposal"]["id"] == str(scope.proposal_id)
    assert expanded["context_ref"] != initial["context_ref"]
    messages = [{"role": "user", "content": json.dumps(initial)}]
    check_messages(owner.store, scope, messages, (first, second))
    tampered = deepcopy(initial)
    tampered["context"]["goal"] = "Changed after projection"
    with pytest.raises(DomainError) as failure:
        check_messages(owner.store, scope, [{"role": "user", "content": json.dumps(tampered)}],
                       (first, second))
    assert failure.value.code == "SOURCE_STALE"
    with Session(setup.admin) as session:
        row = session.get(AgentRun, scope.run_id)
        assert len(row.versions["context_snapshots"]) == 2
        assert "Synthetic context target" not in str(row.versions["context_snapshots"])
        for value in row.versions["context_snapshots"].values():
            assert value["read_set"] == row.read_sources
            assert value["scope"]["proposal_id"] == str(scope.proposal_id)
            assert value["scope"]["requester_id"] == str(scope.requester_id)
            assert value["scope"]["data_categories"] == ["internal"]
    response = setup.client.get(
        f"/v1/categories/{setup.category}/agent-runs/{scope.run_id}/process", headers=setup.headers,
    )
    assert response.status_code == 200
    steps = [step for step in response.json()["steps"] if step["kind"] == "context_projected"]
    assert len(steps) == 2 and steps[-1]["context_fields"] == sorted(expanded["context"])
    assert "Synthetic context target" not in response.text


@pytest.mark.parametrize("environment", ["development", "test", "production"])
def test_unexpected_fields_fail_in_dev_test_and_are_explained_without_values_in_production(
    setup, monkeypatch, environment
):
    monkeypatch.setenv("PDOS_ENVIRONMENT", environment)
    owner, scope, host = host_for(setup)
    binding = load(host, scope, "public_research")
    def extra(bound, goal, fields):
        value = owner.project_context(bound, goal, fields)
        value["category"]["unplanned_field"] = "PRIVATE OMITTED BODY"
        return value
    host.adapters = replace(host.adapters, project_context=extra)
    if environment == "production":
        projected = host.skill_context(
            scope, "Synthetic production projection", bindings=(binding,),
        )
        assert "PRIVATE OMITTED BODY" not in str(projected)
        assert projected["omitted_fields"] == ["/category/unplanned_field"]
        check_messages(owner.store, scope,
                       [{"role": "user", "content": json.dumps(projected)}], (binding,))
        tampered = {**projected, "omitted_fields": []}
        with pytest.raises(DomainError) as changed:
            check_messages(owner.store, scope,
                           [{"role": "user", "content": json.dumps(tampered)}], (binding,))
        assert changed.value.code == "SOURCE_STALE"
    else:
        with pytest.raises(DomainError) as failure:
            host.skill_context(scope, "Synthetic strict projection", bindings=(binding,))
        assert failure.value.code == "VALIDATION_FAILED"
    with owner.store.transaction(scope) as (session, row):
        events = list(session.scalars(select(AgentEvent).where(AgentEvent.run_id == row.id)))
        event = next(value for value in events if value.body["type"] == "context_projected")
        assert event.body["omitted"] == [{"field": "/category/unplanned_field",
                                          "reason": "outside_skill_context_schema"}]
        assert "PRIVATE OMITTED BODY" not in str(event.body)
    response = setup.client.get(
        f"/v1/categories/{setup.category}/agent-runs/{scope.run_id}/process", headers=setup.headers,
    )
    assert response.status_code == 200 and "outside_skill_context_schema" in response.text
    assert "PRIVATE OMITTED BODY" not in response.text


def test_registered_graph_progressively_adds_context_and_replay_never_calls_provider(setup):
    owner, scope, host = host_for(setup)
    with Session(setup.admin) as session, session.begin():
        session.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))
        session.get(AgentRun, scope.run_id).token_limit = 500000
    with human_session(setup) as session:
        register_agreement(session, setup.ctx, agreement(setup).model_copy(
            update={"data_categories": ["internal"]},
        ))  # Synthetic-only contract fixture.
    class Client:
        def __init__(self):
            self.requests = []
        def turn(self, route, **kwargs):
            self.requests.append(deepcopy(kwargs))
            if len(self.requests) == 1:
                assert "proposal" not in json.loads(kwargs["messages"][0]["content"])["context"]
                return ModelTurn(usage=ProviderUsage(20, 10), calls=(
                    ToolCall(id="load-drafting", name="skill.load",
                             arguments={"name": "proposal_drafting"}),
                ))
            latest = json.loads(kwargs["messages"][-1]["content"])
            assert latest["context"]["proposal"]["id"] == str(scope.proposal_id)
            return ModelTurn(usage=ProviderUsage(20, 10), structured={
                "status": "completed", "summary": "Synthetic projected context", "result": {},
            })
        def close(self):
            pass
    client = Client()
    host = BoundHost(owner.store, replace(host.adapters, route_for=lambda _: configured_route(),
        provider_for=lambda *_: "synthetic-provider", cost_required=False, provider_client=client))
    saver = InMemorySaver()
    result = AgentKernel(host, default_registry()).execute(
        scope, goal="Synthetic progressive context", checkpointer=saver,
        preload=("public_research",),
    )
    assert result["output"]["status"] == "completed" and len(client.requests) == 2
    assert client.requests[0]["system"] == client.requests[1]["system"]
    registry = default_registry()
    research = owner.catalog.configuration("public_research")
    drafting = owner.catalog.configuration("proposal_drafting")
    assert client.requests[0]["tools"] == disclosure(
        registry, "main", skill_operations([research]),
    )
    assert client.requests[1]["tools"] == disclosure(
        registry, "main", skill_operations([research, drafting]),
    )
    before = {tool["name"]: tool for tool in client.requests[0]["tools"]}
    after = {tool["name"]: tool for tool in client.requests[1]["tools"]}
    assert before.keys() < after.keys()
    assert all(after[name] == definition for name, definition in before.items())
    assert "proposal.item.patch" not in before and "proposal.item.patch" in after
    repeated = AgentKernel(host, default_registry()).execute(scope, checkpointer=saver)
    assert repeated["output"] == result["output"] and len(client.requests) == 2
