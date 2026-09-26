"""Compatibility calls and budget reservations cannot overlap before usage is visible."""

from __future__ import annotations

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Barrier, Event, Thread
from uuid import uuid4

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text

from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError
from app.ai.egress import ProviderEgressPolicy
from app.ai.gateway import StructuredModelGateway
from app.ai.model_call_fence import ModelCallFence, ModelCallFenceError
from app.ai.model_catalog import ModelCatalog, ProtocolKind
from app.ai.provider_adapters import OpenAICompatibleAdapter
from app.db.schema import tables
from app.domain.model_governance import ModelGovernanceService
from tests.test_budget_ledger import SERVER_ROOT, profile, reserve, settle
from tests.test_budget_ledger import ledger_db as ledger_db
from tests.test_model_budget_controller import LedgerDatabase, controller
from tests.test_model_call_fence import begin, trace
from tests.test_model_gateway import RiskOutput, invocation, qualification


@contextmanager
def held_provider() -> Iterator[tuple[str, Event, Event, list[object]]]:
    entered, release = Event(), Event()
    requests: list[object] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            requests.append(json.loads(self.rfile.read(int(self.headers["content-length"]))))
            entered.set()
            if not release.wait(15):
                self.send_error(500)
                return
            payload = json.dumps(
                {
                    "id": "synthetic-wire",
                    "choices": [{"message": {"content": '{"risk":"low"}'}}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 3},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", entered, release, requests
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def runtime(
    engine: Engine, client: httpx2.Client, url: str, *, budgeted: bool, limit: int = 35
) -> StructuredModelGateway:
    catalog = ModelCatalog.from_environment(
        {
            "PDOS_LLM_PROVIDER": "minimax",
            "PDOS_LLM_BASE_URL": url,
            "PDOS_LLM_API_KEY": "synthetic-only",
            "PDOS_LLM_MODEL": "MiniMax-M2.7",
        }
    )
    return StructuredModelGateway(
        engine,
        catalog=catalog,
        qualifications=[qualification()],
        governance=ModelGovernanceService(
            engine,
            catalog=catalog,
            qualifications=[qualification()],
            default_daily_token_budget=limit,
        ),
        adapters={
            ProtocolKind.OPENAI_COMPATIBLE: OpenAICompatibleAdapter(
                client, ProviderEgressPolicy.from_catalog(catalog)
            )
        },
        rate_cards={},
        budget_controller=controller(engine) if budgeted else None,
    )


@pytest.mark.parametrize("first_budgeted", [False, True])
def test_real_http_calls_cannot_cross_accounting_modes_in_flight(
    ledger_db: LedgerDatabase, first_budgeted: bool
) -> None:
    engine, tenant, runs = ledger_db
    with (
        held_provider() as (url, entered, release, requests),
        httpx2.Client(trust_env=False, follow_redirects=False) as client,
    ):
        first = runtime(engine, client, url, budgeted=first_budgeted)
        second = runtime(engine, client, url, budgeted=not first_budgeted)
        inv = invocation(tenant, run_id=runs[0], model_call_id=uuid4())
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(first.invoke_structured, inv, RiskOutput)
            try:
                assert entered.wait(15)
                denied = second.invoke_structured(
                    invocation(tenant, run_id=runs[1], model_call_id=uuid4()), RiskOutput
                )
                assert denied.error_code == (
                    "MODEL_CALL_BUDGET_IN_FLIGHT"
                    if first_budgeted
                    else "MODEL_CALL_LEGACY_IN_FLIGHT"
                )
                assert denied.structured_attempts == 0 and len(requests) == 1
            finally:
                release.set()
            assert future.result(timeout=15).status == "succeeded"
        after = second.invoke_structured(
            invocation(tenant, run_id=runs[1], model_call_id=uuid4()), RiskOutput
        )
        if first_budgeted:
            assert after.status == "succeeded" and len(requests) == 2
        else:
            # The old result now costs 10 tokens. A new 30-token reservation
            # exceeds 35, proving closed traces participate before admission.
            assert after.error_code == "BUDGET_TENANT_TOKENS_EXHAUSTED"
            assert len(requests) == 1
    with engine.connect() as c:
        denied_trace = (
            c.execute(
                select(tables.model_invocations).where(
                    tables.model_invocations.c.id == denied.invocation_id
                )
            )
            .mappings()
            .one()
        )
    assert denied_trace["usage_status"] == "not_invoked"
    assert denied_trace["model_call_session_id"] is None


@pytest.mark.parametrize("unknown", [False, True])
def test_direct_ledger_admission_rejects_legacy_until_exact_trace_closes(
    ledger_db: LedgerDatabase, unknown: bool
) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile())
    session = begin(engine, tenant)
    if unknown:
        ModelCallFence(engine).unknown(tenant_id=tenant, session_id=session)
    trace_id = trace(engine, tenant, session)
    # Even a committed trace is insufficient until its in-flight marker closes.
    with pytest.raises(BudgetLedgerError, match="LEGACY_CALL_IN_FLIGHT"):
        reserve(ledger, tenant, runs[0])
    with pytest.raises(ModelCallFenceError, match="LEGACY_IN_FLIGHT"):
        begin(engine, tenant, budgeted=True)
    ModelCallFence(engine).finish(tenant_id=tenant, session_id=session, invocation_id=trace_id)
    assert reserve(ledger, tenant, runs[0]).changed


@pytest.mark.parametrize("status", ["reserved", "unknown", "settled", "cancelled"])
def test_legacy_checks_latest_direct_budget_hold_without_session(
    ledger_db: LedgerDatabase, status: str
) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile())
    receipt = reserve(ledger, tenant, runs[0])
    attempt = receipt.entry.attempt_id
    if status == "unknown":
        ledger.transition(tenant_id=tenant, attempt_id=attempt, action="dispatch")
        ledger.transition(tenant_id=tenant, attempt_id=attempt, action="unknown")
    elif status == "settled":
        settle(ledger, tenant, attempt)
    elif status == "cancelled":
        ledger.transition(tenant_id=tenant, attempt_id=attempt, action="cancel")
    if status in {"reserved", "unknown"}:
        with pytest.raises(ModelCallFenceError, match="BUDGET_IN_FLIGHT"):
            begin(engine, tenant)
    else:
        assert begin(engine, tenant)


def test_other_tenant_and_same_mode_are_independent(ledger_db: LedgerDatabase) -> None:
    engine, tenant, _ = ledger_db
    other = uuid4()
    with engine.begin() as c:
        c.execute(tables.tenants.insert(), dict(id=other, slug=str(other), name="Synthetic"))
    begin(engine, tenant)
    begin(engine, tenant)
    begin(engine, other, budgeted=True)
    begin(engine, other, budgeted=True)
    with pytest.raises(ModelCallFenceError, match="BUDGET_IN_FLIGHT"):
        begin(engine, other)


def test_unknown_budgeted_session_blocks_legacy_even_without_reservation(
    ledger_db: LedgerDatabase,
) -> None:
    engine, tenant, _ = ledger_db
    session = begin(engine, tenant, budgeted=True)
    ModelCallFence(engine).unknown(tenant_id=tenant, session_id=session)
    with pytest.raises(ModelCallFenceError, match="BUDGET_IN_FLIGHT"):
        begin(engine, tenant)
    ModelCallFence(engine).finish(
        tenant_id=tenant, session_id=session, invocation_id=trace(engine, tenant, session)
    )
    begin(engine, tenant)


@pytest.mark.parametrize("use_direct_ledger", [False, True])
def test_simultaneous_mixed_admission_has_exactly_one_winner(
    ledger_db: LedgerDatabase, use_direct_ledger: bool
) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile())
    barrier = Barrier(2)

    def legacy() -> bool:
        barrier.wait(timeout=10)
        try:
            begin(engine, tenant)
            return True
        except ModelCallFenceError as error:
            assert error.code == "MODEL_CALL_BUDGET_IN_FLIGHT"
            return False

    def budgeted() -> bool:
        barrier.wait(timeout=10)
        try:
            if use_direct_ledger:
                reserve(ledger, tenant, runs[0])
            else:
                begin(engine, tenant, budgeted=True)
            return True
        except (ModelCallFenceError, BudgetLedgerError) as error:
            assert error.code in {"MODEL_CALL_LEGACY_IN_FLIGHT", "BUDGET_LEGACY_CALL_IN_FLIGHT"}
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(legacy), pool.submit(budgeted)
        assert sum([a.result(timeout=15), b.result(timeout=15)]) == 1


def test_migration_roundtrip_and_history_guard(ledger_db: LedgerDatabase) -> None:
    engine, tenant, _ = ledger_db
    with engine.connect() as c:
        original_head = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0064_model_call_fence")
    command.upgrade(config, "head")
    begin(engine, tenant)
    with pytest.raises(RuntimeError, match="model call fence history"):
        command.downgrade(config, "0064_model_call_fence")
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == original_head
        )
