"""Completed read steps resume with original observations and model-call numbering."""

from __future__ import annotations

import json
from uuid import UUID

import pytest

from app.ai import runtime_factory
from app.ai.executor import AgentLoopStep, GatewayAgentModelInvoker
from app.ai.gateway import GatewayInvocation, GatewayResult
from app.ai.lease_heartbeat import AgentLeaseLostError
from app.db.schema import tables
from app.worker.dispatcher import AgentDispatcher
from tests.test_agent_checkpoints import expire
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)
from tests.test_agent_tool_loop import LoopSetup, final, tool
from tests.test_agent_tool_loop import loop_setup as loop_setup
from tests.test_event_budget_adoption import event_scope as event_scope
from tests.test_model_budget_controller import rows


@pytest.mark.parametrize("completed_steps", [1, 2])
def test_new_executor_continues_after_saved_steps(
    loop_setup: LoopSetup, monkeypatch: pytest.MonkeyPatch, completed_steps: int
) -> None:
    owner, worker, _, ids, env, calls, replies = loop_setup
    replies[:] = [tool() for _ in range(completed_steps)] + [final(ids)]
    with runtime_factory.configured_agent_runtime(env) as runtime:
        observations = runtime.executor._observations
        assert observations is not None
        original = observations._call

        def crash(sql: str, **values: object) -> object:
            result: object = original(sql, **values)
            if "save_agent_loop_checkpoint" in sql:
                raw_body = values["body"]
                assert isinstance(raw_body, str)
                body = json.loads(raw_body)
                if body["next_step"] == completed_steps:
                    expire(owner, UUID(body["context"]["run_id"]))
                    raise AgentLeaseLostError("synthetic interrupted executor")
            return result

        monkeypatch.setattr(observations, "_call", crash)
        interrupted = runtime.executor.execute_next()
    assert interrupted.error_code == "AGENT_RUN_LEASE_LOST", interrupted
    assert len(calls) == completed_steps
    assert len(rows(owner, tables.agent_loop_checkpoints)) == completed_steps
    assert not rows(owner, tables.agent_result_checkpoints)
    observed = rows(owner, tables.agent_tool_observations)
    links = rows(owner, tables.budget_run_links)
    assert AgentDispatcher(worker).dispatch_once().recovered_run_count == 1
    with runtime_factory.configured_agent_runtime(env) as runtime:
        result = runtime.executor.execute_next()
    assert result.status == "succeeded", result
    assert result.run_id == interrupted.run_id and result.finding_id is not None
    assert len(calls) == completed_steps + 1
    assert rows(owner, tables.agent_tool_observations) == observed
    assert rows(owner, tables.budget_run_links) == links
    assert len(rows(owner, tables.findings)) == 1
    assert len(rows(owner, tables.agent_result_checkpoints)) == 1
    recovery = rows(owner, tables.agent_run_recoveries)[0]

    def step(row: dict[str, object]) -> int:
        value = row["next_step"]
        assert isinstance(value, int)
        return value

    checkpoint = max(rows(owner, tables.agent_loop_checkpoints), key=step)
    assert recovery["loop_checkpoint_id"] == checkpoint["id"]
    assert recovery["checkpoint_id"] is None


def test_uncheckpointed_next_model_result_is_not_repeated(
    loop_setup: LoopSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, worker, _, ids, env, calls, replies = loop_setup
    replies[:] = [tool(), final(ids)]
    with runtime_factory.configured_agent_runtime(env) as runtime:
        invoker = runtime.executor._model_invoker
        assert isinstance(invoker, GatewayAgentModelInvoker)
        original = invoker.decide

        def crash(invocation: GatewayInvocation) -> GatewayResult[AgentLoopStep]:
            result = original(invocation)
            if len(calls) == 2:
                assert invocation.run_id is not None
                expire(owner, invocation.run_id)
                raise AgentLeaseLostError("synthetic loss after unsaved result")
            return result

        monkeypatch.setattr(invoker, "decide", crash)
        interrupted = runtime.executor.execute_next()
    assert interrupted.error_code == "AGENT_RUN_LEASE_LOST", interrupted
    assert len(rows(owner, tables.agent_loop_checkpoints)) == 1
    cycle = AgentDispatcher(worker).dispatch_once()
    assert cycle.stopped_run_count == 1 and cycle.recovered_run_count == 0
    assert rows(owner, tables.agent_run_recoveries)[0]["reason"] == (
        "AGENT_LOOP_CHECKPOINT_INCOMPLETE"
    )
    with runtime_factory.configured_agent_runtime(env) as runtime:
        assert runtime.executor.execute_next().status == "idle"
    assert len(calls) == 2 and not rows(owner, tables.findings)
