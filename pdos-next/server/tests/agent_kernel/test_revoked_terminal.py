from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.activities import KernelActivities
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall, ValidationBudget
from pdos_next.database import tenant_session
from pdos_next.models import Audit, Grant, Outbox, Product, now
from tests.agent_kernel.test_cost_budget import rate, wallet
from tests.agent_kernel.test_transactions import run


def revoke(setup):
    with Session(setup.admin) as s, s.begin():
        grant = s.scalar(select(Grant).where(Grant.principal_id == setup.agent))
        grant.expires_at = now() - timedelta(seconds=1)


def close(setup, run_id, **context):
    with tenant_session(
        setup.dispatch,
        context.get("tenant", setup.tenant),
        actor_id=context.get("actor", setup.human),
        requester_id=context.get("requester", setup.human),
        category_id=context.get("category", setup.category),
    ) as s:
        return s.scalar(text("SELECT kernel_scope_failed(:id)"), {"id": run_id})


def test_dispatch_terminal_requires_actual_lost_scope_and_app_cannot_call_direct_sql(setup):
    identity = wallet(setup)
    store, scope = run(setup, validation_budget_id=identity)
    card = rate()
    estimate = card.reserve(100, 100)
    call, _ = store.claim(
        scope,
        "pending",
        "model",
        {},
        reservation=200,
        cost_lease=(estimate, 100, 100, card.snapshot()),
    )
    assert close(setup, scope.run_id) is False  # Even dispatcher cannot stop a healthy Run.
    revoke(setup)
    with pytest.raises(DBAPIError, match="permission denied"):
        with tenant_session(
            setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
        ) as s:
            s.execute(text("SELECT kernel_scope_failed(:id)"), {"id": scope.run_id})
    for context in (
        {"tenant": setup.other_tenant},
        {"category": uuid4()},
        {"actor": setup.peer, "requester": setup.peer},
        {"actor": setup.peer},
    ):
        assert close(setup, scope.run_id, **context) is False
    assert close(setup, uuid4()) is False
    with Session(setup.admin) as s:
        before = (
            s.get(Product, setup.product).revision,
            s.get(Product, setup.product).lifecycle_epoch,
        )
        assert s.get(AgentRun, scope.run_id).state == "queued"
    assert close(setup, scope.run_id) is True
    assert close(setup, scope.run_id) is False
    with Session(setup.admin) as s:
        row = s.get(AgentRun, scope.run_id)
        budget = s.get(ValidationBudget, identity)
        assert row.state == "failed" and row.error_code == "FORBIDDEN_SCOPE" and row.result is None
        assert row.held_tokens == 0 and row.used_tokens == 200
        assert s.get(AgentToolCall, call).state == "unknown"
        assert budget.held_micro_usd == 0 and budget.spent_micro_usd == estimate
        assert (
            s.get(Product, setup.product).revision,
            s.get(Product, setup.product).lifecycle_epoch,
        ) == before
        for cls in (Audit, Outbox):
            assert (
                s.scalar(select(func.count()).select_from(cls).where(cls.tenant_id == setup.tenant))
                == 0
            )
    with setup.engine.connect() as c:
        for role in ("pdos_agent", "pdos_next_app", "pdos_next_auth"):
            assert not c.execute(
                text("SELECT has_function_privilege(:role,'kernel_scope_failed(uuid)','EXECUTE')"),
                {"role": role},
            ).scalar_one()


@pytest.mark.parametrize("state", ["completed", "partial", "failed", "cancelled"])
def test_revoked_terminal_does_not_reopen_or_change_existing_terminal_state(setup, state):
    store, scope = run(setup)
    with store.transaction(scope, lock=True) as (_, row):
        row.state = state
    revoke(setup)
    assert close(setup, scope.run_id) is False
    with Session(setup.admin) as s:
        assert s.get(AgentRun, scope.run_id).state == state


def test_revocation_before_activity_start_records_failed_without_any_model_call(setup):
    _, scope = run(setup)
    revoke(setup)
    result = KernelActivities(setup.engine, technical_engine=setup.dispatch).advance(
        {
            "tenant_id": str(setup.tenant),
            "category_id": str(setup.category),
            "actor_id": str(setup.human),
            "requester_id": str(setup.human),
            "subject_id": str(scope.run_id),
        }
    )
    assert result["status"] == "failed" and result["error_code"] == "FORBIDDEN_SCOPE"
    with Session(setup.admin) as s:
        assert s.get(AgentRun, scope.run_id).state == "failed"
