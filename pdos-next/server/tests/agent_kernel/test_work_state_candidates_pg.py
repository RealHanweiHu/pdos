"""Actual four-family ledgers feed readonly work state; no provider or network calls."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import execution_key
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.work_state_models import AgentWorkState
from pdos_next.models import Grant, now
from tests.agent_kernel.test_category_candidate_transactions import adopted, personal_fixture
from tests.agent_kernel.test_model_configuration_transactions import submit
from tests.agent_kernel.test_read_proof_transactions import read_fixture
from tests.agent_kernel.test_run_continuation import scope, start
from tests.agent_kernel.test_snapshot_candidates_pg import fixture as snapshot_fixture
from tests.agent_kernel.test_snapshot_proof_transactions import model_for
from tests.products.test_definition_item_commands_pg import confirmed
from tests.products.test_platform_links_pg import payload


def finish(f):
    f.store.finish(f.scope, {"status": "completed", "summary": "合成候选待本人核对。",
                            "questions": [], "result": {}})


def read(setup, f, *, personal=False):
    root = "/v1/personal" if personal else f"/v1/categories/{setup.category}"
    response = setup.client.get(root + f"/agent-sessions/{f.scope.session_id}/work-state",
                                headers=setup.headers)
    assert response.status_code == 200, response.text
    return response.json()


def candidate(value, identity):
    row = next(item for item in value["candidates"] if item["event_id"] == identity)
    assert set(row) == {"event_id", "run_id", "kind", "operation", "state", "receipt_id"}
    return row


def count(setup, f):
    with Session(setup.admin) as session:
        return session.scalar(select(func.count()).select_from(AgentWorkState).where(
            AgentWorkState.session_id == f.scope.session_id,
        ))


def test_domain_current_receipt_changes_readonly_projection_not_run_frozen_snapshot(setup):
    # Reuse the native ordinary conversation ledger, not the page-only platform fixture.
    f = read_fixture(setup, skill_key="derivative_diff")
    owner = Bootstrap(setup.engine)
    owner.route = lambda *_: f.route
    arguments = payload(setup)
    source = model_for(f, "platform.link.create", arguments)
    prepared = owner.prepare_candidate(
        f.scope, f.registry.get("platform.link.create"), arguments,
        execution_key(f.scope.run_id, source.model_call_id, 0),
    )
    finish(f)
    before = read(setup, f)
    pending = candidate(before, prepared["event_id"])
    assert pending["kind"] == "domain" and pending["state"] == "pending"
    assert pending["receipt_id"] is None and count(setup, f) == 1
    child, _ = start(setup, continue_from_run_id=str(f.scope.run_id), goal="继续核对候选。")
    child_scope = scope(setup, child)
    frozen = owner.project_context(child_scope, "继续核对候选。")["work_state"]
    assert candidate(frozen, prepared["event_id"])["state"] == "pending"
    receipt, command = confirmed(setup, prepared["command"])
    after = read(setup, f)
    assert after["revision"] == before["revision"] and count(setup, f) == 1
    current = candidate(after, prepared["event_id"])
    assert current == {**pending, "state": "adopted", "receipt_id": receipt["id"]}
    replay = setup.client.post(f"/v1/categories/{setup.category}/commands",
                               headers=setup.headers, json=command)
    assert replay.status_code == 200 and replay.json()["id"] == receipt["id"]
    assert owner.project_context(child_scope, "继续核对候选。")["work_state"] == frozen
    owner.check_conversation(child_scope)
    f.store.finish(child_scope, {"status": "completed", "summary": "已核对真实回执。",
                                "questions": [], "result": {}})
    grandchild, _ = start(setup, continue_from_run_id=str(child))
    next_state = owner.project_context(scope(setup, grandchild), "继续")["work_state"]
    assert candidate(next_state, prepared["event_id"])["receipt_id"] == receipt["id"]
    assert count(setup, f) == 2
    # Actual Grant revocation removes the whole owned scope; no old metadata is echoed.
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(select(Grant).where(
            Grant.category_id == setup.category, Grant.principal_id == setup.human,
        ))
        grant.expires_at = now() - timedelta(seconds=1)
    denied = setup.client.get(
        f"/v1/categories/{setup.category}/agent-sessions/{f.scope.session_id}/work-state",
        headers=setup.headers,
    )
    assert denied.status_code in {403, 404}
    assert prepared["event_id"] not in denied.text and receipt["id"] not in denied.text


def test_snapshot_receipt_is_projected_from_native_ledger_after_work_volume_loss(setup, tmp_path):
    f = snapshot_fixture(setup, tmp_path, completed=False)
    finish(f)
    pending = candidate(read(setup, f), f.prepared["event_id"])
    assert pending["kind"] == "snapshot" and pending["state"] == "pending"
    saved, command = submit(setup, setup.client, f.prepared["command"])
    assert saved.status_code == 200, saved.text
    f.artifacts._path(f.scope, f.snapshot.id).unlink()
    after = read(setup, f)
    current = candidate(after, f.prepared["event_id"])
    assert current["state"] == "adopted" and current["receipt_id"] == saved.json()["id"]
    assert f.snapshot.markdown not in str(after) and count(setup, f) == 1
    repeated, _ = submit(setup, setup.client, command, preview=False)
    assert repeated.json()["id"] == current["receipt_id"] and count(setup, f) == 1


def test_personal_category_requires_actual_receipt_and_current_created_category_grant(
    setup, tmp_path,
):
    f = personal_fixture(setup, tmp_path)
    finish(f)
    before = read(setup, f, personal=True)
    pending = candidate(before, f.candidate["event_id"])
    assert pending["kind"] == "category" and pending["state"] == "pending"
    receipt, _ = adopted(setup, f)
    after = read(setup, f, personal=True)
    assert candidate(after, f.candidate["event_id"]) == {
        **pending, "state": "adopted", "receipt_id": receipt["id"],
    }
    assert after["revision"] == before["revision"] and count(setup, f) == 1
    with Session(setup.admin) as session, session.begin():
        created = UUID(receipt["subject_id"])
        assert session.scalar(select(Grant.id).where(
            Grant.category_id == created, Grant.principal_id == setup.agent,
        )) is None
        session.scalar(select(Grant).where(
            Grant.category_id == created, Grant.principal_id == setup.human,
        )).expires_at = now() - timedelta(seconds=1)
    hidden = candidate(read(setup, f, personal=True), f.candidate["event_id"])
    assert hidden["state"] == "unavailable" and hidden["receipt_id"] is None
    assert hidden["operation"] is None and count(setup, f) == 1
    with Session(setup.admin) as session:
        assert session.get(AgentRun, f.scope.run_id).category_id is None
