"""The no-model personal summary on the Temporal LangGraph plugin, on a real database.

Real: the admitted Run and its native private source, the worker's plugin wiring, the
open/close Activities, scope rebuilt from the database in every node, the summary's own
reads and persistence, and a local Temporal server. No checkpoint database is used.
"""
# ruff: noqa: F401, F811 -- real fixture dependency tree

import asyncio
import base64
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from pdos_next.agent.kernel.models import AgentRun
from pdos_next.agent.kernel.persistence import cancel_run
from pdos_next.core.database import tenant_session
from pdos_next.domain.my_work import summary_plugin_graph
from pdos_next.workflows.personal_summary_graph import PersonalSummaryGraphWork
from pdos_next.workflows.worker import graph_plugin
from tests.automations.pg.test_personal_summary_pg import (
    admit,
    checked,
    original_security_work,
    saved,
    summary_work,
    work_case,
)

BINARY = Path(__file__).resolve().parents[4] / ".local/tools/temporal"
pytestmark = pytest.mark.skipif(
    not BINARY.is_file(), reason="Inspected local Temporal binary required",
)


def execute(summary_work, envelope, *, workflow_ids=("first",), before=None):
    """Run the pilot workflow once per id against the worker's own plugin wiring."""
    setup = summary_work.setup

    async def actual():
        environment = await WorkflowEnvironment.start_local(dev_server_existing_path=str(BINARY))
        try:
            plugin, run_activities = graph_plugin(setup.engine, technical_engine=setup.dispatch)
            queue = "summary-plugin-" + str(uuid4())
            outcomes = []
            with ThreadPoolExecutor(max_workers=4) as executor:
                async with Worker(
                    environment.client, task_queue=queue, workflows=[PersonalSummaryGraphWork],
                    activities=run_activities, plugins=[plugin], activity_executor=executor,
                ), asyncio.timeout(120):
                    for name in workflow_ids:
                        if before:
                            await asyncio.to_thread(before, name)
                        handle = await environment.client.start_workflow(
                            PersonalSummaryGraphWork.run, envelope,
                            id=f"summary-plugin:{name}:{envelope['subject_id']}",
                            task_queue=queue,
                        )
                        try:
                            result = await handle.result()
                        except WorkflowFailureError as error:
                            result = error
                        outcomes.append((result, await handle.fetch_history()))
            return outcomes
        finally:
            await environment.shutdown()

    return asyncio.run(actual())


def scheduled(history):
    return [
        event.activity_task_scheduled_event_attributes.activity_type.name
        for event in history.events
        if event.HasField("activity_task_scheduled_event_attributes")
    ]


def payloads(history):
    return b"\n".join(
        base64.b64decode(value) for value in re.findall(r'"data":\s*"([^"]*)"', history.to_json())
    ).decode().encode().decode("unicode_escape")


def run_row(summary_work, envelope):
    with Session(summary_work.setup.admin) as session:
        run = session.get(AgentRun, UUID(envelope["subject_id"]))
        return run.state, run.error_code, dict(run.versions)


def test_summary_runs_node_by_node_and_a_second_start_does_not_repeat_it(summary_work):
    _rule, envelope = admit(summary_work)
    (first, history), (second, again) = execute(
        summary_work, envelope, workflow_ids=("first", "second"),
    )
    assert first == second == {"run_id": envelope["subject_id"], "status": "completed"}
    assert scheduled(history) == [
        "open_xiaopai_graph_run",
        "personal-summary.read_personal_summary",
        "personal-summary.persist_personal_summary",
    ]
    # The run is terminal: a later workflow for it stops at open and runs no node.
    assert scheduled(again) == ["open_xiaopai_graph_run"]
    result, _events = saved(summary_work, envelope)  # also: no ledger call, no tokens
    summary = result["result"]["personal_summary"]
    assert summary["principal_id"] == str(summary_work.setup.human)
    assert summary["model_used"] is False
    assert checked(summary_work, envelope) == result
    state, error_code, versions = run_row(summary_work, envelope)
    assert (state, error_code) == ("completed", None)
    assert versions["execution_engine"] == "temporal-langgraph/v1"
    # P100: run data may be in history; no connection string or password may.
    recorded = payloads(history)
    assert "具名登记：私有项目材料已核对。" in recorded
    for name in ("TEST_DATABASE_URL", "DATABASE_URL", "AUTH_DATABASE_URL",
                 "DISPATCH_DATABASE_URL"):
        url = os.environ[name]
        assert url not in recorded and url.split(":")[2].split("@")[0] not in recorded
    target = os.environ.get("PDOS_GRAPH_PILOT_EVIDENCE")
    if target:
        with Path(target).open("a") as handle:
            handle.write(json.dumps({
                "case": "summary_real_database", "history_events": len(history.events),
                "history_json_bytes": len(history.to_json().encode()),
                "activities": scheduled(history),
            }, ensure_ascii=False) + "\n")


def test_run_cancelled_between_nodes_stops_before_persisting(summary_work, monkeypatch):
    setup = summary_work.setup
    _rule, envelope = admit(summary_work)
    generate = summary_plugin_graph.runtime.generate

    def generate_then_cancel(store, scope):
        value = generate(store, scope)
        with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                            requester_id=setup.human, category_id=setup.category) as session:
            cancel_run(session, setup.ctx, scope.run_id)
        return value

    monkeypatch.setattr(summary_plugin_graph.runtime, "generate", generate_then_cancel)
    ((result, history),) = execute(summary_work, envelope)
    assert result == {"run_id": envelope["subject_id"], "status": "cancelled",
                      "error_code": "CANCELLED_RUN"}
    # The second node started, rebuilt its scope from the database and stopped there;
    # it was not retried and the cancelled run received no result.
    assert scheduled(history) == [
        "open_xiaopai_graph_run",
        "personal-summary.read_personal_summary",
        "personal-summary.persist_personal_summary",
        "close_xiaopai_graph_run",
    ]
    state, _error, _versions = run_row(summary_work, envelope)
    assert state == "cancelled"
    with Session(setup.admin) as session:
        assert session.get(AgentRun, UUID(envelope["subject_id"])).result is None


def test_node_failure_is_recorded_once_without_a_retry(summary_work, monkeypatch):
    from pdos_next.errors import DomainError

    _rule, envelope = admit(summary_work)
    calls = []

    def refuse(_store, _scope):
        calls.append(1)
        raise DomainError("FORBIDDEN_SCOPE", "synthetic source refusal")

    monkeypatch.setattr(summary_plugin_graph.runtime, "generate", refuse)
    ((result, history),) = execute(summary_work, envelope)
    assert result == {"run_id": envelope["subject_id"], "status": "failed",
                      "error_code": "FORBIDDEN_SCOPE"}
    assert len(calls) == 1
    assert scheduled(history)[-1] == "close_xiaopai_graph_run"
    state, error_code, _versions = run_row(summary_work, envelope)
    assert (state, error_code) == ("failed", "FORBIDDEN_SCOPE")


def test_envelope_of_another_requester_is_refused_and_the_run_is_untouched(summary_work):
    setup = summary_work.setup
    _rule, envelope = admit(summary_work)
    forged = {**envelope, "requester_id": str(setup.peer)}
    ((result, history),) = execute(summary_work, forged)
    assert isinstance(result, WorkflowFailureError)
    assert scheduled(history) == ["open_xiaopai_graph_run"]
    state, error_code, versions = run_row(summary_work, envelope)
    assert (state, error_code) == ("queued", None) and "execution_engine" not in versions
