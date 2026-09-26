"""Isolated pdos_test only: end-to-end restricted model budget admission."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import UUID, uuid4

import httpx2
import pytest
from pydantic import BaseModel
from sqlalchemy import Engine, RowMapping, select, text, update

from app.ai.agent_budget import RestrictedBudgetLedger
from app.ai.budget_evidence import BudgetRequestBinding
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError, BudgetReceipt
from app.ai.egress import ProviderEgressPolicy
from app.ai.gateway import GatewayInvocation, StructuredModelGateway
from app.ai.model_budget import ModelBudgetController, ModelBudgetPort
from app.ai.model_catalog import ModelCatalog, ProtocolKind, ProviderName
from app.ai.provider_adapters import OpenAICompatibleAdapter
from app.ai.run_store import ClaimedAgentRun, RestrictedAgentRunStore
from app.db.schema import tables
from app.domain.model_governance import ModelGovernanceService
from tests.agent_context_fixtures import freeze_project_invocation
from tests.test_agent_budget_transitions import denied
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)
from tests.test_budget_ledger import profile
from tests.test_model_budget_controller import qualified, response
from tests.test_model_call_fence_security import authorize_budgeted_scope
from tests.test_model_call_fence_security import scope as scope
from tests.test_model_gateway import RiskOutput, catalog, qualification
from tests.test_model_provider_http_contract import FakeProviderHandler, fake_provider

BudgetScope = tuple[
    Engine, Engine, RestrictedAgentRunStore, ClaimedAgentRun, dict[str, UUID | int], UUID
]


def scope_id(ids: dict[str, UUID | int], name: str) -> UUID:
    value = ids[name]
    assert isinstance(value, UUID)
    return value


def prepare(
    scope: BudgetScope, *, daily: int = 1000, provision: bool = True, configure: bool = True
) -> RestrictedBudgetLedger:
    owner, agent, store, claim, ids, _ = scope
    if provision:
        BudgetLedger(owner).open_lineage(
            tenant_id=scope_id(ids, "tenant_a"), run_id=claim.id, profile=profile()
        )
    if provision:
        authorize_budgeted_scope(scope)
    if configure:
        with owner.begin() as connection:
            connection.execute(
                tables.tenant_model_settings.insert(),
                dict(
                    id=uuid4(),
                    tenant_id=scope_id(ids, "tenant_a"),
                    provider="minimax",
                    model="MiniMax-M2.7",
                    daily_token_budget=daily,
                ),
            )
    return RestrictedBudgetLedger(agent, store)


def binding(**changes: object) -> BudgetRequestBinding:
    return BudgetRequestBinding.model_validate(
        dict(
            model_call_id=uuid4(),
            structured_attempt=1,
            request_digest="a" * 64,
            provider="minimax",
            model="MiniMax-M2.7",
            protocol="openai-compatible",
            qualification_ref="synthetic",
            meter_version="synthetic",
            qualified_window=8192,
            qualified_output_limit=20,
            output_parameter="max_tokens",
            output_limit=20,
            **changes,
        )
    )


def reserve(
    scope: BudgetScope,
    port: ModelBudgetPort,
    *,
    attempt: UUID | None = None,
    body: BudgetRequestBinding | None = None,
    inputs: int = 10,
    tenant: UUID | None = None,
    run: UUID | None = None,
) -> BudgetReceipt:
    _, _, _, claim, ids, _ = scope
    return port.reserve(
        tenant_id=tenant or scope_id(ids, "tenant_a"),
        run_id=run or claim.id,
        attempt_id=attempt or uuid4(),
        call_kind="model",
        input_tokens=inputs,
        output_tokens=20,
        tenant_daily_token_limit=10**18,
        request_binding=body or binding(),
    )


def journal(owner: Engine) -> list[RowMapping]:
    with owner.connect() as connection:
        return list(
            connection.execute(
                select(tables.budget_journal).order_by(tables.budget_journal.c.revision)
            ).mappings()
        )


def gateway(
    scope: BudgetScope,
    port: ModelBudgetPort,
    client: httpx2.Client,
    *,
    model_catalog: ModelCatalog | None = None,
) -> StructuredModelGateway:
    _, agent, store, _, _, _ = scope
    configured = model_catalog or catalog()
    return StructuredModelGateway(
        agent,
        catalog=configured,
        qualifications=[qualification()],
        governance=ModelGovernanceService(
            agent,
            catalog=configured,
            qualifications=[qualification()],
            default_daily_token_budget=1000,
            run_store=store,
        ),
        adapters={
            ProtocolKind.OPENAI_COMPATIBLE: OpenAICompatibleAdapter(
                client, ProviderEgressPolicy.from_catalog(configured)
            )
        },
        rate_cards={},
        run_store=store,
        budget_controller=ModelBudgetController(
            port, profile=profile(), meters={(ProviderName.MINIMAX, "MiniMax-M2.7"): qualified()}
        ),
    )


def call(scope: BudgetScope, output_type: type[BaseModel] = RiskOutput) -> GatewayInvocation:
    _, agent, store, claim, ids, _ = scope
    return freeze_project_invocation(
        agent,
        store,
        claim,
        tenant_id=scope_id(ids, "tenant_a"),
        project_id=scope_id(ids, "project_a"),
        output_type=output_type,
    )


def test_missing_service_lineage_or_tenant_setting_never_creates_policy(scope: BudgetScope) -> None:
    owner, _, _, claim, ids, _ = scope
    port = prepare(scope, provision=False, configure=False)
    with pytest.raises(BudgetLedgerError, match="BUDGET_RUN_UNBOUND"):
        port.open_lineage(tenant_id=scope_id(ids, "tenant_a"), run_id=claim.id, profile=profile())
    BudgetLedger(owner).open_lineage(
        tenant_id=scope_id(ids, "tenant_a"), run_id=claim.id, profile=profile()
    )
    authorize_budgeted_scope(scope)
    with pytest.raises(BudgetLedgerError, match="BUDGET_TENANT_POLICY_REQUIRED"):
        reserve(scope, port)
    assert not journal(owner)


def test_current_tenant_limit_and_frozen_profile_override_caller_claims(scope: BudgetScope) -> None:
    owner, _, _, claim, ids, _ = scope
    port = prepare(scope, daily=25)
    with pytest.raises(BudgetLedgerError, match="BUDGET_PROFILE_CONFLICT"):
        port.open_lineage(
            tenant_id=scope_id(ids, "tenant_a"),
            run_id=claim.id,
            profile=profile(lineage_token_limit=1000),
        )
    with pytest.raises(BudgetLedgerError, match="BUDGET_TENANT_TOKENS_EXHAUSTED"):
        reserve(scope, port)
    assert not journal(owner)


def test_scope_arguments_cannot_redirect_preallocation(scope: BudgetScope) -> None:
    owner, _, _, _, ids, _ = scope
    port = prepare(scope)
    for tenant, run in [(scope_id(ids, "tenant_b"), None), (None, uuid4())]:
        with pytest.raises(BudgetLedgerError, match="BUDGET_RUN_SCOPE_INVALID"):
            reserve(scope, port, tenant=tenant, run=run)
    assert not journal(owner)


def test_exact_replay_is_idempotent_but_changed_binding_conflicts(scope: BudgetScope) -> None:
    owner, _, _, _, _, _ = scope
    port = prepare(scope)
    attempt = uuid4()
    body = binding()
    assert reserve(scope, port, attempt=attempt, body=body).changed
    assert not reserve(scope, port, attempt=attempt, body=body).changed
    with pytest.raises(BudgetLedgerError, match="BUDGET_ATTEMPT_CONFLICT"):
        reserve(
            scope, port, attempt=attempt, body=body.model_copy(update={"request_digest": "b" * 64})
        )
    assert len(journal(owner)) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("output_limit", True),
        ("structured_attempt", 4),
        ("request_digest", "bad"),
        ("extra", "x"),
        ("qualified_window", 0),
    ],
)
def test_sql_rejects_unvalidated_binding(scope: BudgetScope, field: str, value: object) -> None:
    owner, agent, store, _, _, _ = scope
    prepare(scope)
    body = binding().model_dump(mode="json")
    body[field] = value
    with agent.begin() as connection:
        store.bind(connection)
        denied(
            connection,
            "SELECT cehub_ai.agent_reserve_model_budget(:a,10,CAST(:body AS jsonb))",
            dict(a=uuid4(), body=json.dumps(body)),
            sqlstate="22023",
        )
    assert not journal(owner)


@pytest.mark.parametrize(
    "setting", ["pdos.tenant_id", "pdos.agent_run_id", "pdos.project_id", "pdos.agent_lease_token"]
)
def test_raw_forged_scope_cannot_reserve(scope: BudgetScope, setting: str) -> None:
    owner, agent, store, _, _, _ = scope
    prepare(scope)
    with agent.begin() as connection:
        store.bind(connection)
        connection.execute(
            text("SELECT set_config(:key,:value,true)"), dict(key=setting, value=str(uuid4()))
        )
        denied(
            connection,
            "SELECT cehub_ai.agent_reserve_model_budget(:a,10,CAST(:body AS jsonb))",
            dict(a=uuid4(), body=json.dumps(binding().model_dump(mode="json"))),
        )
    assert not journal(owner)


def test_agent_cannot_call_common_accounting_reservation_or_write_limits(
    scope: BudgetScope,
) -> None:
    _, agent, store, claim, ids, _ = scope
    prepare(scope)
    with agent.begin() as connection:
        store.bind(connection)
        denied(
            connection,
            "SELECT * FROM cehub_ai.unbound_model_usage(:t,clock_timestamp())",
            dict(t=scope_id(ids, "tenant_a")),
        )
        denied(
            connection,
            "SELECT cehub_ai.reserve_run_budget(:t,:r,:a,'model',10,20,999999,NULL)",
            dict(t=scope_id(ids, "tenant_a"), r=claim.id, a=uuid4()),
        )
        denied(
            connection, "UPDATE cehub_ai.tenant_model_settings SET daily_token_budget=999999", {}
        )
        denied(connection, "SELECT * FROM cehub_ai.budget_lineages", {})
        denied(connection, "INSERT INTO cehub_ai.budget_run_links DEFAULT VALUES", {})


def test_current_model_selection_is_rechecked(scope: BudgetScope) -> None:
    owner, _, _, _, _, _ = scope
    port = prepare(scope)
    with owner.begin() as connection:
        connection.execute(update(tables.tenant_model_settings).values(model="changed-model"))
    with pytest.raises(BudgetLedgerError, match="BUDGET_MODEL_SELECTION_CHANGED"):
        reserve(scope, port)
    assert not journal(owner)


def test_owner_and_agent_compete_for_one_tenant_balance(scope: BudgetScope) -> None:
    owner, _, store, claim, ids, _ = scope
    port = prepare(scope, daily=40)
    with owner.begin() as connection:
        original = dict(
            connection.execute(select(tables.agent_runs).where(tables.agent_runs.c.id == claim.id))
            .mappings()
            .one()
        )
        other = uuid4()
        connection.execute(
            tables.agent_runs.insert(),
            {
                **original,
                "id": other,
                "window_started_at": original["window_started_at"] + timedelta(days=1),
                "window_ended_at": original["window_ended_at"] + timedelta(days=1),
            },
        )
    ledger = BudgetLedger(owner)
    ledger.open_lineage(tenant_id=scope_id(ids, "tenant_a"), run_id=other, profile=profile())
    barrier = Barrier(2)

    def compete(service: bool) -> bool | str:
        with store.scope(claim):
            barrier.wait()
            try:
                return reserve(
                    scope, ledger if service else port, run=other if service else claim.id
                ).changed
            except BudgetLedgerError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        result = list(executor.map(compete, [True, False]))
    assert result.count(True) == 1 and "BUDGET_TENANT_TOKENS_EXHAUSTED" in result
    assert len(journal(owner)) == 1


def test_restricted_gateway_reserves_dispatches_settles_and_closes_trace(
    scope: BudgetScope,
) -> None:
    owner, _, _, _, _, _ = scope
    port = prepare(scope)
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return response()

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        service = gateway(scope, port, client)
        inv = call(scope)
        result = service.invoke_structured(inv, RiskOutput)
        replay = service.invoke_structured(inv, RiskOutput)
    assert result.status == "succeeded" and len(requests) == 1, result
    assert replay.error_code == "BUDGET_ATTEMPT_ALREADY_DISPATCHED"
    rows = journal(owner)
    assert [row["revision"] for row in rows] == [1, 2, 3]
    assert rows[-1]["charged_tokens"] == 10 and rows[-1]["held_tokens"] == 0
    with owner.connect() as connection:
        trace = (
            connection.execute(
                select(tables.model_invocations).where(
                    tables.model_invocations.c.id == result.invocation_id
                )
            )
            .mappings()
            .one()
        )
        sessions = list(connection.execute(select(tables.model_call_sessions)).mappings())
    assert trace["budget_call_id"] == inv.model_call_id and trace["usage_status"] == "known"
    assert all(row["execution_mode"] == "budgeted" for row in sessions)


def test_lost_response_holds_budget_and_never_retries_on_new_call_id(scope: BudgetScope) -> None:
    owner, _, _, _, _, _ = scope
    port = prepare(scope)
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        raise httpx2.ReadTimeout("synthetic")

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        service = gateway(scope, port, client)
        first = service.invoke_structured(call(scope), RiskOutput)
        again = service.invoke_structured(call(scope), RiskOutput)
    assert first.status == "degraded" and again.error_code == "BUDGET_LINEAGE_CALL_BUSY"
    assert len(requests) == 1
    assert journal(owner)[-1]["reservation_status"] == "unknown"
    assert journal(owner)[-1]["held_tokens"] == 30


def test_restricted_budgeted_gateway_crosses_real_local_http(scope: BudgetScope) -> None:
    class Output(BaseModel):
        label: str

    owner, _, _, _, _, _ = scope
    port = prepare(scope)
    with fake_provider() as base, httpx2.Client(trust_env=False) as client:
        configured = ModelCatalog.from_environment(
            {
                "PDOS_LLM_API_KEY": "synthetic",
                "PDOS_LLM_BASE_URL": f"{base}/openai/v1",
                "PDOS_LLM_MODEL": "MiniMax-M2.7",
            }
        )
        result = gateway(scope, port, client, model_catalog=configured).invoke_structured(
            call(scope, Output), Output
        )
    assert result.status == "succeeded"
    assert result.output is not None
    assert result.output.label == "high"
    assert len(FakeProviderHandler.requests) == 1
    assert FakeProviderHandler.requests[0][2]["max_completion_tokens"] == 20
    assert journal(owner)[-1]["charged_tokens"] == 10


def test_drain_rejects_new_reservations_from_both_ports(scope: BudgetScope) -> None:
    from app.ai.model_call_fence import ModelCallModeService

    owner, _, _, _, ids, admin = scope
    port = prepare(scope)
    modes = ModelCallModeService(owner)
    modes.change(
        tenant_id=scope_id(ids, "tenant_a"),
        actor_user_id=admin,
        expected_revision=0,
        action="request",
        target="budgeted",
        evidence_ref="synthetic",
    )
    for candidate in (port, BudgetLedger(owner)):
        with pytest.raises(BudgetLedgerError, match="BUDGET_ADMISSION_DRAINING"):
            reserve(scope, candidate)
    assert not journal(owner)
    modes.change(
        tenant_id=scope_id(ids, "tenant_a"),
        actor_user_id=admin,
        expected_revision=1,
        action="cancel",
        evidence_ref="synthetic",
    )
    assert reserve(scope, port).changed
