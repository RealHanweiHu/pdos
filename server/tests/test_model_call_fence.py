"""Real PostgreSQL admission races, drain recovery, and zero-call denials."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from typing import Literal, Never, NoReturn
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text, update
from sqlalchemy.exc import DBAPIError

from app.ai.budget_accounting import LegacyUsageEvidence, LegacyUsageReconciler
from app.ai.budget_ledger import BudgetLedger
from app.ai.model_call_fence import ModelCallFence, ModelCallFenceError, ModelCallModeService
from app.db.schema import tables
from tests.test_budget_ledger import SERVER_ROOT, profile
from tests.test_budget_ledger import ledger_db as ledger_db
from tests.test_model_budget_controller import LedgerDatabase, controller, gateway, response
from tests.test_model_gateway import RiskOutput, invocation


@pytest.fixture(autouse=True)
def tenant_owner(ledger_db: LedgerDatabase) -> None:
    engine, tenant, _ = ledger_db
    with engine.begin() as c:
        user_id = uuid4()
        c.execute(
            tables.users.insert(),
            dict(
                id=user_id,
                tenant_id=tenant,
                username=str(user_id),
                email=f"{user_id}@synthetic.test",
                display_name="Synthetic Owner",
                role="owner",
            ),
        )


def actor(engine: Engine, tenant: UUID) -> UUID:
    with engine.connect() as c:
        value = (
            c.execute(
                select(tables.users.c.id).where(
                    tables.users.c.tenant_id == tenant, tables.users.c.role.in_(["owner", "admin"])
                )
            )
            .scalars()
            .first()
        )

    assert isinstance(value, UUID)
    return value


def change(
    engine: Engine,
    tenant: UUID,
    *,
    revision: int = 0,
    action: Literal["request", "complete", "cancel"] = "request",
    target: Literal["compatibility", "budgeted"] = "budgeted",
) -> int:
    return ModelCallModeService(engine).change(
        tenant_id=tenant,
        actor_user_id=actor(engine, tenant),
        expected_revision=revision,
        action=action,
        target=target if action == "request" else None,
        evidence_ref="synthetic-tested-adoption",
    )


def begin(engine: Engine, tenant: UUID, *, budgeted: bool = False, **kwargs: Never) -> UUID:
    return ModelCallFence(engine).begin(
        tenant_id=tenant,
        run_id=None,
        project_id=None,
        agent_key="project_intelligence",
        budgeted=budgeted,
        **kwargs,
    )


def trace(
    engine: Engine,
    tenant: UUID,
    session: UUID,
    *,
    status: str = "known",
    agent: str = "project_intelligence",
) -> UUID:
    trace_id = uuid4()
    with engine.begin() as c:
        c.execute(
            tables.model_invocations.insert(),
            dict(
                id=trace_id,
                tenant_id=tenant,
                model_call_session_id=session,
                agent_key=agent,
                prompt_version="synthetic",
                provider="minimax",
                model="MiniMax-M2.7",
                protocol="openai-compatible",
                status="succeeded" if status == "known" else "provider_error",
                input_tokens=7,
                output_tokens=3,
                total_tokens=10,
                usage_status=status,
                input_meter_version="normalized_input.v1",
                structured_attempts=1,
                cost_status="unknown",
            ),
        )
    return trace_id


def states(engine: Engine) -> list[str]:
    with engine.connect() as c:
        return list(
            c.execute(
                select(tables.model_call_events.c.state).order_by(
                    tables.model_call_events.c.created_at
                )
            ).scalars()
        )


def test_whole_invocation_drains_across_structured_retry(ledger_db: LedgerDatabase) -> None:
    engine, tenant, _ = ledger_db
    entered, release = Event(), Event()
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        if len(calls) == 1:
            entered.set()
            assert release.wait(15)
            return response("invalid-json")
        return response()

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        runtime = gateway(engine, client, None)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(runtime.invoke_structured, invocation(tenant), RiskOutput)
            try:
                assert entered.wait(15)
                assert change(engine, tenant) == 1
                denied = runtime.invoke_structured(invocation(tenant), RiskOutput)
                assert denied.error_code == "MODEL_CALL_DRAINING"
                assert denied.structured_attempts == 0 and len(calls) == 1
                with pytest.raises(ModelCallFenceError, match="IN_FLIGHT"):
                    change(engine, tenant, revision=1, action="complete")
            finally:
                release.set()
            result = future.result(timeout=15)
    assert result.status == "succeeded" and result.structured_attempts == 2
    assert states(engine) == ["open", "closed"]
    assert change(engine, tenant, revision=1, action="complete") == 2
    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        denied = gateway(engine, client, None).invoke_structured(invocation(tenant), RiskOutput)
    assert denied.error_code == "MODEL_CALL_BUDGET_REQUIRED" and len(calls) == 2


def test_budgeted_gateway_still_runs_after_adoption(ledger_db: LedgerDatabase) -> None:
    engine, tenant, runs = ledger_db
    change(engine, tenant)
    change(engine, tenant, revision=1, action="complete")
    with httpx2.Client(transport=httpx2.MockTransport(lambda _: response())) as client:
        result = gateway(engine, client, controller(engine)).invoke_structured(
            invocation(tenant, run_id=runs[0], model_call_id=uuid4()), RiskOutput
        )
    assert result.status == "succeeded"
    assert states(engine) == ["open", "closed"]


def test_exception_and_crash_never_expire_session(ledger_db: LedgerDatabase) -> None:
    engine, tenant, _ = ledger_db

    def fail(_: httpx2.Request) -> NoReturn:
        raise RuntimeError("interrupted-wire")

    with (
        httpx2.Client(transport=httpx2.MockTransport(fail)) as client,
        pytest.raises(RuntimeError, match="interrupted-wire"),
    ):
        gateway(engine, client, None).invoke_structured(invocation(tenant), RiskOutput)
    assert states(engine) == ["open", "unknown"]
    # A distinct crash can leave only the initial record. Neither gets timed out.
    begin(engine, tenant)
    change(engine, tenant)
    with pytest.raises(ModelCallFenceError, match="IN_FLIGHT"):
        change(engine, tenant, revision=1, action="complete")
    assert change(engine, tenant, revision=1, action="cancel") == 2
    assert states(engine) == ["open", "unknown", "open"]


def test_trace_commit_survives_finish_failure_and_can_be_recovered(
    ledger_db: LedgerDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, _ = ledger_db
    with httpx2.Client(transport=httpx2.MockTransport(lambda _: response())) as client:
        runtime = gateway(engine, client, None)

        def fail(**_: object) -> NoReturn:
            raise RuntimeError("finish-write-failed")

        monkeypatch.setattr(runtime._call_fence, "finish", fail)
        with pytest.raises(RuntimeError, match="finish-write-failed"):
            runtime.invoke_structured(invocation(tenant), RiskOutput)
    with engine.connect() as c:
        saved = c.execute(select(tables.model_invocations)).mappings().one()
    assert states(engine) == ["open", "unknown"]
    fence = ModelCallFence(engine)
    kwargs = dict(
        tenant_id=tenant, session_id=saved["model_call_session_id"], invocation_id=saved["id"]
    )
    fence.finish(**kwargs)
    fence.finish(**kwargs)
    assert states(engine) == ["open", "unknown", "closed"]
    change(engine, tenant)
    change(engine, tenant, revision=1, action="complete")


def test_persist_failure_is_conservative_and_next_call_does_not_reuse_context(
    ledger_db: LedgerDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, _ = ledger_db
    with httpx2.Client(transport=httpx2.MockTransport(lambda _: response())) as client:
        runtime = gateway(engine, client, None)
        original = runtime._record

        def fail(*args: object, **kwargs: object) -> NoReturn:
            raise RuntimeError("trace-failed")

        monkeypatch.setattr(runtime, "_record", fail)
        with pytest.raises(RuntimeError, match="trace-failed"):
            runtime.invoke_structured(invocation(tenant), RiskOutput)
        monkeypatch.setattr(runtime, "_record", original)
        runtime.invoke_structured(invocation(tenant), RiskOutput)
    assert states(engine) == ["open", "unknown", "open", "closed"]


def test_unknown_provider_usage_blocks_switch_even_after_trace_closes_call(
    ledger_db: LedgerDatabase,
) -> None:
    engine, tenant, _ = ledger_db

    def failed(request: httpx2.Request) -> NoReturn:
        raise httpx2.ReadTimeout("synthetic-timeout", request=request)

    with httpx2.Client(transport=httpx2.MockTransport(failed)) as client:
        result = gateway(engine, client, None).invoke_structured(invocation(tenant), RiskOutput)
    assert result.status == "degraded" and states(engine) == ["open", "closed"]
    change(engine, tenant)
    with pytest.raises(ModelCallFenceError, match="USAGE_UNRESOLVED"):
        change(engine, tenant, revision=1, action="complete")
    assert result.invocation_id is not None
    LegacyUsageReconciler(engine).reconcile(
        tenant_id=tenant,
        invocation_id=result.invocation_id,
        reviewer_user_id=actor(engine, tenant),
        evidence=LegacyUsageEvidence(
            evidence_ref="synthetic-provider-confirmation", input_tokens=7, output_tokens=3
        ),
    )
    change(engine, tenant, revision=1, action="complete")


def test_pending_budget_reservation_blocks_forward_and_reverse_transition(
    ledger_db: LedgerDatabase,
) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    ledger.open_lineage(tenant_id=tenant, run_id=runs[0], profile=profile())
    attempt = uuid4()
    ledger.reserve(
        tenant_id=tenant,
        run_id=runs[0],
        attempt_id=attempt,
        call_kind="model",
        input_tokens=7,
        output_tokens=3,
        tenant_daily_token_limit=1000,
    )
    change(engine, tenant)
    with pytest.raises(ModelCallFenceError, match="BUDGET_UNRESOLVED"):
        change(engine, tenant, revision=1, action="complete")
    ledger.transition(tenant_id=tenant, attempt_id=attempt, action="cancel")
    change(engine, tenant, revision=1, action="complete")
    session = begin(engine, tenant, budgeted=True)
    change(engine, tenant, revision=2, target="compatibility")
    with pytest.raises(ModelCallFenceError, match="IN_FLIGHT"):
        change(engine, tenant, revision=3, action="complete")
    ModelCallFence(engine).finish(
        tenant_id=tenant, session_id=session, invocation_id=trace(engine, tenant, session)
    )
    change(engine, tenant, revision=3, action="complete")
    begin(engine, tenant)


def test_mode_changes_require_current_authorized_actor_and_revision(
    ledger_db: LedgerDatabase,
) -> None:
    engine, tenant, _ = ledger_db
    service = ModelCallModeService(engine)
    with pytest.raises(ModelCallFenceError, match="FORBIDDEN"):
        service.change(
            tenant_id=tenant,
            actor_user_id=uuid4(),
            expected_revision=0,
            action="request",
            target="budgeted",
            evidence_ref="synthetic",
        )
    change(engine, tenant)
    with pytest.raises(ModelCallFenceError, match="REVISION_CONFLICT"):
        change(engine, tenant)
    with engine.begin() as c:
        c.execute(
            update(tables.users)
            .where(tables.users.c.id == actor(engine, tenant))
            .values(is_active=False)
        )
    with pytest.raises(ModelCallFenceError, match="FORBIDDEN"):
        change(engine, tenant, revision=1, action="cancel")


@pytest.mark.parametrize("invalid", ["other-session", "other-agent", "other-trace", "other-tenant"])
def test_finish_requires_exact_scope_and_trace_binding(
    ledger_db: LedgerDatabase, invalid: str
) -> None:
    engine, tenant, _ = ledger_db
    session = begin(engine, tenant)
    trace_id = trace(
        engine,
        tenant,
        begin(engine, tenant) if invalid == "other-session" else session,
        agent="knowledge_lite" if invalid == "other-agent" else "project_intelligence",
    )
    with pytest.raises(DBAPIError):
        ModelCallFence(engine).finish(
            tenant_id=uuid4() if invalid == "other-tenant" else tenant,
            session_id=session,
            invocation_id=uuid4() if invalid == "other-trace" else trace_id,
        )
    assert "closed" not in states(engine)


def test_begin_and_drain_race_has_no_admission_gap(ledger_db: LedgerDatabase) -> None:
    engine, tenant, _ = ledger_db
    barrier = Barrier(2)

    def begin_racing() -> UUID | None:
        barrier.wait(timeout=10)
        try:
            return begin(engine, tenant)
        except ModelCallFenceError as error:
            assert error.code == "MODEL_CALL_DRAINING"
            return None

    def drain_racing() -> int:
        barrier.wait(timeout=10)
        return change(engine, tenant)

    with ThreadPoolExecutor(max_workers=2) as pool:
        opened, drained = pool.submit(begin_racing), pool.submit(drain_racing)
        session = opened.result(timeout=15)
        assert drained.result(timeout=15) == 1
    if session is not None:
        with pytest.raises(ModelCallFenceError, match="IN_FLIGHT"):
            change(engine, tenant, revision=1, action="complete")
    else:
        change(engine, tenant, revision=1, action="complete")
    with pytest.raises(ModelCallFenceError, match="DRAINING|BUDGET_REQUIRED"):
        begin(engine, tenant)


def test_history_is_append_only_and_downgrade_refuses_data(ledger_db: LedgerDatabase) -> None:
    engine, tenant, _ = ledger_db
    with engine.connect() as c:
        original_head = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    begin(engine, tenant)
    change(engine, tenant)
    for name in ("model_call_sessions", "model_call_events", "model_call_mode_events"):
        with pytest.raises(DBAPIError), engine.begin() as c:
            c.execute(text(f"DELETE FROM cehub_ai.{name}"))
    with pytest.raises(RuntimeError, match="fence history exists"):
        command.downgrade(Config(str(SERVER_ROOT / "alembic.ini")), "0063_legacy_usage_accounting")
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == original_head
        )


def test_empty_fence_migration_roundtrip(ledger_db: LedgerDatabase) -> None:
    command.downgrade(Config(str(SERVER_ROOT / "alembic.ini")), "0063_legacy_usage_accounting")
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")


def test_unavailable_fence_prevents_wire_and_never_falls_back(
    ledger_db: LedgerDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, _ = ledger_db
    calls: list[httpx2.Request] = []

    def unexpected_call(request: httpx2.Request) -> NoReturn:
        calls.append(request)
        pytest.fail("unavailable fence reached provider")

    with httpx2.Client(transport=httpx2.MockTransport(unexpected_call)) as client:
        runtime = gateway(engine, client, None)

        def unavailable(**_: object) -> NoReturn:
            raise RuntimeError("admission-database-unavailable")

        monkeypatch.setattr(runtime._call_fence, "begin", unavailable)
        with pytest.raises(RuntimeError, match="admission-database-unavailable"):
            runtime.invoke_structured(invocation(tenant), RiskOutput)
    assert calls == [] and states(engine) == []


def test_interruption_and_failed_unknown_write_leave_initial_hold(
    ledger_db: LedgerDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, _ = ledger_db

    def interrupted(_: httpx2.Request) -> NoReturn:
        raise KeyboardInterrupt()

    with httpx2.Client(transport=httpx2.MockTransport(interrupted)) as client:
        runtime = gateway(engine, client, None)

        def failed_recovery(**_: object) -> NoReturn:
            raise RuntimeError("recovery-database-unavailable")

        monkeypatch.setattr(runtime._call_fence, "unknown", failed_recovery)
        with pytest.raises(KeyboardInterrupt):
            runtime.invoke_structured(invocation(tenant), RiskOutput)
    assert states(engine) == ["open"]
    change(engine, tenant)
    with pytest.raises(ModelCallFenceError, match="IN_FLIGHT"):
        change(engine, tenant, revision=1, action="complete")


def test_shared_gateway_concurrent_sessions_link_only_their_own_trace(
    ledger_db: LedgerDatabase,
) -> None:
    engine, tenant, _ = ledger_db
    barrier = Barrier(2)

    def handler(_: httpx2.Request) -> httpx2.Response:
        barrier.wait(timeout=10)
        return response()

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        runtime = gateway(engine, client, None)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(runtime.invoke_structured, invocation(tenant), RiskOutput)
                for _ in range(2)
            ]
            results = [f.result(timeout=15) for f in futures]
    assert all(r.status == "succeeded" for r in results)
    with engine.connect() as c:
        traces = list(c.execute(select(tables.model_invocations)).mappings())
        closed = list(
            c.execute(
                select(tables.model_call_events).where(tables.model_call_events.c.state == "closed")
            ).mappings()
        )
    assert len({r["model_call_session_id"] for r in traces}) == 2
    assert {r["id"]: r["model_call_session_id"] for r in traces} == {
        r["invocation_id"]: r["session_id"] for r in closed
    }
