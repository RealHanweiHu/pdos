"""Actual technical ledger shape/idempotency; run centrally on verified pdos_test only."""

from uuid import uuid4

from pdos_agent_runtime.graph import registered_graph_context
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.gateway import AgentGateway
from pdos_next.agent_kernel.management import register_agreement
from pdos_next.agent_kernel.models import AgentToolCall, TenantAdministrator
from tests.agent_kernel.test_anthropic_context_count import (
    MESSAGES,
    SCHEMA,
    SYSTEM,
    native_client,
    route,
)
from tests.agent_kernel.test_transactions import agreement, human_session, run


def test_actual_count_ledger_is_metadata_only_zero_usage_and_model_replay_is_exactly_once(setup):
    with Session(setup.admin) as session, session.begin():
        session.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))
    cache_policy = agreement(setup).model_copy(update={
        "provider": route().version, "data_categories": ["public"], "prompt_cache_allowed": True,
    })
    with human_session(setup) as session:
        register_agreement(session, setup.ctx, cache_policy)
    store, scope = run(setup)
    client, seen = native_client()
    gateway = AgentGateway(store, route_for=lambda _: route(), cost_required=False, client=client)
    try:
        with registered_graph_context("xiaopai"):
            first = gateway.turn(scope, system=SYSTEM, messages=MESSAGES,
                                 tools=[], output_schema=SCHEMA)
        with human_session(setup) as session:
            register_agreement(session, setup.ctx, cache_policy.model_copy(update={
                "expected_revision": 1, "prompt_cache_allowed": False,
                "idempotency_key": "count-cache-tighten:" + str(uuid4()),
            }))
        with registered_graph_context("xiaopai"):
            second = gateway.turn(scope, system=SYSTEM, messages=MESSAGES,
                                  tools=[], output_schema=SCHEMA)
    finally:
        client.close()
    assert first.ledger_call_id == second.ledger_call_id
    assert [path for path, _ in seen] == ["/v1/messages/count_tokens", "/v1/messages"]
    with store.transaction(scope) as (session, actual_run):
        calls = session.scalars(select(AgentToolCall).where(
            AgentToolCall.run_id == scope.run_id,
        )).all()
        assert len(calls) == 2
        count = next(call for call in calls if call.tool == "model.count_tokens")
        model = next(call for call in calls if call.tool == "model")
        assert count.state == model.state == "completed"
        assert count.execution_binding == {
            "kind": "unbound", "dispatch": "anthropic-count-tokens/v1",
            "model_binding": model.execution_binding,
        }
        assert count.result == {"input_tokens": 900}
        assert count.reserved_tokens == count.charged_tokens == 0
        assert count.receipt_id is None
        assert count.provider_request_id == "synthetic-count-1"
        assert model.charged_tokens == actual_run.used_tokens == 37
        assert actual_run.held_tokens == 0
        assert model.cost_charged_micro_usd == 0
        assert model.result["context_budget"]["provider_counted_input_tokens"] == 900
        assert actual_run.versions["context_observations"]["main"]["actual_input_tokens"] == 30
