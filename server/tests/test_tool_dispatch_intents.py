"""Real restricted roles and actual factory; no external model or embedding requests."""

from __future__ import annotations

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import NoReturn, TypedDict
from uuid import UUID, uuid4, uuid5

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.ai import runtime_factory
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError, BudgetReceipt
from app.ai.lease_heartbeat import AgentLeaseLostError
from app.ai.observations import AgentObservationError, AgentObservations
from app.ai.run_store import ClaimedAgentRun, RestrictedAgentRunStore
from app.ai.runtime_contract import FrozenRunContext
from app.ai.tools import AgentReadTools, ProjectContextResult, ToolPage
from app.db.schema import tables
from app.worker.dispatcher import AgentDispatcher
from tests.test_agent_checkpoints import CheckpointSetup, crash_after_result, expire, scope_id
from tests.test_agent_checkpoints import setup as setup
from tests.test_agent_database_security import SECURITY_TEMPLATE, SERVER_ROOT
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)
from tests.test_event_budget_adoption import event_scope as event_scope
from tests.test_model_budget_controller import evidence, rows
from tests.test_tool_observation_receipts import row_uuid


class PrepareOverrides(TypedDict, total=False):
    tool: str
    args: dict[str, object]
    call: UUID


@contextmanager
def active(setup: CheckpointSetup) -> Iterator[tuple[ClaimedAgentRun, AgentObservations]]:
    _, _, agent, _, _, _, _ = setup
    store = RestrictedAgentRunStore(agent)
    claim = store.claim(started_at=datetime.now(UTC))
    assert claim is not None
    with store.scope(claim):
        yield claim, AgentObservations(agent, store)


def prepare(
    port: AgentObservations,
    claim: ClaimedAgentRun,
    key: str,
    *,
    tool: str = "get_project_context",
    args: dict[str, object] | None = None,
    call: UUID | None = None,
) -> UUID:
    result = port._call(
        "SELECT cehub_ai.prepare_agent_tool_call(:call,:key,:tool,:args)",
        call=call or uuid5(claim.id, key),
        key=key,
        tool=tool,
        args=json.dumps(args or {"project_id": str(claim.values["project_id"])}),
    )
    assert isinstance(result, UUID)
    return result


@pytest.mark.parametrize("fill", [0, 4, 6])
def test_actual_handler_sees_committed_intent_and_quota_blocks_before_memory(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch, fill: int
) -> None:
    owner, _, _, _, env, calls, _ = setup
    original = AgentReadTools.get_project_context
    memory_calls: list[int] = []
    memory = AgentReadTools.search_memory
    with runtime_factory.configured_agent_runtime(env) as runtime:

        def check_before_handler(self: AgentReadTools, *, project_id: UUID) -> ProjectContextResult:
            intents = rows(owner, tables.agent_tool_intents)
            dispatches = rows(owner, tables.agent_tool_dispatches)
            assert len(intents) == len(dispatches) == 1
            assert dispatches[0]["intent_id"] == intents[0]["id"]
            assert not rows(owner, tables.agent_tool_observations)
            port = runtime.executor._observations
            assert port is not None
            for i in range(fill):
                port.prepare(
                    context=self._context,
                    call_key=f"reserved.{i}",
                    tool_key="get_project_context",
                    arguments={"project_id": str(project_id)},
                )
            return original(self, project_id=project_id)

        def count_memory(
            self: AgentReadTools, *, project_id: UUID, query: str, offset: int = 0, limit: int = 20
        ) -> ToolPage:
            memory_calls.append(1)
            return memory(self, project_id=project_id, query=query, offset=offset, limit=limit)

        monkeypatch.setattr(AgentReadTools, "get_project_context", check_before_handler)
        monkeypatch.setattr(AgentReadTools, "search_memory", count_memory)
        result = runtime.executor.execute_next()
    if fill == 6:
        assert result.error_code == "BUDGET_TOOL_CALL_COUNT_EXHAUSTED"
        assert calls == [] and memory_calls == []
        assert len(rows(owner, tables.agent_tool_dispatches)) == 2
    else:
        assert result.status == "succeeded", result
        assert len(calls) == len(memory_calls) == 1
    observations = rows(owner, tables.agent_tool_observations)
    for row in observations:
        assert str(row["tool_intent_id"]) == evidence(row["metadata"])["tool_call_id"]
    assert len(rows(owner, tables.agent_tool_intents)) == (4 + fill if fill < 6 else 8)


@pytest.mark.parametrize("change", ["same", "arguments", "tool", "call_id", "scope"])
def test_prepare_idempotency_and_frozen_call_identity(setup: CheckpointSetup, change: str) -> None:
    owner, _, _, ids, _, _, _ = setup
    with active(setup) as (claim, port):
        first = prepare(port, claim, "one")
        kw: PrepareOverrides = {}
        expected = "CONFLICT"
        if change == "arguments":
            kw["args"] = {"project_id": str(claim.values["project_id"]), "different": True}
        elif change == "tool":
            kw["tool"] = "get_recent_events"
        elif change == "call_id":
            kw["call"] = uuid4()
        elif change == "scope":
            kw["args"] = {"project_id": str(ids["project_b"])}
            expected = "SCOPE"
        if change == "same":
            assert prepare(port, claim, "one") == first
        else:
            with pytest.raises(AgentObservationError, match=expected):
                prepare(port, claim, "one", **kw)
        assert len(rows(owner, tables.agent_tool_intents)) == 1
        port.dispatch(first)
        with pytest.raises(AgentObservationError, match="ALREADY_DISPATCHED"):
            port.dispatch(first)
    assert len(rows(owner, tables.agent_tool_dispatches)) == 1


def test_concurrent_prepare_and_dispatch_grants_only_one_execution(setup: CheckpointSetup) -> None:
    owner, _, agent, _, _, _, _ = setup
    with active(setup) as (claim, _):

        def attempt(_: int) -> str:
            try:
                with agent.begin() as c:
                    c.execute(
                        text("SELECT cehub_ai.bind_agent_scope(:run,:token)"),
                        dict(run=claim.id, token=claim.lease_token),
                    )
                    c.execute(
                        text("SELECT cehub_ai.prepare_agent_tool_call(:call,:key,:tool,:args)"),
                        dict(
                            call=uuid5(claim.id, "same"),
                            key="same",
                            tool="get_project_context",
                            args=json.dumps({"project_id": str(claim.values["project_id"])}),
                        ),
                    )
                with agent.begin() as c:
                    c.execute(
                        text("SELECT cehub_ai.bind_agent_scope(:run,:token)"),
                        dict(run=claim.id, token=claim.lease_token),
                    )
                    c.execute(
                        text("SELECT cehub_ai.dispatch_agent_tool_call(:call)"),
                        dict(call=uuid5(claim.id, "same")),
                    )
                return "granted"
            except DBAPIError as error:
                assert "AGENT_TOOL_ALREADY_DISPATCHED" in str(error)
                return "refused"

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(attempt, range(2))) == ["granted", "refused"]
    assert len(rows(owner, tables.agent_tool_intents)) == 1
    assert len(rows(owner, tables.agent_tool_dispatches)) == 1


def test_concurrent_new_calls_compete_for_last_lineage_slot(setup: CheckpointSetup) -> None:
    owner, _, agent, _, _, _, _ = setup
    with active(setup) as (claim, port):
        for i in range(7):
            prepare(port, claim, f"fill.{i}")

        def attempt(index: int) -> str:
            key = f"race.{index}"
            try:
                with agent.begin() as c:
                    c.execute(
                        text("SELECT cehub_ai.bind_agent_scope(:run,:token)"),
                        dict(run=claim.id, token=claim.lease_token),
                    )
                    c.execute(
                        text("SELECT cehub_ai.prepare_agent_tool_call(:call,:key,:tool,:args)"),
                        dict(
                            call=uuid5(claim.id, key),
                            key=key,
                            tool="get_project_context",
                            args=json.dumps({"project_id": str(claim.values["project_id"])}),
                        ),
                    )
                return "granted"
            except DBAPIError as error:
                assert "BUDGET_TOOL_CALL_COUNT_EXHAUSTED" in str(error)
                return "refused"

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(attempt, range(2))) == ["granted", "refused"]
    assert len(rows(owner, tables.agent_tool_intents)) == 8


def test_actual_handler_result_lost_before_receipt_is_never_redispatched(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, worker, _, _, env, calls, _ = setup
    with runtime_factory.configured_agent_runtime(env) as runtime:

        def crash(
            *,
            context: FrozenRunContext,
            call_key: str,
            tool_key: str,
            arguments: dict[str, object],
            output: dict[str, object],
            error_code: str | None = None,
        ) -> NoReturn:
            expire(owner, context.run_id)
            raise AgentLeaseLostError("synthetic crash after handler")

        monkeypatch.setattr(runtime.executor._observations, "append", crash)
        result = runtime.executor.execute_next()
    assert result.error_code == "AGENT_RUN_LEASE_LOST"
    assert len(rows(owner, tables.agent_tool_dispatches)) == 1
    assert rows(owner, tables.agent_tool_observations) == []
    assert AgentDispatcher(worker).dispatch_once().stopped_run_count == 1
    assert rows(owner, tables.agent_runs)[0]["error_code"] == "AGENT_TOOL_RECEIPT_UNKNOWN"
    with runtime_factory.configured_agent_runtime(env) as runtime:
        assert runtime.executor.execute_next().status == "idle"
    assert calls == []


@pytest.mark.parametrize("invalid", ["unmatched_tool", "missing_intent"])
def test_scope_and_dispatch_admission_fail_before_execution(
    setup: CheckpointSetup, invalid: str
) -> None:
    owner, _, _, _, _, _, _ = setup
    with (
        active(setup) as (claim, port),
        pytest.raises(AgentObservationError, match="TOOL_INTENT_(TOOL_INVALID|MISSING)"),
    ):
        if invalid == "unmatched_tool":
            prepare(port, claim, "forbidden", tool="get_quality_evidence")
        else:
            port.dispatch(uuid4())
    assert rows(owner, tables.agent_tool_intents) == []
    assert rows(owner, tables.agent_tool_dispatches) == []


@pytest.mark.parametrize("when", ["prepared", "dispatched"])
def test_expired_recovery_distinguishes_not_dispatched_from_unknown_receipt(
    setup: CheckpointSetup, when: str
) -> None:
    owner, worker, _, _, env, calls, _ = setup
    with active(setup) as (claim, port):
        call = prepare(port, claim, "crash")
        if when == "dispatched":
            port.dispatch(call)
        expire(owner, claim.id)
        with pytest.raises(AgentLeaseLostError):
            port.dispatch(call)
    before = rows(owner, tables.agent_tool_intents)
    assert AgentDispatcher(worker).dispatch_once().stopped_run_count == 1
    expected = "AGENT_TOOL_RECEIPT_UNKNOWN" if when == "dispatched" else "AGENT_TOOL_NOT_DISPATCHED"
    assert rows(owner, tables.agent_runs)[0]["error_code"] == expected
    assert rows(owner, tables.agent_tool_intents) == before
    with runtime_factory.configured_agent_runtime(env) as runtime:
        assert runtime.executor.execute_next().status == "idle"
    assert calls == []


def test_checkpoint_recovery_does_not_allocate_or_dispatch_tools_again(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, worker, _, _, env, calls, _ = setup
    crash_after_result(setup, monkeypatch)
    before = [rows(owner, t) for t in (tables.agent_tool_intents, tables.agent_tool_dispatches)]
    assert AgentDispatcher(worker).dispatch_once().recovered_run_count == 1
    with runtime_factory.configured_agent_runtime(env) as runtime:
        assert runtime.executor.execute_next().status == "succeeded"
    assert [
        rows(owner, t) for t in (tables.agent_tool_intents, tables.agent_tool_dispatches)
    ] == before
    assert len(calls) == 1


@pytest.mark.parametrize("journal_first", [False, True])
def test_generic_budget_journal_and_handler_intents_share_tool_count(
    setup: CheckpointSetup, journal_first: bool
) -> None:
    owner, _, _, ids, _, _, _ = setup
    ledger = BudgetLedger(owner)
    with active(setup) as (claim, port):

        def reserve() -> BudgetReceipt:
            return ledger.reserve(
                tenant_id=scope_id(ids, "tenant_a"),
                run_id=claim.id,
                attempt_id=uuid4(),
                call_kind="tool",
                input_tokens=1,
                output_tokens=0,
                tenant_daily_token_limit=100000,
            )

        if journal_first:
            reserve()
        for i in range(7 if journal_first else 8):
            prepare(port, claim, f"fill.{i}")
        with pytest.raises(AgentObservationError, match="TOOL_CALL_COUNT_EXHAUSTED"):
            prepare(port, claim, "over")
        if not journal_first:
            with pytest.raises(BudgetLedgerError, match="CALL_COUNT_EXHAUSTED"):
                reserve()


def test_linked_run_inherits_remaining_tool_count(setup: CheckpointSetup) -> None:
    owner, _, agent, ids, _, _, _ = setup
    with active(setup) as (claim, port):
        for i in range(7):
            prepare(port, claim, f"parent.{i}")
        child = dict(
            rows(owner, tables.agent_runs)[0],
            id=uuid4(),
            status="queued",
            started_at=None,
            completed_at=None,
            run_context={},
        )
        start, end = child["window_started_at"], child["window_ended_at"]
        assert isinstance(start, datetime) and isinstance(end, datetime)
        child["window_started_at"] = start + timedelta(days=1)
        child["window_ended_at"] = end + timedelta(days=1)
        with owner.begin() as c:
            c.execute(tables.agent_runs.insert().values(**child))
        lineage = rows(owner, tables.budget_lineages)[0]
        BudgetLedger(owner).link_run(
            tenant_id=scope_id(ids, "tenant_a"),
            lineage_id=row_uuid(lineage, "id"),
            run_id=row_uuid(child, "id"),
        )
        store = RestrictedAgentRunStore(agent)
        second = store.claim(started_at=datetime.now(UTC))
        assert second is not None
        assert second.id == child["id"]
        with store.scope(second):
            second_port = AgentObservations(agent, store)
            prepare(second_port, second, "last")
            with pytest.raises(AgentObservationError, match="TOOL_CALL_COUNT_EXHAUSTED"):
                prepare(second_port, second, "over")
    assert len(rows(owner, tables.agent_tool_intents)) == 8


def test_pre_migration_active_history_is_not_treated_as_zero_calls(setup: CheckpointSetup) -> None:
    owner, _, _, ids, _, _, _ = setup
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0078_event_loop_binding")
    with active(setup) as (claim, port):
        # Empty new history permits a roundtrip, while the earlier run/activity
        # is retained and cannot be silently given a fresh tool allowance.
        command.downgrade(config, "0076_tool_observation_receipts")
        command.upgrade(config, "head")
        with pytest.raises(AgentLeaseLostError):
            prepare(port, claim, "unverifiable")
        with pytest.raises(BudgetLedgerError, match="TOOL_HISTORY_UNAVAILABLE"):
            BudgetLedger(owner).reserve(
                tenant_id=scope_id(ids, "tenant_a"),
                run_id=claim.id,
                attempt_id=uuid4(),
                call_kind="tool",
                input_tokens=1,
                output_tokens=0,
                tenant_daily_token_limit=100000,
            )
    assert rows(owner, tables.agent_tool_intents) == []


def test_intent_history_schema_and_role_boundaries(setup: CheckpointSetup) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db.schema import metadata

    owner, worker, agent, _, _, _, _ = setup
    names = {
        "agent_tool_intents",
        "agent_tool_dispatches",
        "agent_tool_observations",
        "agent_tool_accounting_epochs",
    }
    with owner.connect() as c:
        context = MigrationContext.configure(
            c,
            opts=dict(
                include_schemas=True,
                include_object=lambda obj, name, kind, reflected, compared: (
                    kind != "table" or name in names
                ),
            ),
        )
        assert compare_metadata(context, metadata) == []
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0076_tool_observation_receipts")
    command.upgrade(config, "head")
    with active(setup) as (claim, port):
        call = prepare(port, claim, "evidence")
        port.dispatch(call)
    for table in (
        tables.agent_tool_intents,
        tables.agent_tool_dispatches,
        tables.agent_tool_accounting_epochs,
    ):
        with pytest.raises(DBAPIError, match="append-only"), owner.begin() as c:
            c.execute(table.delete())
        for engine in (agent, worker):
            with pytest.raises(DBAPIError), engine.begin() as c:
                c.execute(table.select())
    with pytest.raises(DBAPIError), worker.begin() as c:
        c.execute(text("SELECT cehub_ai.dispatch_agent_tool_call(NULL)"))
    with pytest.raises(
        DBAPIError,
        match="persistent (tool intent|event authorization|"
        "context manifest or runtime bundle) history",
    ):
        command.downgrade(config, "0076_tool_observation_receipts")


def test_dba_template_rolls_back_a_failure_after_the_last_new_port(setup: CheckpointSetup) -> None:
    owner, _, _, _, _, _, _ = setup
    body = SECURITY_TEMPLATE.read_text()
    assert body.rstrip().endswith("COMMIT;") and body.count("\nCOMMIT;") == 1
    body = body.replace(
        "\nBEGIN;", "\nBEGIN;\nCREATE TEMP TABLE pdos_tool_atomic_marker(id integer);", 1
    ).replace(
        "\nCOMMIT;",
        "\nDO $fault$ BEGIN RAISE EXCEPTION 'synthetic late DBA failure'; END $fault$;\nCOMMIT;",
    )
    with owner.connect() as c:
        with pytest.raises(DBAPIError, match="synthetic late DBA failure"):
            c.exec_driver_sql(body)
        c.rollback()
        assert (
            c.execute(text("SELECT to_regclass('pg_temp.pdos_tool_atomic_marker')")).scalar_one()
            is None
        )
