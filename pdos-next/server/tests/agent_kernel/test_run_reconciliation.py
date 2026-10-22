"""Actual technical outcome closure and HTTP owner/admin scopes in marked pdos_test."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.activities import KernelActivities
from pdos_next.agent_kernel.models import (
    AgentEvent,
    AgentInput,
    AgentRun,
    AgentToolCall,
    TenantAdministrator,
    ValidationBudget,
)
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.run_reconciliation import finalize, mark_required
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Claim, Receipt, RequestKey
from pdos_next.service import digest
from tests.agent_kernel.test_cost_budget import rate, wallet
from tests.agent_kernel.test_public_run_revert import claim_ledger
from tests.agent_kernel.test_revert import receipt
from tests.agent_kernel.test_skill_management import promote
from tests.agent_kernel.test_transactions import run


def lost(setup, *, admin=True, waiting=True):
    if admin:
        promote(setup)
    budget = wallet(setup)
    store, scope = run(setup, validation_budget_id=budget, token_limit=500000)
    card = rate()
    charge = card.reserve(200, 100)
    call, _ = store.claim(
        scope,
        "synthetic-lost-model",
        "model",
        {},
        reservation=300,
        cost_lease=(charge, 200, 100, card.snapshot()),
    )
    with store.transaction(scope, lock=True) as (_, row):
        row.state = "waiting_input" if waiting else "running"
        row.error_code = "EXTERNAL_OUTCOME_UNKNOWN" if waiting else None
    if waiting:
        mark_required(store, scope)
    return SimpleNamespace(store=store, scope=scope, call=call, budget=budget, charge=charge)


def path(setup, f):
    return f"/v1/categories/{setup.category}/agent-runs/{f.scope.run_id}/reconciliation"


def post(setup, f, **body):
    return setup.client.post(
        path(setup, f), headers=setup.headers, json={"expected_cancel_epoch": 0, **body}
    )


def reference(setup, f):
    return {
        "tenant_id": str(setup.tenant),
        "category_id": str(setup.category),
        "actor_id": str(setup.human),
        "requester_id": str(setup.human),
        "subject_id": str(f.scope.run_id),
    }


def test_admin_http_finalizes_unknown_once_releases_slots_and_keeps_bounded_cost(setup):
    f = lost(setup)
    page = setup.client.get(path(setup, f), headers=setup.headers)
    assert page.status_code == 200, page.text
    assert page.json()["required"] and page.json()["can_finalize"]
    assert page.json()["automatic_after"] and page.json()["held_tokens"] == 300
    first = post(setup, f)
    assert first.status_code == 200, first.text
    value = first.json()
    assert value["status"] == "failed" and value["reconciliation"]["failed_call_count"] == 1
    assert value["reconciliation"]["estimated_micro_usd"] == f.charge
    assert value["reconciliation"]["held_tokens"] == 0
    again = post(setup, f)
    assert again.status_code == 200 and again.json()["reconciliation"] == value["reconciliation"]
    with Session(setup.admin) as session:
        row, call, budget = (
            session.get(AgentRun, f.scope.run_id),
            session.get(AgentToolCall, f.call),
            session.get(ValidationBudget, f.budget),
        )
        assert (
            row.state == "failed"
            and row.cancel_epoch == 1
            and row.held_tokens == 0
            and row.used_tokens == 300
        )
        assert call.state == "failed" and call.cost_state == "estimated_unknown"
        assert budget.held_micro_usd == budget.held_input_tokens == budget.held_output_tokens == 0
        assert (
            budget.spent_micro_usd == f.charge
            and budget.used_input_tokens == 200
            and budget.used_output_tokens == 100
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgentEvent)
                .where(
                    AgentEvent.run_id == row.id, AgentEvent.body["type"].astext == "run_reconciled"
                )
            )
            == 1
        )
    with pytest.raises(DomainError):
        f.store.claim(f.scope, "must-not-advance-old-run", "model", {})
    new_store, new_scope = run(setup, validation_budget_id=f.budget, token_limit=500000)
    assert new_scope.run_id != f.scope.run_id
    new_call, _ = new_store.claim(new_scope, "new-request-read", "category.read", {})
    new_store.settle(new_scope, new_call, result={"new_request_allowed": True})


def test_admin_closure_notifies_the_existing_two_argument_workflow_cancel_port(setup):
    from tests.agent_kernel.test_api import client
    f = lost(setup)
    calls = []
    api, _ = client(setup, cancel_calls=calls)
    response = api.post(path(setup, f), json={"expected_cancel_epoch": 0})
    assert response.status_code == 200
    assert calls == [(setup.tenant, f.scope.run_id)]
    assert "workflow_cleanup_pending" not in response.json()
    api.close()


def test_owner_read_scope_and_admin_revocation_are_current_but_system_cleanup_still_works(setup):
    f = lost(setup)
    denied = setup.client.get(
        path(setup, f), headers={"Authorization": "Bearer " + setup.tokens[setup.peer]}
    )
    assert denied.status_code == 403
    with Session(setup.admin) as session, session.begin():
        session.scalar(
            select(TenantAdministrator).where(TenantAdministrator.tenant_id == setup.tenant)
        ).active = False
    assert post(setup, f).status_code == 403
    result = KernelActivities(setup.engine, technical_engine=setup.dispatch).reconcile(
        reference(setup, f)
    )
    assert result["status"] == "failed" and result["reconciliation"]["mode"] == "automatic"
    assert result["reconciliation"]["initiated_by"] is None


def test_stale_epoch_and_client_system_flags_cannot_close_running_or_unknown_work(setup):
    f = lost(setup)
    assert post(setup, f, expected_cancel_epoch=9).status_code == 409
    assert post(setup, f, automatic=True).status_code == 422
    with Session(setup.admin) as session:
        assert session.get(AgentRun, f.scope.run_id).cancel_epoch == 0


def test_normal_questions_are_preserved_and_unknown_outcome_cannot_be_resumed_by_answers(setup):
    f = lost(setup)
    answers = setup.client.post(
        f"/v1/categories/{setup.category}/agent-runs/{f.scope.run_id}/answers",
        headers=setup.headers,
        json={"answers": {"retry": True}, "idempotency_key": str(uuid4())},
    )
    assert answers.status_code == 409
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgentInput)
                .where(AgentInput.run_id == f.scope.run_id)
            )
            == 0
        )
    with f.store.transaction(f.scope, lock=True) as (_, row):
        row.error_code = None
    page = setup.client.get(path(setup, f), headers=setup.headers)
    assert not page.json()["required"] and post(setup, f).status_code == 409


def test_current_actual_claim_receipt_is_retained_and_whole_goal_is_not_falsely_completed(setup):
    promote(setup)
    artifact = uuid4()
    with tenant_session(
        setup.admin,
        setup.tenant,
        actor_id=setup.agent,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        session.add(
            Artifact(
                id=artifact,
                tenant_id=setup.tenant,
                category_id=setup.category,
                product_id=setup.product,
                owner_id=setup.human,
                title="Synthetic current source",
                source_label="Synthetic only",
                content="Synthetic pressure: 150 PSI",
                content_hash=digest("Synthetic pressure: 150 PSI"),
                visibility="category",
            )
        )
    actual = claim_ledger(setup, artifact)
    from pdos_next.agent_kernel.bindings import execution_key

    saved = actual.adapter.execute(
        actual.scope,
        actual.spec.name,
        actual.arguments,
        execution_key(actual.scope.run_id, actual.model.id, 0),
        source=actual.source,
    )
    store = KernelStore(setup.engine)
    lost_id, _ = store.claim(actual.scope, "after-real-claim", "model", {}, reservation=100)
    with store.transaction(actual.scope, lock=True) as (_, row):
        row.state, row.error_code = "waiting_input", "EXTERNAL_OUTCOME_UNKNOWN"
    f = SimpleNamespace(scope=actual.scope)
    result = post(setup, f)
    assert result.status_code == 200, result.text
    assert (
        result.json()["status"] == "partial"
        and result.json()["reconciliation"]["business_receipt_count"] == 1
    )
    with Session(setup.admin) as session:
        assert session.get(Claim, UUID(saved["subject_id"])).status == "active"
        assert session.get(Receipt, UUID(saved["id"])) is not None
        assert session.get(AgentToolCall, lost_id).state == "failed"
        assert (
            session.scalar(
                select(func.count()).select_from(Claim).where(Claim.run_id == actual.scope.run_id)
            )
            == 1
        )


def test_recovery_uses_original_request_key_and_exact_run_receipt(setup):
    promote(setup)
    store, scope = run(setup)
    identity = receipt(setup, scope)
    key = "synthetic-receipt-key"
    call_id, _ = store.claim(scope, key, "synthetic.draft", {}, reservation=50)
    with Session(setup.admin) as session, session.begin():
        saved = session.get(Receipt, identity)
        session.add(
            RequestKey(
                tenant_id=setup.tenant,
                category_id=setup.category,
                actor_id=setup.agent,
                key=key,
                digest=saved.request_digest,
                receipt_id=identity,
            )
        )
    with store.transaction(scope, lock=True) as (_, row):
        row.state, row.error_code = "waiting_input", "EXTERNAL_OUTCOME_UNKNOWN"
    result = finalize(setup.engine, setup.ctx, scope.run_id, expected_cancel_epoch=0)
    assert result["status"] == "partial" and result["reconciliation"]["recovered_call_count"] == 1
    with Session(setup.admin) as session:
        call = session.get(AgentToolCall, call_id)
        assert call.state == "completed" and call.receipt_id == identity
        assert session.get(AgentRun, scope.run_id).held_tokens == 0


def test_lost_activity_can_be_closed_without_admin_or_any_model_configuration(setup):
    f = lost(setup, admin=False, waiting=False)
    assert post(setup, f).status_code == 409
    result = KernelActivities(setup.engine).reconcile(
        {**reference(setup, f), "activity_exhausted": True}
    )
    assert result["status"] == "failed" and result["reconciliation"]["held_tokens"] == 0


def test_metadata_pagination_refuses_cross_run_cursor_and_has_no_raw_result_or_parameters(setup):
    f = lost(setup)
    f.store.claim(f.scope, "another-pending-read", "mcp.lookup", {"private": "never project this"})
    first = setup.client.get(path(setup, f) + "?page_size=1", headers=setup.headers)
    assert first.status_code == 200 and first.json()["next_call_cursor"]
    second = setup.client.get(
        path(setup, f) + "?page_size=1&call_cursor=" + first.json()["next_call_cursor"],
        headers=setup.headers,
    )
    assert second.status_code == 200 and len(second.json()["calls"]) == 1
    assert "never project this" not in first.text + second.text
    assert (
        setup.client.get(
            path(setup, f) + "?call_cursor=" + str(uuid4()), headers=setup.headers
        ).status_code
        == 403
    )


def test_read_only_owner_can_inspect_and_close_technical_wait_without_gain_of_revert_power(setup):
    from pdos_next.models import Grant

    f = lost(setup)
    saved = receipt(setup, f.scope)
    with Session(setup.admin) as session, session.begin():
        session.scalar(
            select(Grant).where(
                Grant.principal_id == setup.human, Grant.category_id == setup.category
            )
        ).can_write = False
    value = setup.client.get(path(setup, f), headers=setup.headers)
    assert value.status_code == 200 and value.json()["receipts"][0]["id"] == str(saved)
    assert (
        setup.client.post(
            f"/v1/categories/{setup.category}/agent-runs/{f.scope.run_id}/revert-preview",
            headers=setup.headers,
        ).status_code
        == 403
    )
    assert post(setup, f).json()["status"] == "partial"


def test_failure_after_settlement_rolls_back_slots_cost_run_and_technical_record(setup):
    from sqlalchemy import event

    f = lost(setup)

    def interrupt(_mapper, _connection, target):
        if target.body.get("type") == "run_reconciled":
            raise RuntimeError("synthetic after-settlement failure")

    event.listen(AgentEvent, "before_insert", interrupt)
    try:
        with pytest.raises(RuntimeError, match="after-settlement"):
            post(setup, f)
    finally:
        event.remove(AgentEvent, "before_insert", interrupt)
    with Session(setup.admin) as session:
        row, budget = session.get(AgentRun, f.scope.run_id), session.get(ValidationBudget, f.budget)
        assert row.cancel_epoch == 0 and row.held_tokens == 300 and row.state == "waiting_input"
        assert budget.held_micro_usd == f.charge and budget.spent_micro_usd == 0
        assert session.get(AgentToolCall, f.call).state == "started"
    assert post(setup, f).status_code == 200


def test_model_result_field_cannot_claim_reconciliation_or_bypass_administrator(setup):
    f = lost(setup, admin=False)
    fake = {"event_id": str(uuid4()), "original_cancel_epoch": 0, "mode": "administrator"}
    with f.store.transaction(f.scope, lock=True) as (_, row):
        row.result = {"result": {"reconciliation": fake}}
    meta = setup.client.get(path(setup, f), headers=setup.headers)
    assert meta.status_code == 200 and meta.json()["completed"] is None
    run_path = f"/v1/categories/{setup.category}/agent-runs/{f.scope.run_id}"
    assert setup.client.get(run_path, headers=setup.headers).json()["reconciliation"] is None
    assert post(setup, f).status_code == 403
    promote(setup)
    result = post(setup, f)
    assert result.status_code == 200
    assert result.json()["reconciliation"]["event_id"] != fake["event_id"]
