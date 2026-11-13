"""A separate worker process for the plugin pilot, so a test can kill it mid-node.

  python -m tests.workflows.graph_pilot_worker ADDRESS NAMESPACE TASK_QUEUE
"""

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

# Same first import as the production worker process. Importing the summary modules
# before it hits an existing circular import in agent.kernel.models (D379).
import pdos_next.workflows.worker  # noqa: F401, I001
from tests.workflows import graph_pilot_fixtures as fixtures


async def main(address, namespace, queue):
    from temporalio.langgraph import LangGraphPlugin

    from pdos_next.domain.my_work import summary_plugin_graph
    from pdos_next.workflows.xiaopai_graph import XiaopaiGraphWork

    fixtures.patch_summary()
    client = await Client.connect(address, namespace=namespace)
    plugin = LangGraphPlugin(graphs={summary_plugin_graph.GRAPH: summary_plugin_graph.build()})
    with ThreadPoolExecutor(max_workers=4) as executor:
        async with Worker(
            client, task_queue=queue, workflows=[XiaopaiGraphWork],
            activities=fixtures.RUN_ACTIVITIES, plugins=[plugin], activity_executor=executor,
        ):
            fixtures.note("worker:ready")
            await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:4]))
