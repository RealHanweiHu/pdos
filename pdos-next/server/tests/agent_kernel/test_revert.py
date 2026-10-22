"""Technical revert ownership seams use synthetic receipts, never model qualification."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.activities import KernelActivities
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall, ValidationBudget
from pdos_next.agent_kernel.persistence import (
    finish_run_revert,
    prepare_run_revert,
    record_answers,
)
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Receipt
from tests.agent_kernel.test_api import client
from tests.agent_kernel.test_cost_budget import rate, wallet
from tests.agent_kernel.test_revoked_terminal import close
from tests.agent_kernel.test_transactions import human_session, run


def receipt(setup, scope, *, human=False, linked=True, product_id=None):
    identity = uuid4()
    with Session(setup.admin) as s, s.begin():
        s.add(Receipt(
            id=identity,
            tenant_id=setup.tenant,
            category_id=setup.category,
            product_id=product_id,
            command_id=uuid4(),
            actor_id=setup.human if human else setup.agent,
            requester_id=setup.human,
            operation="ai.run.revert" if human else "synthetic.draft",
            subject_type="agent_run" if human else "synthetic",
            subject_id=scope.run_id if human else uuid4(),
            subject_revision=1,
            visibility="private",
            request_digest=str(uuid4()),
            intent_digest=str(uuid4()),
            result={"synthetic": True},
            agent_run_id=scope.run_id if linked and not human else None,
        ))
    return identity


def finish(setup, scope, identity, epoch=None):
    with human_session(setup) as s:
        return finish_run_revert(
            s, setup.ctx, scope.run_id, revert_receipt_id=identity,
            expected_cancel_epoch=scope.cancel_epoch if epoch is None else epoch,
        )


def test_prepare_returns_every_actual_receipt_including_nonledger_receipts(setup):
    store, scope = run(setup)
    first = receipt(setup, scope)
    second = receipt(setup, scope, product_id=setup.product)
    call, _ = store.claim(scope, "draft", "synthetic.draft", {})
    store.settle(scope, call, result={"actual": True}, receipt_id=first)
    with human_session(setup) as s:
        actual, rows = prepare_run_revert(s, setup.ctx, scope.run_id, lock=True)
        assert actual.id == scope.run_id and {r.id for r in rows} == {first, second}


def test_missing_run_bound_receipt_refuses_whole_revert_and_does_not_stamp(setup):
    store, scope = run(setup)
    unbound = receipt(setup, scope, linked=False)
    call, _ = store.claim(scope, "draft", "synthetic.draft", {})
    store.settle(scope, call, result={}, receipt_id=unbound)
    with human_session(setup) as s, pytest.raises(DomainError) as exc:
        prepare_run_revert(s, setup.ctx, scope.run_id)
    assert exc.value.code == "FORBIDDEN_SCOPE"
    with Session(setup.admin) as s:
        assert s.get(AgentRun, scope.run_id).reverted_at is None


@pytest.mark.parametrize("field", ["requester_id", "actor_id"])
def test_hidden_or_wrong_writer_receipt_is_never_silently_omitted(setup, field):
    _, scope = run(setup)
    identity = receipt(setup, scope)
    with Session(setup.admin) as s, s.begin():
        setattr(s.get(Receipt, identity), field, setup.peer)
    # requester_id makes the private row invisible through RLS; actor_id keeps
    # it readable but breaks the actual writer envelope. Both forbid the whole set.
    with human_session(setup) as s, pytest.raises(DomainError) as exc:
        prepare_run_revert(s, setup.ctx, scope.run_id)
    assert exc.value.code == "FORBIDDEN_SCOPE"
    with Session(setup.admin) as s:
        assert s.get(AgentRun, scope.run_id).reverted_at is None


def test_product_bound_run_cannot_revert_a_different_scope_receipt(setup):
    _, scope = run(setup, product_id=setup.product)
    receipt(setup, scope)
    with human_session(setup) as s, pytest.raises(DomainError) as exc:
        prepare_run_revert(s, setup.ctx, scope.run_id)
    assert exc.value.code == "FORBIDDEN_SCOPE"


def test_revert_retains_completed_result_and_blocks_all_future_execution(setup):
    store, scope = run(setup)
    receipt(setup, scope)
    with store.transaction(scope, lock=True) as (_, row):
        row.state, row.result = "completed", {"historical": True}
    identity = receipt(setup, scope, human=True)
    result = finish(setup, scope, identity)
    assert result["reverted"] and result["cancel_epoch"] == 1
    assert finish(setup, scope, identity) == result
    with Session(setup.admin) as s:
        row = s.get(AgentRun, scope.run_id)
        assert row.state == "completed" and row.result == {"historical": True}
        assert row.reverted_by == setup.human and row.revert_receipt_id == identity
    with pytest.raises(DomainError) as exc:
        store.current(scope)
    assert exc.value.code == "CANCELLED_RUN"
    reference = {
        "tenant_id": str(setup.tenant), "category_id": str(setup.category),
        "actor_id": str(setup.human), "requester_id": str(setup.human),
        "subject_id": str(scope.run_id),
    }
    assert KernelActivities(setup.engine).advance(reference)["reverted"] is True
    with human_session(setup) as s, pytest.raises(DomainError) as exc:
        record_answers(s, setup.ctx, scope.run_id, answers={}, idempotency_key="after-revert")
    assert exc.value.code == "CANCELLED_RUN"
    assert close(setup, scope.run_id) is False


def test_revert_unknown_send_releases_existing_slots_and_keeps_fee_reservation(setup):
    budget_id = wallet(setup)
    store, scope = run(setup, validation_budget_id=budget_id)
    card = rate()
    estimate = card.reserve(100, 100)
    call_id, _ = store.claim(
        scope, "pending-model", "model", {}, reservation=200,
        cost_lease=(estimate, 100, 100, card.snapshot()),
    )
    identity = receipt(setup, scope, human=True)
    finish(setup, scope, identity)
    with Session(setup.admin) as s:
        actual = s.get(AgentRun, scope.run_id)
        call = s.get(AgentToolCall, call_id)
        budget = s.get(ValidationBudget, budget_id)
        assert actual.state == "queued" and actual.held_tokens == 0 and actual.used_tokens == 200
        assert call.state == "unknown" and call.cost_state == "estimated_unknown"
        assert call.cost_charged_micro_usd == estimate
        assert budget.held_micro_usd == 0 and budget.spent_micro_usd == estimate
    assert close(setup, scope.run_id) is False


def test_revert_requires_current_human_scope_and_actual_matching_receipt(setup):
    _, scope = run(setup)
    identity = receipt(setup, scope, human=True)
    with pytest.raises(DomainError) as exc:
        finish(setup, scope, identity, epoch=3)
    assert exc.value.code == "VERSION_CONFLICT"
    with pytest.raises(DomainError) as exc:
        finish(setup, scope, receipt(setup, scope))
    assert exc.value.code == "FORBIDDEN_SCOPE"
    for ctx in (
        replace(setup.ctx, actor_id=setup.peer, requester_id=setup.peer),
        replace(setup.ctx, category_id=uuid4()),
        replace(setup.ctx, tenant_id=setup.other_tenant),
    ):
        with human_session(setup) as s, pytest.raises(DomainError) as exc:
            prepare_run_revert(s, ctx, scope.run_id)
        assert exc.value.code == "FORBIDDEN_SCOPE"
    with Session(setup.admin) as s, s.begin():
        s.scalar(select(Grant).where(Grant.principal_id == setup.human)).can_write = False
    with pytest.raises(DomainError) as exc:
        finish(setup, scope, identity)
    assert exc.value.code == "FORBIDDEN_SCOPE"


def test_revert_uow_rolls_back_technical_stamp_if_public_owner_transaction_fails(setup):
    store, scope = run(setup)
    call_id, _ = store.claim(scope, "pending", "model", {}, reservation=100)
    identity = receipt(setup, scope, human=True)
    with pytest.raises(RuntimeError, match="synthetic owner failure"):
        with human_session(setup) as s:
            finish_run_revert(
                s, setup.ctx, scope.run_id, revert_receipt_id=identity, expected_cancel_epoch=0
            )
            raise RuntimeError("synthetic owner failure")
    with Session(setup.admin) as s:
        row, call = s.get(AgentRun, scope.run_id), s.get(AgentToolCall, call_id)
        assert row.reverted_at is None and row.cancel_epoch == 0 and row.held_tokens == 100
        assert call.state == "started" and call.reserved_tokens == 100


def test_direct_sql_cannot_forge_stamp_or_mutate_completed_or_reverted_run(setup):
    store, scope = run(setup)
    with store.transaction(scope, lock=True) as (_, row):
        row.state = "completed"
    for sql, values in (
        ("UPDATE agent_runs SET cancel_epoch=cancel_epoch+1 WHERE id=:id", {}),
        ("UPDATE agent_runs SET reverted_at=clock_timestamp(),reverted_by=:actor,"
         "revert_receipt_id=:receipt,cancel_epoch=cancel_epoch+1 WHERE id=:id",
         {"actor": setup.human, "receipt": uuid4()}),
    ):
        with pytest.raises(DBAPIError):
            with human_session(setup) as s:
                s.execute(text(sql), {"id": scope.run_id, **values})
    finish(setup, scope, receipt(setup, scope, human=True))
    with pytest.raises(DBAPIError):
        with human_session(setup) as s:
            s.execute(
                text("UPDATE agent_runs SET reverted_at=NULL WHERE id=:id"), {"id": scope.run_id}
            )


def test_reverted_run_read_events_and_stream_show_technical_receipt_without_restarting(setup):
    _, scope = run(setup)
    identity = receipt(setup, scope, human=True)
    finish(setup, scope, identity)
    api, calls = client(setup)
    path = f"/v1/categories/{setup.category}/agent-runs/{scope.run_id}"
    result = api.get(path).json()
    assert result["status"] == "queued" and result["reverted"] is True
    assert result["revert_receipt_id"] == str(identity)
    events = api.get(path + "/events").json()
    assert events["reverted"] is True and events["items"][0]["event"]["type"] == "run_reverted"
    stream = api.get(path + "/stream")
    assert '"reverted": true' in stream.text and "event: end" in stream.text
    assert calls == []
    api.close()
