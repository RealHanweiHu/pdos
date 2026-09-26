"""Run only on an isolated pdos_test cluster: fixture configures global test roles."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import TypedDict
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, select, text, update
from sqlalchemy.exc import DBAPIError

from app.ai.gateway import StructuredModelGateway
from app.ai.lease_heartbeat import AgentLeaseLostError
from app.ai.model_call_fence import ModelCallFence, ModelCallFenceError, ModelCallModeService
from app.ai.model_catalog import ProtocolKind
from app.ai.provider_adapters import ProviderResponse
from app.ai.run_store import ClaimedAgentRun, RestrictedAgentRunStore
from app.db.schema import tables
from app.db.url import psycopg_database_url
from app.domain.model_governance import ModelGovernanceService
from tests.test_agent_database_security import denied, role_engine, seed_two_tenants
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)
from tests.test_event_budget_adoption import EventScope, scope_id
from tests.test_event_budget_adoption import event_scope as event_scope
from tests.test_model_gateway import FakeAdapter, RiskOutput, catalog, invocation, qualification

ModelCallScope = tuple[
    Engine, Engine, RestrictedAgentRunStore, ClaimedAgentRun, dict[str, UUID | int], UUID
]


class FenceArguments(TypedDict):
    tenant_id: UUID
    run_id: UUID | None
    project_id: UUID | None
    agent_key: str
    budgeted: bool


@pytest.fixture
def scope(secured_agent_database_url: str) -> Iterator[ModelCallScope]:
    owner = create_engine(psycopg_database_url(secured_agent_database_url))
    agent = role_engine(secured_agent_database_url, "pdos_agent")
    try:
        with owner.begin() as c:
            ids = seed_two_tenants(c)
            admin = uuid4()
            c.execute(
                tables.users.insert(),
                dict(
                    id=admin,
                    tenant_id=scope_id(ids, "tenant_a"),
                    username=str(admin),
                    email=f"{admin}@synthetic.test",
                    display_name="Test owner",
                    role="owner",
                ),
            )
        store = RestrictedAgentRunStore(agent)
        claim = store.claim(started_at=datetime.now(UTC))
        assert claim is not None
        with store.scope(claim):
            yield owner, agent, store, claim, ids, admin
    finally:
        agent.dispose()
        owner.dispose()


def authorize_budgeted_scope(scope: ModelCallScope) -> None:
    """Complete owner-created budget fixture setup using the real authorization issuer."""
    owner, _, _, claim, _, _ = scope
    with owner.begin() as connection:
        connection.execute(
            text("SELECT cehub_ai.issue_event_authorization(:run_id, :lease_token)"),
            {"run_id": claim.id, "lease_token": claim.lease_token},
        )


def test_agent_fence_derives_scope_and_cannot_change_policy_or_budget(
    scope: ModelCallScope,
) -> None:
    owner, agent, store, claim, ids, _ = scope
    fence = ModelCallFence(agent, store)
    # Model-supplied scope is ignored by the restricted port; server lease wins.
    session = fence.begin(
        tenant_id=uuid4(), run_id=uuid4(), project_id=uuid4(), agent_key="forged", budgeted=False
    )
    with owner.connect() as c:
        row = c.execute(select(tables.model_call_sessions)).mappings().one()
    assert row["tenant_id"] == scope_id(ids, "tenant_a") and row["project_id"] == scope_id(
        ids, "project_a"
    )
    assert row["run_id"] == claim.id and row["agent_key"] == "project_intelligence"
    assert row["execution_mode"] == "legacy"
    with pytest.raises(ModelCallFenceError, match="BUDGET_RUN_UNBOUND"):
        fence.begin(
            tenant_id=scope_id(ids, "tenant_a"),
            run_id=claim.id,
            project_id=scope_id(ids, "project_a"),
            agent_key="project_intelligence",
            budgeted=True,
        )
    with agent.begin() as c:
        store.bind(c)
        denied(
            c,
            "SELECT * FROM cehub_ai.open_model_call(:tenant, NULL, NULL, 'x', 'budgeted')",
            {"tenant": scope_id(ids, "tenant_a")},
        )
        denied(
            c,
            "SELECT cehub_ai.finish_model_call(:tenant, :session, :trace)",
            {"tenant": scope_id(ids, "tenant_a"), "session": session, "trace": uuid4()},
        )
        for name in (
            "model_call_sessions",
            "model_call_events",
            "model_call_mode_events",
            "budget_journal",
        ):
            denied(c, f"SELECT * FROM cehub_ai.{name}", {})
            denied(c, f"DELETE FROM cehub_ai.{name}", {})
        denied(c, "INSERT INTO cehub_ai.model_call_mode_events DEFAULT VALUES", {})
    fence.unknown(tenant_id=scope_id(ids, "tenant_a"), session_id=session)


@pytest.mark.parametrize(
    "setting", ["pdos.agent_lease_token", "pdos.tenant_id", "pdos.project_id", "pdos.agent_run_id"]
)
def test_agent_open_denies_forged_transaction_scope(scope: ModelCallScope, setting: str) -> None:
    _, agent, store, _, _, _ = scope
    with agent.begin() as c:
        store.bind(c)
        c.execute(
            text("SELECT set_config(:key, :value, true)"), {"key": setting, "value": str(uuid4())}
        )
        denied(c, "SELECT * FROM cehub_ai.agent_open_model_call()", {})
    with agent.begin() as c:
        denied(c, "SELECT * FROM cehub_ai.agent_open_model_call()", {})


def test_agent_cannot_close_another_tenant_or_expired_lease_session(scope: ModelCallScope) -> None:
    owner, agent, store, claim, ids, _ = scope
    fence = ModelCallFence(agent, store)
    own = fence.begin(
        tenant_id=scope_id(ids, "tenant_a"),
        run_id=claim.id,
        project_id=scope_id(ids, "project_a"),
        agent_key="project_intelligence",
        budgeted=False,
    )
    other = ModelCallFence(owner).begin(
        tenant_id=scope_id(ids, "tenant_b"),
        run_id=None,
        project_id=scope_id(ids, "project_b"),
        agent_key="project_intelligence",
        budgeted=False,
    )
    with pytest.raises(DBAPIError):
        fence.unknown(tenant_id=scope_id(ids, "tenant_a"), session_id=other)
    with owner.begin() as c:
        c.execute(
            update(tables.agent_runs)
            .where(tables.agent_runs.c.id == claim.id)
            .values(status="succeeded", completed_at=datetime.now(UTC))
        )
    with pytest.raises(AgentLeaseLostError, match="AGENT_RUN_LEASE_LOST"):
        fence.unknown(tenant_id=scope_id(ids, "tenant_a"), session_id=own)


def test_restricted_gateway_closes_trace_and_honors_persistent_drain(scope: ModelCallScope) -> None:
    owner, agent, store, claim, ids, admin = scope
    adapter = FakeAdapter(
        [
            ProviderResponse(
                content='{"risk":"low"}',
                input_tokens=7,
                output_tokens=3,
                request_id="synthetic",
                model_version="synthetic",
            )
        ]
    )
    runtime = StructuredModelGateway(
        agent,
        catalog=catalog(),
        qualifications=[qualification()],
        governance=ModelGovernanceService(
            agent,
            catalog=catalog(),
            qualifications=[qualification()],
            default_daily_token_budget=1000,
            run_store=store,
        ),
        adapters={ProtocolKind.OPENAI_COMPATIBLE: adapter},
        rate_cards={},
        run_store=store,
    )
    inv = invocation(
        scope_id(ids, "tenant_a"), run_id=claim.id, project_id=scope_id(ids, "project_a")
    )
    result = runtime.invoke_structured(inv, RiskOutput)
    assert result.status == "succeeded"
    with owner.connect() as c:
        events = list(
            c.execute(
                select(tables.model_call_events).order_by(tables.model_call_events.c.revision)
            ).mappings()
        )
        trace = c.execute(select(tables.model_invocations)).mappings().one()
    assert [r["state"] for r in events] == ["open", "closed"]
    assert events[-1]["invocation_id"] == result.invocation_id
    assert trace["model_call_session_id"] == events[-1]["session_id"]
    ModelCallModeService(owner).change(
        tenant_id=scope_id(ids, "tenant_a"),
        actor_user_id=admin,
        expected_revision=0,
        action="request",
        target="budgeted",
        evidence_ref="synthetic",
    )
    denied_result = runtime.invoke_structured(inv, RiskOutput)
    assert denied_result.error_code == "MODEL_CALL_DRAINING" and len(adapter.calls) == 1


def test_restricted_legacy_call_obeys_owner_budget_reservation(event_scope: EventScope) -> None:
    from app.ai.budget_ledger import BudgetLedger
    from app.worker.dispatcher import AgentDispatcher
    from tests.test_budget_ledger import reserve

    owner, worker, agent, ids = event_scope
    dispatcher = AgentDispatcher(worker, budget_profile_key="short")
    dispatcher.dispatch_tenant(tenant_id=scope_id(ids, "tenant_a"))
    dispatcher.seal_due_runs()
    store = RestrictedAgentRunStore(agent)
    claim = store.claim(started_at=datetime.now(UTC))
    assert claim is not None
    ledger = BudgetLedger(owner)
    held = reserve(ledger, scope_id(ids, "tenant_a"), claim.id)
    fence = ModelCallFence(agent, store)
    args: FenceArguments = dict(
        tenant_id=scope_id(ids, "tenant_a"),
        run_id=claim.id,
        project_id=scope_id(ids, "project_a"),
        agent_key="project_intelligence",
        budgeted=False,
    )
    # Budget and service authorization predate this claim. Closing a reservation
    # never authorizes a switch back to an unbudgeted model call.
    with store.scope(claim):
        with pytest.raises(ModelCallFenceError, match="MODEL_CALL_BUDGET_REQUIRED"):
            fence.begin(**args)
        with agent.begin() as c:
            store.bind(c)
            denied(
                c,
                "SELECT cehub_ai.model_calls_in_flight(:tenant, 'legacy')",
                {"tenant": scope_id(ids, "tenant_a")},
            )
        ledger.transition(
            tenant_id=scope_id(ids, "tenant_a"), attempt_id=held.entry.attempt_id, action="cancel"
        )
        with pytest.raises(ModelCallFenceError, match="MODEL_CALL_BUDGET_REQUIRED"):
            fence.begin(**args)


def test_claiming_before_budget_cannot_mint_service_authority_later(scope: ModelCallScope) -> None:
    from app.ai.budget_ledger import BudgetLedger
    from tests.test_budget_ledger import profile

    owner, agent, store, claim, ids, _ = scope
    BudgetLedger(owner).open_lineage(
        tenant_id=scope_id(ids, "tenant_a"), run_id=claim.id, profile=profile()
    )
    with pytest.raises(AgentLeaseLostError, match="AGENT_RUN_LEASE_LOST"):
        ModelCallFence(agent, store).begin(
            tenant_id=scope_id(ids, "tenant_a"),
            run_id=claim.id,
            project_id=scope_id(ids, "project_a"),
            agent_key="project_intelligence",
            budgeted=False,
        )
