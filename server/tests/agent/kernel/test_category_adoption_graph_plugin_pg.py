"""Category adoption end to end on the plugin path (P100, gap G1).

Real: the personal run and its candidate, the person's confirmed category creation and
receipt, the Outbox event, the metadata dispatcher, the Temporal signal, the workflow,
the plugin graph and the adoption proof read inside the node. Model turns are scripted
on the host, as in the original-path test this mirrors; no provider is called.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from pdos_next.agent.kernel.activities import KernelActivities, configure_agent_kernel
from pdos_next.agent.kernel.host import BoundHost, KernelAdapters
from pdos_next.agent.kernel.models import AgentRun
from pdos_next.agent.kernel.temporal_port import workflow_id
from pdos_next.agent.kernel.types import ModelTurn, ToolCall
from pdos_next.core.dispatch.outbox import acknowledge, claim_events
from pdos_next.core.models import Grant
from pdos_next.workflows.transport import TemporalSender
from pdos_next.workflows.worker import graph_plugin
from pdos_next.workflows.xiaopai_graph import XiaopaiGraphWork
from tests.agent.kernel.test_category_candidate_transactions import adopted, personal_fixture
from tests.agent.kernel.xiaopai_graph_plugin_harness import BINARY, payloads, scheduled
from tests.confirmation_fixture import confirmation_clock  # noqa: F401

pytestmark = pytest.mark.skipif(
    not BINARY.is_file(), reason="Inspected local Temporal binary required",
)


def test_adoption_signal_resumes_the_waiting_graph_once(setup, tmp_path, monkeypatch):
    f = personal_fixture(setup, tmp_path)
    adapters = KernelAdapters(
        route_for=lambda *_: f.route,
        project_context=f.bootstrap.project_context,
        verify_result=lambda _, result, __: result,
        prepare_candidate=f.bootstrap.prepare_candidate,
        execute_command=lambda *_: pytest.fail("No direct write"),
        tool_registry=f.registry,
        skill_catalog=f.catalog,
    )
    turns = iter([
        ModelTurn(
            calls=(ToolCall(id="synthetic-native", name="category.create",
                            arguments=f.arguments),),
            ledger_call_id=f.model_id,
        ),
        ModelTurn(structured={
            "status": "completed", "summary": "合成采用完成", "result": {},
            "questions": [], "unfinished": [],
        }),
    ])
    model_calls = []

    def scripted(self, *_args, **_kwargs):
        model_calls.append(1)
        return next(turns)

    # The node rebuilds its host from worker dependencies; script that host's model.
    monkeypatch.setattr(BoundHost, "model_step", None)
    monkeypatch.setattr(BoundHost, "model", scripted)
    monkeypatch.setattr(setup.engine, "_pdos_agent_kernel_adapters", None, raising=False)
    configure_agent_kernel(setup.engine, adapters)
    monkeypatch.setattr(
        KernelActivities, "preload", lambda self, scope, adapters: ("category_framing",),
    )
    reference = {
        "tenant_id": str(setup.tenant), "category_id": "", "actor_id": str(setup.human),
        "requester_id": str(setup.human), "subject_id": str(f.run.id),
    }

    async def actual():
        environment = await WorkflowEnvironment.start_local(dev_server_existing_path=str(BINARY))
        try:
            queue = "adoption-graph-" + str(uuid4())
            plugin, run_activities = graph_plugin(setup.engine, technical_engine=setup.dispatch)
            legacy = KernelActivities(setup.engine, technical_engine=setup.dispatch)
            with ThreadPoolExecutor(max_workers=4) as executor:
                async with Worker(
                    environment.client, task_queue=queue, workflows=[XiaopaiGraphWork],
                    activities=[*run_activities, legacy.reconcile], plugins=[plugin],
                    activity_executor=executor,
                ), asyncio.timeout(90):
                    handle = await environment.client.start_workflow(
                        XiaopaiGraphWork.run, reference,
                        id=workflow_id(setup.tenant, f.run.id), task_queue=queue,
                    )
                    while True:
                        pending = await handle.query(XiaopaiGraphWork.pending_input)
                        if pending:
                            break
                        await asyncio.sleep(0.05)
                    assert pending[0]["type"] == "category_adoption"
                    assert pending[0]["run_id"] == str(f.run.id)
                    assert len(model_calls) == 1
                    # The person confirms the creation: a real receipt and Outbox event.
                    receipt, _ = await asyncio.to_thread(adopted, setup, f)
                    events = await asyncio.to_thread(claim_events, setup.dispatch, setup.tenant)
                    assert len(events) == 1 and events[0].event_type == "category.created"
                    sender = TemporalSender(
                        environment.client, queue, dispatch_engine=setup.dispatch,
                    )
                    # The transactional Outbox may deliver more than once.
                    assert (await sender(events[0])).endswith(str(f.run.id))
                    assert (await sender(events[0])).endswith(str(f.run.id))
                    await asyncio.to_thread(
                        acknowledge, setup.dispatch, events[0], workflow_id=handle.id,
                    )
                    result = await handle.result()
                    history = await handle.fetch_history()
                    replay_plugin, _ = graph_plugin(setup.engine, technical_engine=setup.dispatch)
                    await Replayer(
                        workflows=[XiaopaiGraphWork], plugins=[replay_plugin],
                    ).replay_workflow(history)
                    return receipt, result, history
        finally:
            await environment.shutdown()

    receipt, result, history = asyncio.run(actual())
    assert result == {"run_id": str(f.run.id), "status": "completed"}
    assert len(model_calls) == 2  # the duplicate delivery did not resume twice
    names = scheduled(history)
    assert names.count("xiaopai.tools") == 1
    assert names.count("xiaopai.await_category_adoption") == 2  # the wait, then the resume
    signals = [
        event.workflow_execution_signaled_event_attributes for event in history.events
        if event.HasField("workflow_execution_signaled_event_attributes")
    ]
    identity = receipt["result"]["adoption_input_ref"]
    assert len(signals) == 2
    recorded = payloads(history)
    assert identity in recorded and receipt["subject_id"] in recorded
    with Session(setup.admin) as session:
        assert session.get(AgentRun, f.run.id).state == "completed"
        # The agent identity gained no grant on the category the person created.
        assert session.scalar(select(Grant.id).where(
            Grant.category_id == UUID(receipt["subject_id"]),
            Grant.principal_id == setup.agent,
        )) is None
