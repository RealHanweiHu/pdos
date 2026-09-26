"""Actual factory observations, projected payload receipts and lease/scoping boundaries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import NoReturn
from uuid import UUID, uuid4, uuid5

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.ai import runtime_factory
from app.ai.executor import AgentAssessment, GatewayAgentModelInvoker
from app.ai.gateway import GatewayInvocation, GatewayResult
from app.ai.observations import AgentObservationError
from app.contracts.runtime_records import Observation
from app.db.schema import tables
from tests.test_agent_checkpoints import CheckpointSetup, crash_after_result, scope_id
from tests.test_agent_checkpoints import setup as setup
from tests.test_agent_database_security import SERVER_ROOT
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)
from tests.test_event_budget_adoption import event_scope as event_scope
from tests.test_model_budget_controller import evidence, rows

JOURNALS = (
    tables.agent_tool_observations,
    tables.agent_context_receipts,
    tables.agent_context_observations,
)


def row_number(row: Mapping[str, object], key: str) -> int:
    value = row[key]
    assert isinstance(value, int)
    return value


def row_uuid(row: Mapping[str, object], key: str) -> UUID:
    value = row[key]
    assert isinstance(value, UUID)
    return value


def test_real_factory_persists_observations_and_exact_projected_context(
    setup: CheckpointSetup,
) -> None:
    owner, _, _, _, env, calls, _ = setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.status == "succeeded", result
    observations = sorted(
        rows(owner, tables.agent_tool_observations), key=lambda r: row_number(r, "sequence")
    )
    assert [r["tool_key"] for r in observations] == [
        "get_project_context",
        "get_recent_events",
        "search_memory",
        "get_issue_evidence",
    ]
    assert [r["sequence"] for r in observations] == [1, 2, 3, 4]
    for row in observations:
        assert Observation.model_validate(row["metadata"]).id == row["id"]
    memory = evidence(next(r for r in observations if r["tool_key"] == "search_memory")["metadata"])
    assert memory["status"] == "unavailable" and memory["total_count"] is None
    assert memory["error_code"] == "TOOL_NOT_ENABLED"
    receipt = rows(owner, tables.agent_context_receipts)[0]
    links = sorted(
        rows(owner, tables.agent_context_observations), key=lambda r: row_number(r, "position")
    )
    assert [r["observation_id"] for r in links] == [r["id"] for r in observations]
    trace = rows(owner, tables.model_invocations)[0]
    assert trace["context_receipt_id"] == receipt["id"] and trace["run_id"] == result.run_id
    body = json.loads(calls[0].content)
    actual = json.loads(body["messages"][1]["content"].split("PDOS_CONTEXT_JSON\n")[1])
    assert actual == evidence(receipt["body"])["context"]
    by_tool = {item["tool"]: item for item in actual["tool_observations"]}
    assert by_tool["search_memory"]["status"] == "unavailable"
    assert by_tool["get_issue_evidence"]["status"] == "completed"
    with owner.connect() as c:
        assert c.execute(
            text("""SELECT bool_and(metadata->>'input_digest'=
            encode(sha256(convert_to(input_body::text,'UTF8')),'hex') AND
            metadata->>'output_digest'=encode(sha256(convert_to(output_body::text,'UTF8')),'hex'))
            FROM cehub_ai.agent_tool_observations""")
        ).scalar_one()


@pytest.mark.parametrize("change", ["allowed_field", "private_field"])
def test_gateway_verifies_only_the_actual_egress_body_before_call(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    owner, _, _, _, env, calls, _ = setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        invoke = runtime.executor._model_invoker.invoke

        def change_context(invocation: GatewayInvocation) -> GatewayResult[AgentAssessment]:
            context = dict(invocation.context)
            if change == "allowed_field":
                context["project"] = {
                    **evidence(context["project"]),
                    "name": "different after freezing",
                }
            else:
                context["internal_secret"] = "never disclose this value"
            return invoke(invocation.model_copy(update={"context": context}))

        monkeypatch.setattr(runtime.executor._model_invoker, "invoke", change_context)
        result = runtime.executor.execute_next()
    if change == "allowed_field":
        assert result.error_code == "AGENT_CONTEXT_RECEIPT_MISMATCH"
        assert calls == [] and not rows(owner, tables.findings)
    else:
        assert result.status == "succeeded"
        assert b"never disclose" not in calls[0].content
    assert len(rows(owner, tables.agent_context_receipts)) == 1


def test_context_freeze_is_idempotent_and_rejects_order_or_content_conflicts(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _, _, _, env, calls, _ = setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        invoke = runtime.executor._model_invoker.invoke

        def check_freeze(invocation: GatewayInvocation) -> GatewayResult[AgentAssessment]:
            assert invocation.model_call_id is not None
            port = runtime.executor._observations
            assert port is not None
            receipt = rows(owner, tables.agent_context_receipts)[0]
            links = sorted(
                rows(owner, tables.agent_context_observations),
                key=lambda r: row_number(r, "position"),
            )
            ids = tuple(row_uuid(row, "observation_id") for row in links)
            receipt_body = evidence(receipt["body"])
            assert port.freeze(invocation.model_call_id, receipt_body, ids) == receipt["id"]
            with pytest.raises(AgentObservationError, match="OBSERVATIONS_INVALID"):
                port.freeze(invocation.model_call_id, receipt_body, tuple(reversed(ids)))
            with pytest.raises(AgentObservationError, match="OBSERVATIONS_INVALID"):
                port.freeze(invocation.model_call_id, receipt_body, (uuid4(),))
            changed = {**receipt_body, "instruction_sha256": "0" * 64}
            with pytest.raises(AgentObservationError, match="RECEIPT_CONFLICT"):
                port.freeze(invocation.model_call_id, changed, ids)
            return invoke(invocation)

        monkeypatch.setattr(runtime.executor._model_invoker, "invoke", check_freeze)
        assert runtime.executor.execute_next().status == "succeeded"
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["same", "output", "scope", "tool", "source"])
def test_observation_ports_enforce_idempotency_scope_and_conflicts(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    owner, _, _, ids, env, calls, _ = setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        invoke = runtime.executor._model_invoker.invoke

        def check_port(invocation: GatewayInvocation) -> GatewayResult[AgentAssessment]:
            row = sorted(
                rows(owner, tables.agent_tool_observations), key=lambda r: row_number(r, "sequence")
            )[0]
            args = evidence(row["input_body"])
            output = evidence(row["output_body"])
            meta = evidence(row["metadata"])
            tool = row["tool_key"]
            expected = None
            if change == "output":
                output["project"] = {**evidence(output["project"]), "name": "changed"}
                expected = "OBSERVATION_CONFLICT"
            elif change == "scope":
                args["project_id"] = str(ids["project_b"])
                expected = "OBSERVATION_INVALID"
            elif change == "tool":
                tool = "get_quality_evidence"
                expected = "OBSERVATION_TOOL_INVALID"
            elif change == "source":
                sources = meta["sources"]
                assert isinstance(sources, list)
                meta["sources"] = [{**evidence(sources[0]), "tenant_id": str(ids["tenant_b"])}]
                expected = "OBSERVATION_SOURCE_SCOPE"

            def append() -> dict[str, object]:
                port = runtime.executor._observations
                assert port is not None
                return evidence(
                    port._call(
                        "SELECT cehub_ai.append_agent_tool_observation"
                        "(:key,:tool,:args,:output,:meta)",
                        key=row["call_key"],
                        tool=tool,
                        args=json.dumps(args),
                        output=json.dumps(output),
                        meta=json.dumps(meta),
                    )
                )

            if expected:
                with pytest.raises(AgentObservationError, match=expected):
                    append()
            else:
                appended_id = append()["id"]
                assert isinstance(appended_id, str)
                assert UUID(appended_id) == row["id"]
            return invoke(invocation)

        monkeypatch.setattr(runtime.executor._model_invoker, "invoke", check_port)
        assert runtime.executor.execute_next().status == "succeeded"
    assert len(calls) == 1 and len(rows(owner, tables.agent_tool_observations)) == 4


def test_observation_and_receipt_history_is_append_only_and_not_role_readable(
    setup: CheckpointSetup,
) -> None:
    owner, worker, agent, _, env, _, _ = setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        assert runtime.executor.execute_next().status == "succeeded"
    for table in JOURNALS:
        with pytest.raises(DBAPIError, match="append-only"), owner.begin() as c:
            c.execute(table.delete())
        for engine in (worker, agent):
            with pytest.raises(DBAPIError), engine.begin() as c:
                c.execute(table.select())
    with pytest.raises(DBAPIError), worker.begin() as c:
        c.execute(text("SELECT cehub_ai.verify_agent_context_receipt(NULL,NULL,NULL)"))


def test_recovery_reuses_observation_and_context_records_without_model_or_embedding(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.worker.dispatcher import AgentDispatcher

    owner, worker, _, _, env, calls, _ = setup
    crash_after_result(setup, monkeypatch)
    before = [rows(owner, t) for t in JOURNALS]
    assert AgentDispatcher(worker).dispatch_once().recovered_run_count == 1
    with runtime_factory.configured_agent_runtime(env) as runtime:
        assert runtime.executor.execute_next().status == "succeeded"
    assert [rows(owner, t) for t in JOURNALS] == before and len(calls) == 1


def test_unavailable_model_without_trace_stays_explicitly_degraded(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _, _, _, env, calls, _ = setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        invoker = runtime.executor._model_invoker
        assert isinstance(invoker, GatewayAgentModelInvoker)
        governance = invoker._gateway._governance
        get = governance.get
        monkeypatch.setattr(governance, "get", lambda **kw: replace(get(**kw), selection=None))
        result = runtime.executor.execute_next()
    assert result.status == "degraded" and result.error_code == "MODEL_NOT_AVAILABLE"
    assert calls == [] and not rows(owner, tables.model_invocations)
    assert not rows(owner, tables.agent_result_checkpoints)
    assert len(rows(owner, tables.agent_tool_observations)) == 4


def test_schema_roundtrip_and_persistent_evidence_guard(setup: CheckpointSetup) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db.schema import metadata

    owner, _, _, _, env, _, _ = setup
    names = {table.name for table in JOURNALS} | {"model_invocations"}
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
    command.downgrade(config, "0075_event_trigger_scheduling")
    command.upgrade(config, "head")
    with runtime_factory.configured_agent_runtime(env) as runtime:
        assert runtime.executor.execute_next().status == "succeeded"
    with pytest.raises(
        DBAPIError,
        match="persistent (tool observation|tool intent|event authorization|"
        "context manifest or runtime bundle) history",
    ):
        command.downgrade(config, "0075_event_trigger_scheduling")


def test_failed_tool_records_failure_without_model_cleanup_call(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai.tools import AgentReadTools

    owner, _, _, _, env, calls, _ = setup

    def fail_read(
        self: AgentReadTools, *, project_id: UUID, query: str, offset: int = 0, limit: int = 20
    ) -> NoReturn:
        raise ValueError("synthetic invalid tool input")

    monkeypatch.setattr(AgentReadTools, "search_memory", fail_read)
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.error_code == "TOOL_INPUT_INVALID" and calls == []
    observations = sorted(
        rows(owner, tables.agent_tool_observations), key=lambda r: row_number(r, "sequence")
    )
    assert len(observations) == 3 and evidence(observations[-1]["metadata"])["status"] == "failed"
    assert evidence(observations[-1]["metadata"])["error_code"] == "TOOL_INPUT_INVALID"
    assert not rows(owner, tables.agent_context_receipts)


@pytest.mark.parametrize("target", ["missing_run", "other_run"])
def test_trace_scope_cannot_attach_a_receipt_to_another_run(
    setup: CheckpointSetup, target: str
) -> None:
    from datetime import timedelta

    owner, _, _, _, env, _, _ = setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        assert runtime.executor.execute_next().status == "succeeded"
    trace = dict(
        rows(owner, tables.model_invocations)[0],
        id=uuid4(),
        model_call_session_id=None,
        budget_call_id=None,
    )
    if target == "missing_run":
        trace["run_id"] = None
        expected = "ck_model_invocations_context_run"
    else:
        run = dict(rows(owner, tables.agent_runs)[0], id=uuid4())
        start, end = run["window_started_at"], run["window_ended_at"]
        assert isinstance(start, datetime) and isinstance(end, datetime)
        run["window_started_at"] = start + timedelta(days=1)
        run["window_ended_at"] = end + timedelta(days=1)
        with owner.begin() as c:
            c.execute(tables.agent_runs.insert().values(**run))
        trace["run_id"] = run["id"]
        expected = "fk_model_context_receipt"
    with pytest.raises(DBAPIError, match=expected), owner.begin() as c:
        c.execute(tables.model_invocations.insert().values(**trace))


def test_concurrent_append_uses_one_sequence_and_preserves_original_time(
    setup: CheckpointSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    owner, _, agent, _, env, _, _ = setup
    with runtime_factory.configured_agent_runtime(env) as runtime:
        invoke = runtime.executor._model_invoker.invoke

        def check_concurrent(invocation: GatewayInvocation) -> GatewayResult[AgentAssessment]:
            observation = sorted(
                rows(owner, tables.agent_tool_observations), key=lambda r: row_number(r, "sequence")
            )[0]
            run = rows(owner, tables.agent_runs)[0]
            call_id = uuid5(row_uuid(run, "id"), "concurrent.project")
            port = runtime.executor._observations
            assert port is not None
            port._call(
                "SELECT cehub_ai.prepare_agent_tool_call(:call,:key,:tool,:args)",
                call=call_id,
                key="concurrent.project",
                tool=observation["tool_key"],
                args=json.dumps(observation["input_body"]),
            )
            port.dispatch(call_id)

            def append(_: int) -> dict[str, object]:
                lease_token = evidence(run["run_context"])["_lease_token"]
                assert isinstance(lease_token, str)
                with agent.begin() as c:
                    c.execute(
                        text("SELECT cehub_ai.bind_agent_scope(:run,:token)"),
                        dict(run=run["id"], token=UUID(lease_token)),
                    )
                    result = c.execute(
                        text("""SELECT cehub_ai.append_agent_tool_observation(
                        :key,:tool,:args,:output,:meta)"""),
                        dict(
                            key="concurrent.project",
                            tool=observation["tool_key"],
                            args=json.dumps(observation["input_body"]),
                            output=json.dumps(observation["output_body"]),
                            meta=json.dumps(
                                {**evidence(observation["metadata"]), "tool_call_id": str(call_id)}
                            ),
                        ),
                    ).scalar_one()
                    return evidence(result)

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(append, range(2)))
            assert results[0] == results[1] and results[0]["sequence"] == 5
            return invoke(invocation)

        monkeypatch.setattr(runtime.executor._model_invoker, "invoke", check_concurrent)
        assert runtime.executor.execute_next().status == "succeeded"
    assert len(rows(owner, tables.agent_tool_observations)) == 5
    assert len(rows(owner, tables.agent_context_observations)) == 4


def test_actual_paginated_read_records_partial_status_and_continuation(
    setup: CheckpointSetup,
) -> None:
    from datetime import UTC, datetime

    from tests.test_agent_dispatcher import append_event

    owner, _, _, ids, env, calls, _ = setup
    with owner.begin() as c:
        for _ in range(25):
            append_event(
                c,
                tenant_id=scope_id(ids, "tenant_a"),
                project_id=scope_id(ids, "project_a"),
                event_type="ISSUE_CREATED",
                occurred_at=datetime.now(UTC),
            )
    with runtime_factory.configured_agent_runtime(env) as runtime:
        assert runtime.executor.execute_next().status == "succeeded"
    event = next(
        r
        for r in rows(owner, tables.agent_tool_observations)
        if r["tool_key"] == "get_recent_events"
    )
    meta = Observation.model_validate(event["metadata"])
    assert meta.total_count is not None
    assert meta.status == "partial" and meta.shown_count == 20 and meta.total_count > 20
    assert meta.truncated and meta.continuation
    body = evidence(rows(owner, tables.agent_context_receipts)[0]["body"])
    context = evidence(body["context"])
    observations = context["tool_observations"]
    assert isinstance(observations, list)
    exposed = next(evidence(o) for o in observations if evidence(o)["tool"] == "get_recent_events")
    assert exposed["truncated"] is True and exposed["continuation"] == meta.continuation
    assert len(calls) == 1
