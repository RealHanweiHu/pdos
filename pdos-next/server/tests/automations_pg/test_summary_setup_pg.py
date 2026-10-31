"""Real native T1/Grant/Attempt and walletless deterministic Run; root executes PG.

No model qualification, arbitrary fixed skill, model wallet, business fact or
clock is manufactured. Negative cases touch only explicit authorization/Run guards.
"""

import os
from datetime import timedelta
from types import SimpleNamespace as NS
from uuid import UUID, uuid4

import pytest
from pdos_agent_runtime.graph import registered_graph_context
from pdos_next.agent_kernel.activities import KernelActivities
from pdos_next.agent_kernel.models import (
    AgentRun,
    AgentToolCall,
    TenantSkillEnablement,
    ValidationBudget,
)
from pdos_next.agent_kernel.persistence import KernelStore, cancel_run
from pdos_next.database import tenant_session
from pdos_next.domain.automations import service_runtime
from pdos_next.domain.automations.schemas import ZERO_MODEL_BUDGET
from pdos_next.domain.automations.service_models import AutomationServiceAttempt
from pdos_next.enterprise_search.assistant_adapter import AssistantReadAdapter
from pdos_next.enterprise_search.embedding_query import QueryEmbedding, QueryPorts
from pdos_next.errors import DomainError
from pdos_next.models import Grant, now
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.automations_pg.test_service_automation_pg import _activate


@pytest.fixture
def summary_setup(setup):
    with Session(setup.admin) as s:
        for model in (ValidationBudget, TenantSkillEnablement):
            assert (
                s.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(
                        model.tenant_id == setup.tenant,
                    )
                )
                == 0
            )
    spec = {
        "name": "Actual walletless personal summary",
        "goal": "Read subscriber current facts",
        "purpose": "Personal structured summary without inference",
        "stop_condition": "Complete structured result or report unavailable scope",
        "trigger_kind": "schedule",
        "trigger_config": {
            "first_at": (now() - timedelta(minutes=2)).isoformat(),
            "original_timezone": "UTC",
        },
        "personal_summary": {"groups": [], "category_ids": [str(setup.category)]},
        "product_id": str(setup.product),
        "skill_keys": [],
        "validation_budget_id": None,
        "token_limit": 1,
        "budget": dict(ZERO_MODEL_BUDGET),
        "cooldown_seconds": 0,
        "max_runs": 3,
    }
    rule, reference = _activate(setup, spec)
    assert service_runtime.tick(setup.engine, reference)["state"] == "active"
    with Session(setup.admin) as s:
        attempt = s.scalar(
            select(AutomationServiceAttempt).where(
                AutomationServiceAttempt.service_grant_id == UUID(reference["grant_id"]),
                AutomationServiceAttempt.state == "admitted",
            )
        )
        assert attempt is not None
        run = s.get(AgentRun, attempt.run_id)
        assert run.validation_budget_id is None and run.writer_id == setup.agent
        assert run.requester_id == setup.human and run.token_limit == 1
        envelope = {
            "tenant_id": str(run.tenant_id),
            "category_id": str(run.category_id),
            "actor_id": str(run.writer_id),
            "requester_id": str(run.requester_id),
            "subject_id": str(run.id),
        }
    store = KernelStore(setup.engine)
    scope = store.scope(
        tenant_id=setup.tenant,
        requester_id=setup.human,
        writer_id=setup.agent,
        category_id=setup.category,
        run_id=UUID(envelope["subject_id"]),
    )
    return NS(
        setup=setup, rule=rule, reference=reference, envelope=envelope, store=store, scope=scope
    )


def counts(work):
    with Session(work.setup.admin) as s:
        return tuple(
            s.scalar(
                select(func.count())
                .select_from(model)
                .where(
                    model.tenant_id == work.setup.tenant,
                )
            )
            for model in (ValidationBudget, TenantSkillEnablement, AgentToolCall)
        )


def worker(work, monkeypatch):
    monkeypatch.setattr(work.setup.engine, "_pdos_agent_kernel_adapters", None, raising=False)
    monkeypatch.setattr("pdos_next.agent_kernel.activities.activity.heartbeat", lambda *_a: None)
    return KernelActivities(
        work.setup.engine,
        checkpoint_url=os.environ["PDOS_CHECKPOINT_DATABASE_URL"],
        technical_engine=work.setup.dispatch,
    )


def test_actual_native_authorized_summary_runs_without_model_skill_wallet_or_adapter(
    summary_setup,
    monkeypatch,
):
    work = summary_setup
    activity = worker(work, monkeypatch)
    assert counts(work) == (0, 0, 0)
    assert activity.advance(work.envelope)["status"] == "completed"
    assert activity.advance(work.envelope)["status"] == "completed"
    with Session(work.setup.admin) as s:
        run = s.get(AgentRun, work.scope.run_id)
        assert run.validation_budget_id is None and run.held_tokens == run.used_tokens == 0
        result = run.result["result"]["personal_summary"]
        assert result["principal_id"] == str(work.setup.human) and result["model_used"] is False
    assert counts(work) == (0, 0, 0)


@pytest.mark.parametrize("name", ["model", "assistant.search", "generic.read"])
def test_actual_summary_cannot_claim_any_generic_or_unmetered_tool(summary_setup, name):
    work = summary_setup
    with pytest.raises(DomainError) as error:
        work.store.claim(work.scope, "denied:" + name, name, {}, reservation=0)
    assert error.value.code == "FORBIDDEN_SCOPE"
    # SQL also refuses a caller that attempts to bypass the Python dispatcher.
    with pytest.raises(DBAPIError, match="Deterministic summary cannot acquire"):
        with Session(work.setup.admin) as s, s.begin():
            s.add(
                AgentToolCall(
                    tenant_id=work.setup.tenant,
                    run_id=work.scope.run_id,
                    call_key="direct:" + name,
                    tool=name,
                    input_digest="a" * 64,
                )
            )
            s.flush()
    assert counts(work) == (0, 0, 0)


def test_no_actual_search_call_means_query_embedding_adapter_never_runs(summary_setup):
    work = summary_setup

    def forbidden(*_a, **_k):
        raise AssertionError("a summary cannot reach the query embedding provider")

    adapter = AssistantReadAdapter(work.store, NS(), query_embedding=NS(prepare=forbidden))
    with pytest.raises(DomainError) as error:
        adapter.search(work.scope, {"query": "must not leave"}, intent_key="no-real-call")
    assert error.value.code == "FORBIDDEN_SCOPE"
    assert counts(work) == (0, 0, 0)


def test_direct_query_embedding_entry_requires_actual_main_read_before_any_port(summary_setup):
    work = summary_setup

    def forbidden(*_a, **_k):
        raise AssertionError("Summary must stop before profile, source or provider access")

    runtime = QueryEmbedding(
        work.store, QueryPorts(NS(), forbidden), source_guard=forbidden
    )
    with registered_graph_context("xiaopai"), pytest.raises(DomainError) as error:
        runtime.prepare(work.scope, uuid4(), {"query": "local denied summary query"})
    assert error.value.code == "FORBIDDEN_SCOPE"
    assert counts(work) == (0, 0, 0)


def test_original_fixed_run_proof_still_refuses_in_place_capacity_changes(summary_setup):
    work = summary_setup
    with pytest.raises(DBAPIError, match="Service Run requires"):
        with Session(work.setup.admin) as s, s.begin():
            s.execute(
                update(AgentRun).where(AgentRun.id == work.scope.run_id).values(token_limit=2)
            )
    assert counts(work) == (0, 0, 0)


def test_real_service_authority_revocation_is_not_bypassed_by_walletless_mode(summary_setup):
    work = summary_setup
    with Session(work.setup.admin) as s, s.begin():
        s.execute(
            update(Grant)
            .where(
                Grant.tenant_id == work.setup.tenant,
                Grant.category_id == work.setup.category,
                Grant.principal_id == work.setup.agent,
            )
            .values(expires_at=now() - timedelta(seconds=1))
        )
    with pytest.raises(DomainError) as error:
        work.store.current(work.scope)
    assert error.value.code == "FORBIDDEN_SCOPE"
    assert counts(work) == (0, 0, 0)


def test_actual_cancellation_remains_terminal_without_any_model_capacity(
    summary_setup, monkeypatch
):
    work = summary_setup
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as s:
        assert cancel_run(s, work.setup.ctx, work.scope.run_id)["status"] == "cancelled"
    assert worker(work, monkeypatch).advance(work.envelope)["status"] == "cancelled"
    assert counts(work) == (0, 0, 0)
