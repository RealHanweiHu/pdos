"""Actual native cancellation/revocation while a synthetic query call is in flight."""

import os

import pytest
from pdos_agent_runtime.graph import registered_graph_context
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import AgentToolCall, ValidationBudget
from pdos_next.agent_kernel.persistence import cancel_run
from pdos_next.enterprise_search.embedding_query_binding import TOOL
from pdos_next.errors import DomainError
from pdos_next.models import Grant
from tests.agent_kernel.test_transactions import human_session
from tests.enterprise_search.test_embedding_query_pg import actual_query

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="Explicit verified local PostgreSQL required"
)


@pytest.mark.parametrize("boundary", ["cancel", "revoke"])
def test_inflight_query_never_releases_vector_or_double_charges_after_authority_loss(
    setup,
    monkeypatch,
    boundary,
):
    f, runtime, provider, budget_id, parent_id = actual_query(setup, monkeypatch)
    original = provider.embed
    reserved_before_loss = []

    def reply_after_loss(*args, **kwargs):
        response = original(*args, **kwargs)
        with Session(setup.admin) as session:
            reserved_before_loss.append(
                session.scalar(
                    select(AgentToolCall.cost_reserved_micro_usd).where(
                        AgentToolCall.run_id == f.scope.run_id,
                        AgentToolCall.tool == TOOL,
                    )
                )
            )
        if boundary == "cancel":
            with human_session(setup) as session:
                cancel_run(session, setup.ctx, f.scope.run_id)
        else:
            with Session(setup.admin) as session, session.begin():
                session.execute(
                    delete(Grant).where(
                        Grant.tenant_id == setup.tenant,
                        Grant.category_id == setup.category,
                        Grant.principal_id == setup.human,
                    )
                )
        return response

    monkeypatch.setattr(provider, "embed", reply_after_loss)
    with registered_graph_context("xiaopai"), pytest.raises(DomainError) as error:
        runtime.prepare(f.scope, parent_id, f.read_arguments)
    assert error.value.code == ("CANCELLED_RUN" if boundary == "cancel" else "FORBIDDEN_SCOPE")
    assert len(provider.calls) == 1
    with Session(setup.admin) as session:
        call = session.scalar(
            select(AgentToolCall).where(
                AgentToolCall.run_id == f.scope.run_id,
                AgentToolCall.tool == TOOL,
            )
        )
        assert call.state in {"failed", "unknown"} and call.result is None
        budget = session.get(ValidationBudget, budget_id)
        assert budget.calls == 1 and budget.held_micro_usd == 0 and budget.spent_micro_usd > 0
        before = (budget.calls, budget.spent_micro_usd, call.cost_charged_micro_usd)
        call_id = call.id
        if boundary == "cancel":
            assert call.cost_state == "estimated_unknown"
            assert call.cost_charged_micro_usd == reserved_before_loss[0] > 0
            assert call.cost_reserved_micro_usd == 0
        else:
            assert call.cost_state == "actual" and call.actual_input_tokens == 10
    assert not f.store.release_call(f.scope, call_id, unknown=True, error="SOURCE_UNAVAILABLE")
    with Session(setup.admin) as session:
        budget = session.get(ValidationBudget, budget_id)
        call = session.get(AgentToolCall, call_id)
        assert (budget.calls, budget.spent_micro_usd, call.cost_charged_micro_usd) == before
