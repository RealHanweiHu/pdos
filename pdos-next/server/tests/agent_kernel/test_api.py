from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.activities import KernelActivities
from pdos_next.agent_kernel.api import ApiPorts, router
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.errors import DomainError
from pdos_next.models import Grant


def client(setup, *, binding_state=None, cancel_calls=None):
    calls = []

    async def start(ref):
        calls.append(("start", ref))

    async def signal(*args):
        calls.append(("signal", args))

    async def cancel(*args):
        if cancel_calls is not None:
            cancel_calls.append(args)
            return
        raise RuntimeError("Synthetic worker unavailable")

    app = FastAPI()

    @app.exception_handler(DomainError)
    async def failure(_, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(exc.payload(), status_code=exc.status)

    def binding(*_):
        if binding_state is not None and binding_state.get("unavailable"):
            raise DomainError("SOURCE_UNAVAILABLE", "Synthetic changed current binding")
        return SimpleNamespace(
            private_context=False,
            data_categories=("public",),
            customer_identities=(),
            read_sources=(),
            token_limit=(binding_state or {}).get("token_limit", 100000),
        )

    ports = ApiPorts(
        writer_for=lambda *_: setup.agent,
        binding_for=binding,
        start_workflow=start,
        signal_workflow=signal,
        cancel_workflow=cancel,
    )
    app.include_router(router(setup.engine, context_dependency=lambda: setup.ctx, ports=ports))
    return TestClient(app), calls


def test_run_returns_stable_work_id_and_missing_model_wait_has_zero_inference(setup):
    api, calls = client(setup)
    payload = {"goal": "Synthetic public research", "idempotency_key": "api:" + str(uuid4())}
    path = f"/v1/categories/{setup.category}/agent-runs"
    first = api.post(path, json=payload)
    assert first.status_code == 202
    second = api.post(path, json=payload)
    assert first.json() == second.json()
    ref = calls[0][1]
    assert set(ref) == {"tenant_id", "category_id", "actor_id", "requester_id", "subject_id"}
    assert "Synthetic public research" not in str(ref)
    result = KernelActivities(setup.engine).advance(ref)
    assert result["status"] == "waiting_input" and result["error_code"] == "SOURCE_UNAVAILABLE"
    read = api.get(path + "/" + first.json()["run_id"])
    assert read.json()["status"] == "waiting_input"
    stream = api.get(path + "/" + first.json()["run_id"] + "/events")
    assert [r["event"]["type"] for r in stream.json()["items"]] == [
        "accepted", "run_state", "model_unavailable"
    ]
    assert api.post(path, json={**payload, "private_context": True}).status_code == 422
    assert (
        api.get(f"/v1/categories/{uuid4()}/agent-runs/" + first.json()["run_id"]).status_code == 403
    )
    cancelled = api.post(path + "/" + first.json()["run_id"] + "/cancel")
    assert cancelled.json()["status"] == "cancelled" and cancelled.json()["held_tokens"] == 0
    assert cancelled.json()["workflow_cancel_pending"] is True
    with Session(setup.admin) as s:
        assert s.get(AgentRun, ref["subject_id"]).state == "cancelled"
    api.close()


def test_answer_signal_contains_only_committed_reference(setup):
    api, calls = client(setup)
    path = f"/v1/categories/{setup.category}/agent-runs"
    response = api.post(
        path, json={"goal": "Synthetic question", "idempotency_key": "api:" + str(uuid4())}
    ).json()
    ref = calls[0][1]
    KernelActivities(setup.engine).advance(ref)
    submitted = api.post(
        path + "/" + response["run_id"] + "/answers",
        json={"answers": {"question": "US"}, "idempotency_key": "answer:" + str(uuid4())},
    )
    assert submitted.status_code == 202
    assert calls[-1][0] == "signal" and calls[-1][1][-1] == submitted.json()["answer_ref"]
    assert "US" not in str(calls[-1])
    api.close()


def test_sse_replays_terminal_events_and_does_not_restart_inference(setup):
    api, calls = client(setup)
    path = f"/v1/categories/{setup.category}/agent-runs"
    created = api.post(
        path, json={"goal": "Synthetic streaming", "idempotency_key": "api:" + str(uuid4())}
    ).json()
    api.post(path + "/" + created["run_id"] + "/cancel")
    response = api.get(path + "/" + created["run_id"] + "/stream")
    assert response.status_code == 200 and "text/event-stream" in response.headers["content-type"]
    assert "event: process" in response.text and "event: end" in response.text
    assert "cancelled" in response.text and len(calls) == 1
    api.close()


def test_original_start_recovery_needs_current_read_without_new_binding_or_budget(setup):
    state = {}
    api, calls = client(setup, binding_state=state)
    path = f"/v1/categories/{setup.category}/agent-runs"
    payload = {"goal": "Synthetic exact original start", "idempotency_key": str(uuid4())}
    first = api.post(path, json=payload)
    assert first.status_code == 202
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(select(Grant).where(Grant.category_id == setup.category,
                                                  Grant.principal_id == setup.human))
        grant.can_write = False
    state["unavailable"] = True
    # Only a new Run resolves current execution binding; replay needs current read authority.
    assert api.post(path, json=payload).json() == first.json()
    assert api.post(path, json={**payload, "goal": "Different human goal"}).status_code == 409
    unavailable = api.post(path, json={**payload, "idempotency_key": str(uuid4())})
    assert unavailable.status_code == 409 and unavailable.json()["code"] == "SOURCE_UNAVAILABLE"
    assert len(calls) == 2 and calls[0][1] == calls[1][1]
    api.close()


def test_run_history_stable_cursor_and_other_requester_exclusion(setup):
    api, _ = client(setup)
    path = f"/v1/categories/{setup.category}/agent-runs"
    created = []
    for index in range(3):
        response = api.post(path, json={"goal": f"Synthetic history {index}",
                                       "idempotency_key": str(uuid4())})
        assert response.status_code == 202
        created.append(response.json()["run_id"])
    first = api.get(path + "?page_size=2").json()
    assert [row["run_id"] for row in first["items"]] == list(reversed(created[1:]))
    second = api.get(path + "?page_size=2&cursor=" + first["next_cursor"]).json()
    assert [row["run_id"] for row in second["items"]] == created[:1]
    assert second["next_cursor"] is None
    assert api.get(path + "?cursor=" + str(uuid4())).status_code == 403
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(select(Grant).where(Grant.category_id == setup.category,
                                                  Grant.principal_id == setup.human))
        session.delete(grant)
    assert api.get(path + "/" + created[0]).status_code == 403
    assert api.get(path).json()["items"] == []
    api.close()


@pytest.mark.parametrize("product_bound", [False, True])
def test_actual_default_bootstrap_binds_category_source_without_borrowing_agent_session(
    setup, product_bound
):
    from uuid import UUID

    from pdos_next.agent_kernel.models import AgentRun
    from pdos_next.agent_kernel.persistence import KernelStore
    from tests.agent_kernel.test_domain_adapter_transactions import fixture

    source = fixture(setup)
    path = f"/v1/categories/{setup.category}/agent-runs"
    payload = {"goal": "Synthetic actual default bootstrap",
               "idempotency_key": str(uuid4()),
               "product_id": str(setup.product) if product_bound else None,
               "sources": [{"artifact_id": source.arguments["artifact_id"],
                            "expected_revision": 1}]}
    response = setup.client.post(path, headers=setup.headers, json=payload)
    assert response.status_code == 202, response.text
    assert response.json()["execution_state"] == "durable_runtime_unavailable"
    identity = UUID(response.json()["run_id"])
    with Session(setup.admin) as session:
        row = session.get(AgentRun, identity)
        assert row.writer_id == setup.agent and row.requester_id == setup.human
        assert row.read_sources == [{"artifact_id": source.arguments["artifact_id"],
                                     "expected_revision": 1, "product_id": None}]
    bound = KernelStore(setup.engine).scope(tenant_id=setup.tenant,
        category_id=setup.category, writer_id=setup.agent, requester_id=setup.human,
        run_id=identity)
    assert bound.product_id == (setup.product if product_bound else None)
    assert setup.client.post(path, headers=setup.headers, json=payload).json() == response.json()
