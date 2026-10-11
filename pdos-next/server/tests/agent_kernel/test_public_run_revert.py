"""Real common HTTP owner with explicitly synthetic AI history; no model is called."""

from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel import persistence
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.models import Artifact, Audit, Claim, Confirmation, Consumption, Outbox, Receipt
from pdos_next.service import digest
from tests.agent_kernel.test_transactions import run


def history(setup, *, category_only=False, shared_source=False):
    product = None if category_only else setup.product
    store, scope = run(setup, product_id=product)
    artifact, claim, artifacts_receipt, claim_receipt = (uuid4() for _ in range(4))
    with Session(setup.admin) as s, s.begin():
        s.add(Artifact(
            id=artifact, tenant_id=setup.tenant, category_id=setup.category, product_id=product,
            owner_id=setup.human, title="Synthetic AI output",
            source_label="M2 public owner fixture", content="Synthetic pressure: 150 PSI",
            content_hash=digest("Synthetic pressure: 150 PSI"),
            visibility="category" if shared_source else "private",
        ))
        s.flush()
        if product:
            s.add(Claim(
                id=claim, tenant_id=setup.tenant, category_id=setup.category, product_id=product,
                artifact_id=artifact, source_revision=1, line=1, quote="150 PSI",
                statement="Synthetic output", nature="extracted", availability="known",
                visibility="private", human_owner_id=setup.human, writer_id=setup.agent,
            ))
            s.flush()
        entries = [(artifact, "artifact", "evidence.artifact.register", artifacts_receipt)]
        if product:
            entries.append((claim, "claim", "evidence.claim.record", claim_receipt))
        for target, kind, operation, identity in entries:
            s.add(Receipt(
                id=identity, tenant_id=setup.tenant, category_id=setup.category, product_id=product,
                command_id=uuid4(), actor_id=setup.agent, requester_id=setup.human,
                operation=operation, subject_type=kind, subject_id=target, subject_revision=1,
                visibility="category" if shared_source and kind == "artifact" else "private",
                request_digest=digest(str(uuid4())),
                intent_digest=digest(str(uuid4())), agent_run_id=scope.run_id,
                result={"id": str(target), "revision": 1, "status": "active"},
            ))
    with store.transaction(scope, lock=True) as (_, row):
        row.state, row.result = "completed", {"synthetic_history": True}
    return scope, artifact, claim if product else None


def preview(setup, scope):
    return setup.client.post(
        f"/v1/categories/{setup.category}/agent-runs/{scope.run_id}/revert-preview",
        headers=setup.headers,
    )


def test_actual_whole_run_preview_and_human_t1_command_revert_all_drafts_once(setup):
    scope, artifact, claim = history(setup)
    candidate = preview(setup, scope)
    assert candidate.status_code == 200
    command = candidate.json()["command"]
    assert command["payload"]["run_id"] == str(scope.run_id)
    assert len(candidate.json()["review"]["receipts"]) == 2
    path = f"/v1/categories/{setup.category}/commands"
    done = setup.client.post(path, headers=setup.headers, json=command)
    assert done.status_code == 200
    repeated = setup.client.post(path, headers=setup.headers, json=command)
    assert repeated.json() == done.json()
    with Session(setup.admin) as s:
        actual = s.get(AgentRun, scope.run_id)
        assert actual.state == "completed" and actual.result == {"synthetic_history": True}
        assert actual.reverted_at and actual.cancel_epoch == 1
        assert s.get(Artifact, artifact).status == "withdrawn"
        assert s.get(Claim, claim).status == "reverted"
        receipt = s.get(Receipt, actual.revert_receipt_id)
        assert receipt.actor_id == setup.human and receipt.agent_run_id is None
        assert s.scalar(
            select(func.count()).select_from(Audit).where(Audit.receipt_id == receipt.id)
        ) == 1
        assert s.scalar(
            select(func.count()).select_from(Outbox).where(Outbox.receipt_id == receipt.id)
        ) == 1


def test_category_only_run_reverts_category_artifact_through_public_human_owner(setup):
    scope, artifact, _ = history(setup, category_only=True)
    candidate = preview(setup, scope)
    assert candidate.status_code == 200
    done = setup.client.post(
        f"/v1/categories/{setup.category}/commands", headers=setup.headers,
        json=candidate.json()["command"],
    )
    assert done.status_code == 200
    with Session(setup.admin) as s:
        assert s.get(Artifact, artifact).status == "withdrawn"
        assert s.get(AgentRun, scope.run_id).reverted_at


def test_public_revert_refuses_external_consumption_and_changes_nothing(setup):
    scope, artifact, claim = history(setup)
    with Session(setup.admin) as s, s.begin():
        s.add(Consumption(
            tenant_id=setup.tenant, category_id=setup.category, product_id=setup.product,
            claim_id=claim, consumer_type="synthetic_next_step", consumer_id=uuid4(),
        ))
    denied = preview(setup, scope)
    assert denied.status_code == 409
    with Session(setup.admin) as s:
        assert s.get(Artifact, artifact).status == "active"
        assert s.get(Claim, claim).status == "active"
        assert s.get(AgentRun, scope.run_id).reverted_at is None


@pytest.mark.parametrize("stage", ["finish", "outbox"])
def test_public_revert_tail_failure_rolls_back_every_business_and_technical_effect(
    setup, monkeypatch, stage
):
    scope, artifact, claim = history(setup)
    candidate = preview(setup, scope)
    assert candidate.status_code == 200
    command = candidate.json()["command"]
    original = persistence.finish_run_revert

    def failed_finish(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic finish tail failure")

    def failed_outbox(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO outbox_events"):
            raise RuntimeError("synthetic outbox tail failure")

    if stage == "finish":
        monkeypatch.setattr(persistence, "finish_run_revert", failed_finish)
    else:
        event.listen(setup.engine, "before_cursor_execute", failed_outbox)
    try:
        with pytest.raises(RuntimeError, match=f"synthetic {stage} tail failure"):
            setup.client.post(
                f"/v1/categories/{setup.category}/commands", headers=setup.headers, json=command
            )
    finally:
        if stage == "outbox":
            event.remove(setup.engine, "before_cursor_execute", failed_outbox)
    with Session(setup.admin) as s:
        assert s.get(Artifact, artifact).status == "active"
        assert s.get(Claim, claim).status == "active"
        actual = s.get(AgentRun, scope.run_id)
        assert actual.reverted_at is None and actual.cancel_epoch == 0
        confirmation = s.scalar(
            select(Confirmation).where(Confirmation.subject_id == scope.run_id)
        )
        assert confirmation.consumed is False
        for model, count in ((Receipt, 2), (Audit, 0), (Outbox, 0)):
            assert s.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == setup.tenant)
            ) == count


def test_private_external_definition_consumption_is_opaque_but_blocks_whole_run(setup):
    scope, artifact, claim = history(setup, shared_source=True)
    reference = {
        "artifact_id": str(artifact), "expected_revision": 1, "line": 1, "quote": "150 PSI"
    }
    saved = setup.client.post(
        f"/v1/categories/{setup.category}/commands",
        headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"},
        json={
            "command_id": str(uuid4()), "idempotency_key": "private-consumer:" + str(uuid4()),
            "operation": "product.definition.draft", "category_id": str(setup.category),
            "product_id": str(setup.product), "expected_revision": 1,
            "source_read_set": [{"artifact_id": str(artifact), "expected_revision": 1}],
            "payload": {
                "title": "Synthetic private consumer", "purpose": "M2 private downstream fixture",
                "visibility": "private", "use_cases": ["Synthetic verification"],
                "sources": [reference], "specs": [], "change_reason": "Explicit synthetic consumer",
            },
        },
    )
    assert saved.status_code == 200
    from tests.agent_kernel.test_transactions import human_session

    with human_session(setup) as s:
        assert s.get(DefinitionRevision, saved.json()["subject_id"]) is None
    denied = preview(setup, scope)
    assert denied.status_code == 409
    assert "Synthetic private consumer" not in denied.text
    with Session(setup.admin) as s:
        assert s.get(Artifact, artifact).status == "active"
        assert s.get(Claim, claim).status == "active"
        assert s.get(AgentRun, scope.run_id).reverted_at is None
