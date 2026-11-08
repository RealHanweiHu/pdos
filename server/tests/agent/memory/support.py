"""Shared helpers for M1 memory tests: actual Runs, actual finish, no provider calls."""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.persistence import KernelStore
from pdos_next.agent.memory.models import MemoryEpisode


def runs_path(setup, *, personal=False):
    return "/v1/personal/agent-runs" if personal else f"/v1/categories/{setup.category}/agent-runs"


def start(setup, *, personal=False, headers=None, goal="比较三家气泵供应商的报价和交期", **body):
    response = setup.client.post(
        runs_path(setup, personal=personal), headers=headers or setup.headers,
        json={"goal": goal, "idempotency_key": str(uuid4()), **body},
    )
    assert response.status_code == 202, response.text
    return UUID(response.json()["run_id"]), response.json()


def scope(setup, identity, *, personal=False, requester=None):
    return KernelStore(setup.engine).scope(
        tenant_id=setup.tenant, requester_id=requester or setup.human, writer_id=setup.agent,
        category_id=None if personal else setup.category, run_id=identity,
    )


def finish(setup, identity, *, personal=False, requester=None, status="completed",
           unfinished=("核对交期单位",)):
    result = {
        "status": status,
        "summary": "合成结果：已比较报价，交期仍待核对。",
        "questions": [],
        "unfinished": list(unfinished),
        "result": {"context_proposals": {"constraints": []}},
    }
    KernelStore(setup.engine).finish(
        scope(setup, identity, personal=personal, requester=requester), result,
    )
    return result


def episode(setup, run_id):
    with Session(setup.admin) as session:
        return session.scalar(select(MemoryEpisode).where(MemoryEpisode.run_id == run_id))
