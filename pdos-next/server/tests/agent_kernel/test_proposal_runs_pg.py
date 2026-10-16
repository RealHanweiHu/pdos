"""Actual proposal-bound runs and current read scope; no provider calls."""

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.models import Grant
from tests.preproject.test_g0 import create


def start(setup, proposal_id=None):
    body = {"goal": "Synthetic proposal draft and gaps", "idempotency_key": str(uuid4())}
    if proposal_id:
        body["proposal_id"] = proposal_id
    path = f"/v1/categories/{setup.category}/agent-runs"
    response = setup.client.post(path, headers=setup.headers, json=body)
    assert response.status_code == 202, response.text
    return response.json()["run_id"], body


def test_history_and_replay_use_actual_proposal_scope(setup):
    first, _ = create(setup, {"title": "Synthetic proposal one", "entry_kind": "new_product"})
    other, _ = create(setup, {"title": "Synthetic proposal two", "entry_kind": "new_product"})
    a, body = start(setup, first)
    b, _ = start(setup, first)
    c, _ = start(setup, other)
    start(setup)
    path = f"/v1/categories/{setup.category}/agent-runs"
    page = setup.client.get(
        path, headers=setup.headers, params={"proposal_id": first, "page_size": 1}
    ).json()
    assert [(r["run_id"], r["proposal_id"]) for r in page["items"]] == [(b, first)]
    tail = setup.client.get(
        path, headers=setup.headers, params={"proposal_id": first, "cursor": page["next_cursor"]}
    ).json()
    assert [r["run_id"] for r in tail["items"]] == [a] and tail["next_cursor"] is None
    assert (
        setup.client.get(
            path, headers=setup.headers, params={"proposal_id": first, "cursor": c}
        ).status_code
        == 403
    )
    detail = setup.client.get(path + "/" + a, headers=setup.headers).json()
    assert detail["proposal_id"] == first and detail["product_id"] is None
    repeat = setup.client.post(path, headers=setup.headers, json=body)
    assert repeat.status_code == 202 and repeat.json()["run_id"] == a
    with Session(setup.admin) as session:
        row = session.get(AgentRun, UUID(a))
        assert row.proposal_id == UUID(first) and row.private_context
        assert row.requester_id == setup.human and row.writer_id == setup.agent
        assert (
            session.scalar(
                select(func.count()).select_from(AgentRun).where(AgentRun.tenant_id == setup.tenant)
            )
            == 4
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgentToolCall)
                .where(AgentToolCall.tenant_id == setup.tenant)
            )
            == 0
        )


def test_proposal_history_needs_current_audience_and_category_entry(setup):
    identity, _ = create(
        setup, {"title": "Synthetic private proposal", "entry_kind": "new_product"}
    )
    run, _ = start(setup, identity)
    path = f"/v1/categories/{setup.category}/agent-runs"
    peer = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    assert setup.client.get(path, headers=peer, params={"proposal_id": identity}).status_code == 404
    assert (
        setup.client.get(
            "/v1/personal/agent-runs", headers=setup.headers, params={"proposal_id": identity}
        ).status_code
        == 403
    )
    assert (
        setup.client.get(path, headers=setup.headers, params={"proposal_id": "invalid"}).status_code
        == 422
    )
    with Session(setup.admin) as session, session.begin():
        session.delete(
            session.scalar(
                select(Grant).where(
                    Grant.category_id == setup.category, Grant.principal_id == setup.human
                )
            )
        )
    for suffix in ("/" + run, "/" + run + "/events", "/" + run + "/candidates"):
        assert setup.client.get(path + suffix, headers=setup.headers).status_code == 403
    assert (
        setup.client.get(path, headers=setup.headers, params={"proposal_id": identity}).status_code
        == 403
    )
