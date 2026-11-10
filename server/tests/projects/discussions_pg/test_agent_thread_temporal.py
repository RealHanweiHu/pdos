"""The delivery workflow through a real local Temporal server (D37 ⑥, P54).

Uses the already-downloaded local Temporal binary (skipped without it). The Run is
ended by the test-only stand-in; discovery, the workflow, the activity and the
registered-graph node are the production code.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from g0_fixture import create_g0_project
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from pdos_next.domain.projects.discussions import agent_delivery
from projects.discussions_pg import helpers as h
from projects.discussions_pg.test_agent_thread import XIAOPAI, finish, post_topic, requests

BINARY = Path(__file__).resolve().parents[4] / ".local/tools/temporal"
pytestmark = pytest.mark.skipif(not BINARY.is_file(), reason="local Temporal binary missing")


def test_discovered_reply_is_delivered_by_the_workflow(setup):
    project = create_g0_project(setup, visibility="private")
    thread_id = post_topic(setup, project, setup.human, f"{XIAOPAI} 总结一下")["thread"]["id"]
    [row] = requests(setup, thread_id)
    finish(setup, row.run_id, "总结：三项待确认。")

    async def run():
        environment = await WorkflowEnvironment.start_local(dev_server_existing_path=str(BINARY))
        try:
            activities = agent_delivery.ReplyActivities(setup.engine, setup.dispatch)
            with ThreadPoolExecutor(max_workers=2) as executor:
                async with Worker(
                    environment.client,
                    task_queue="d37-6-test",
                    workflows=[agent_delivery.DiscussionAgentReply],
                    activities=[activities.deliver],
                    activity_executor=executor,
                ):
                    found = await agent_delivery.dispatch_pending(
                        setup.dispatch, setup.tenant, environment.client, task_queue="d37-6-test"
                    )
                    assert found == {"discovered": 1, "started": 1}
                    handle = environment.client.get_workflow_handle(
                        agent_delivery.workflow_id(setup.tenant, row.id)
                    )
                    return await handle.result()
        finally:
            await environment.shutdown()

    result = asyncio.run(run())
    assert result["verdict"] == "public"
    view = h.thread(setup, project, setup.peer, thread_id)
    assert view["messages"][-1]["author_kind"] == "agent"
    assert view["messages"][-1]["body"] == "总结：三项待确认。"
