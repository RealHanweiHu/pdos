import pytest
from pdos_agent_runtime.graph import registered_graph_context
from pdos_next.agent.kernel.gateway import AgentGateway
from pdos_next.agent.kernel.types import ModelTurn
from pdos_next.core.service import digest
from pdos_next.errors import DomainError
from pdos_next.providers.types import ProviderUsage
from tests.agent_kernel.test_gateway import Client, configured_route
from tests.agent_kernel.test_transactions import run


def test_run_records_prompt_version_and_rejects_semantic_identity_drift(setup):
    store, scope = run(setup)
    client = Client(lambda _: ModelTurn(structured={"ok": True}, usage=ProviderUsage(1, 1)))
    gateway = AgentGateway(
        store, cost_required=False, route_for=lambda _: configured_route(), client=client,
    )
    system = "frozen versioned prompt"
    identity = {
        "key": "xiaopai.main",
        "version": "1.0.0",
        "content_digest": digest(system),
        "system_digest": digest(system),
    }

    def call(actual):
        with registered_graph_context("xiaopai"):
            return gateway.turn(
                scope,
                system=system,
                messages=[{"role": "user", "content": "synthetic"}],
                tools=[],
                output_schema={"type": "object"},
                prompt_identity=actual,
            )

    call(identity)
    call(identity)
    assert client.calls == 1
    with store.transaction(scope) as (_, row):
        assert row.versions["prompt_identities"]["main"] == identity
        assert row.versions["prompt_prefixes"]["main"] == digest(system)
    with pytest.raises(DomainError) as error:
        call({**identity, "version": "1.0.1-draft"})
    assert error.value.code == "VERSION_CONFLICT" and client.calls == 1
    with pytest.raises(DomainError) as error:
        call({**identity, "system_digest": "0" * 64})
    assert error.value.code == "VERSION_CONFLICT" and client.calls == 1
