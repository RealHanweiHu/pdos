"""Actual stored model candidate admission, Human proof, recovery and whole-run undo."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import execution_key
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.models import AgentEvent, AgentRun, TenantSkillEnablement
from pdos_next.agent_kernel.persistence import cancel_run
from pdos_next.models import Claim, Confirmation, Receipt
from tests.agent_kernel.test_domain_adapter_transactions import counts, fixture
from tests.agent_kernel.test_transactions import human_session


def candidate(setup):
    f = fixture(setup)
    with Session(setup.admin) as s, s.begin():
        s.get(TenantSkillEnablement, f.qualification.id).qualification_revoked = True
    bootstrap = Bootstrap(setup.engine)
    bootstrap.route = lambda *_: f.route  # Only the synthetic stored-model route test port.
    prepared = bootstrap.prepare_candidate(
        f.scope, f.spec, f.arguments, execution_key(f.scope.run_id, f.model.id, 0)
    )
    path = f"/v1/categories/{setup.category}/commands"
    preview = setup.client.post(path + "/preview", headers=setup.headers, json=prepared["command"])
    assert preview.status_code == 200, preview.text
    return f, prepared, preview.json()["command"], path


def test_claim_candidate_cannot_be_changed_or_confirmed_after_cancel(setup):
    f, _, command, path = candidate(setup)
    before = counts(setup)
    tampered = {**command, "payload": {**command["payload"], "statement": "Different AI content"}}
    rejected = setup.client.post(path, headers=setup.headers, json=tampered)
    assert rejected.status_code == 409 and rejected.json()["code"] == "DUPLICATE_INTENT_CONFLICT"
    assert counts(setup) == before
    with human_session(setup) as s:
        cancel_run(s, setup.ctx, f.scope.run_id)
    rejected = setup.client.post(path, headers=setup.headers, json=command)
    assert rejected.status_code == 403 and rejected.json()["code"] == "FORBIDDEN_SCOPE"
    assert counts(setup) == before


def test_claim_candidate_t1_preserves_writer_and_all_or_none_run_revert(setup):
    f, prepared, command, path = candidate(setup)
    result = setup.client.post(path, headers=setup.headers, json=command)
    assert result.status_code == 200, result.text
    receipt_id = UUID(result.json()["id"])
    with Session(setup.admin) as s:
        receipt = s.get(Receipt, receipt_id)
        assert receipt.actor_id == setup.human and receipt.agent_run_id == f.scope.run_id
        assert s.get(Claim, receipt.subject_id).writer_id == setup.agent
        adopted = s.scalars(select(AgentEvent).where(AgentEvent.run_id == f.scope.run_id)).all()
        assert any(
            e.body.get("type") == "claim_candidate_adopted"
            and e.body.get("prepared_event_id") == prepared["event_id"]
            for e in adopted
        )
    revert = {
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": "ai.run.revert",
        "category_id": str(setup.category),
        "product_id": str(setup.product),
        "expected_revision": 1,
        "source_read_set": [],
        "payload": {"run_id": str(f.scope.run_id)},
    }
    preview = setup.client.post(path + "/preview", headers=setup.headers, json=revert)
    assert preview.status_code == 200, preview.text
    assert [r["id"] for r in preview.json()["review"]["receipts"]] == [str(receipt_id)]
    result = setup.client.post(path, headers=setup.headers, json=preview.json()["command"])
    assert result.status_code == 200, result.text
    with Session(setup.admin) as s:
        assert s.get(Claim, receipt.subject_id).status == "reverted"
        assert s.get(AgentRun, f.scope.run_id).reverted_at is not None


def test_claim_adoption_terminal_failure_keeps_proof_and_no_partial_result(setup):
    _, _, command, path = candidate(setup)
    before = counts(setup)

    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO outbox_events"):
            raise RuntimeError("synthetic candidate tail failure")

    event.listen(setup.engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="synthetic candidate tail failure"):
            setup.client.post(path, headers=setup.headers, json=command)
    finally:
        event.remove(setup.engine, "before_cursor_execute", fail)
    assert counts(setup) == before
    with Session(setup.admin) as s:
        assert not s.scalar(
            select(Confirmation.consumed).where(Confirmation.tenant_id == setup.tenant)
        )
    saved = setup.client.post(path, headers=setup.headers, json=command)
    assert saved.status_code == 200, saved.text
