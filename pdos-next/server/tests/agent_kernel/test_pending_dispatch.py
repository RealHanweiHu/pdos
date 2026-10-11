"""Actual dispatch role sees only committed Run UUID references, without inference."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from pdos_next.agent_kernel.temporal_port import dispatch_pending_runs
from pdos_next.database import tenant_session


def test_pending_dispatch_recovers_committed_start_and_keeps_roles_and_tenant_scope(setup):
    path = f"/v1/categories/{setup.category}/agent-runs"
    response = setup.client.post(
        path,
        headers=setup.headers,
        json={"goal": "Synthetic committed offline dispatch", "idempotency_key": str(uuid4())},
    )
    assert response.status_code == 202, response.text
    identity = response.json()["run_id"]

    class Port:
        def __init__(self):
            self.calls = []
            self.unavailable = True

        async def start(self, reference):
            if self.unavailable:
                raise RuntimeError("Synthetic offline Temporal")
            self.calls.append(reference)

    port = Port()
    failed = asyncio.run(dispatch_pending_runs(setup.dispatch, setup.tenant, port))
    assert failed == {"delivered": 0, "unavailable": 1}
    port.unavailable = False
    assert asyncio.run(dispatch_pending_runs(setup.dispatch, setup.tenant, port)) == {
        "delivered": 1,
        "unavailable": 0,
    }
    assert port.calls == [
        {
            "tenant_id": str(setup.tenant),
            "category_id": str(setup.category),
            "actor_id": str(setup.human),
            "requester_id": str(setup.human),
            "subject_id": identity,
        }
    ]
    assert asyncio.run(dispatch_pending_runs(setup.dispatch, uuid4(), port)) == {
        "delivered": 0,
        "unavailable": 0,
    }
    with pytest.raises(DBAPIError):
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session:
            session.execute(
                text("SELECT * FROM kernel_pending_runs(:tenant,100)"), {"tenant": setup.tenant}
            )
    # Delivery does not run a model or manufacture a completed result.
    assert (
        setup.client.get(path + "/" + identity, headers=setup.headers).json()["status"] == "queued"
    )
