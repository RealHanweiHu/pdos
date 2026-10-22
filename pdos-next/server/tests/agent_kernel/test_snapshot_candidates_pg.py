"""Snapshot candidate pages use actual read proofs and common receipt recovery."""

import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import execution_key
from pdos_next.agent_kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.agent_kernel.models import AgentEvent, AgentRun, PublicWebSnapshot
from pdos_next.agent_kernel.research_adapter import ResearchArtifacts
from pdos_next.agent_kernel.research_read_ledger import page_result
from pdos_next.models import Confirmation, Receipt, now
from pdos_next.research.types import ReadPage, Snapshot
from tests.agent_kernel.test_model_configuration_transactions import submit
from tests.agent_kernel.test_read_proof_transactions import read_fixture
from tests.agent_kernel.test_snapshot_proof_transactions import model_for


def fixture(setup, tmp_path, *, completed=True):
    f = read_fixture(setup)
    artifacts = ResearchArtifacts(tmp_path, current=f.store.current)
    text = "Synthetic retained public evidence."
    snapshot = Snapshot(
        uuid4(),
        "https://synthetic.test/spec",
        "https://synthetic.test/spec",
        "合成研究来源",
        "source",
        now(),
        text,
        hashlib.sha256(text.encode()).hexdigest(),
        "synthetic",
        "unknown",
    )
    artifacts.save_snapshot(f.scope, snapshot)
    arguments = {"url": snapshot.url, "cursor": 0}
    source = model_for(f, "research.read", arguments, isolation="research")
    f.host.read_callback(
        f.scope.child("research"),
        f.registry.get("research.read"),
        arguments,
        execution_key(f.scope.run_id, source.model_call_id, 0),
        source=source,
        callback=lambda *_: page_result(ReadPage(snapshot, "chars:0:35", text, None)),
    )
    arguments = {"snapshot_id": str(snapshot.id)}
    source = model_for(f, "research.snapshot.register", arguments)
    owner = Bootstrap(setup.engine, ports=RuntimePorts(research_artifacts=artifacts))
    owner.route = lambda *_: f.route
    prepared = owner.prepare_candidate(
        f.scope,
        f.registry.get("research.snapshot.register"),
        arguments,
        execution_key(f.scope.run_id, source.model_call_id, 0),
    )
    if completed:
        with Session(setup.admin) as session, session.begin():
            session.get(AgentRun, f.scope.run_id).state = "completed"
    f.prepared, f.snapshot, f.artifacts = prepared, snapshot, artifacts
    return f


def page(setup, f):
    response = setup.client.get(
        f"/v1/categories/{setup.category}/agent-runs/{f.scope.run_id}/candidates",
        headers=setup.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["items"][0]


def counts(setup):
    with Session(setup.admin) as session:
        return tuple(
            session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == setup.tenant)
            )
            for model in (AgentEvent, Receipt, PublicWebSnapshot, Confirmation)
        )


def test_snapshot_page_is_read_only_and_saved_receipt_survives_missing_work_volume(setup, tmp_path):
    f = fixture(setup, tmp_path)
    before = counts(setup)
    current = page(setup, f)
    assert current["state"] == "pending" and current["command"] == f.prepared["command"]
    assert current["summary"]["title"] == f.snapshot.title
    assert f.snapshot.markdown not in str(current) and counts(setup) == before
    saved, command = submit(setup, setup.client, current["command"])
    assert saved.status_code == 200, saved.text
    f.artifacts._path(f.scope, f.snapshot.id).unlink()
    restored = page(setup, f)
    assert restored["state"] == "adopted" and restored["receipt"]["id"] == saved.json()["id"]
    assert restored["command"] is None
    after = counts(setup)
    repeated, _ = submit(setup, setup.client, command, preview=False)
    assert repeated.json()["id"] == saved.json()["id"] and counts(setup) == after


@pytest.mark.parametrize("state", ["missing", "cancelled", "failed"])
def test_unusable_snapshot_is_not_exposed_as_a_fresh_confirmation(setup, tmp_path, state):
    f = fixture(setup, tmp_path, completed=state == "missing")
    if state == "missing":
        f.artifacts._path(f.scope, f.snapshot.id).unlink()
    elif state == "cancelled":
        from pdos_next.agent_kernel.persistence import cancel_run
        from tests.agent_kernel.test_transactions import human_session

        with human_session(setup) as session:
            cancel_run(session, setup.ctx, f.scope.run_id)
    else:
        with f.store.transaction(f.scope, lock=True) as (_, row):
            row.state = "failed"
    current = page(setup, f)
    assert current["state"] == ("cancelled" if state == "cancelled" else "unavailable")
    assert current["command"] is None
