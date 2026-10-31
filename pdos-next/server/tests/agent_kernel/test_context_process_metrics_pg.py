"""Actual PG/provider-ledger -> original HTTP process projection; root runs centrally."""

import json
from dataclasses import replace
from datetime import timedelta

from pdos_agent_runtime.graph import registered_graph_context
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.context_observability import record_call
from pdos_next.agent_kernel.gateway import AgentGateway
from pdos_next.agent_kernel.types import ModelTurn
from pdos_next.models import Grant, now
from pdos_next.providers.types import ProviderUsage
from tests.agent_kernel.test_gateway import Client, configured_route
from tests.agent_kernel.test_transactions import run


def test_actual_model_ledger_metrics_are_readable_through_existing_process_and_current_rls(setup):
    store, scope = run(setup)
    route = replace(configured_route(), context_window_tokens=200_000)
    client = Client(lambda _: ModelTurn("synthetic private provider text", usage=ProviderUsage(
        200, 10, 80, 20,
    ), structured={"ok": True}))
    gateway = AgentGateway(store, cost_required=False, route_for=lambda _: route, client=client)
    messages = [{"role": "user", "content": json.dumps({"goal": "synthetic private goal",
        "context": {"work_state": {"revision": 4, "constraints": [{"text": "PRIVATE constraint"}]},
                    "conversation": {"turns": []}}})}]
    with registered_graph_context("xiaopai"):
        turn = gateway.turn(scope, system="frozen synthetic system", messages=messages,
                            tools=[], output_schema={"type": "object"})
    first = record_call(store, scope, turn, messages)
    assert record_call(store, scope, turn, messages) == first and client.calls == 1
    path = f"/v1/categories/{setup.category}/agent-runs/{scope.run_id}/process?page_size=1"
    response = setup.client.get(path, headers=setup.headers)
    assert response.status_code == 200, response.text
    step = response.json()["steps"][-1]
    assert step["kind"] == "context_observed"
    metrics = step["context_metrics"]
    assert metrics["window"] == 200_000 and metrics["actual_input_tokens"] == 200
    assert metrics["cache"]["read_tokens"] == 80 and metrics["cache"]["read_hit_ratio"] == .4
    assert metrics["segments"]["system"]["actual_tokens"] is None
    assert metrics["work_state"]["revision"] == 4
    for private in [
        "synthetic private provider text", "synthetic private goal", "PRIVATE constraint",
    ]:
        assert private not in response.text
    assert setup.client.get(path, headers={
        "Authorization": "Bearer " + setup.tokens[setup.peer],
    }).status_code == 403
    with Session(setup.admin) as session, session.begin():
        session.scalar(select(Grant).where(Grant.category_id == setup.category,
                                          Grant.principal_id == setup.human)).expires_at = (
            now() - timedelta(seconds=1)
        )
    assert setup.client.get(path, headers=setup.headers).status_code == 403
    assert client.calls == 1  # GET/replay cannot dispatch the provider or a write.
