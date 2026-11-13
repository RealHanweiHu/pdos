"""A separate worker process for the plugin main graph, so a test can kill it (G3).

  python -m tests.agent.kernel.xiaopai_graph_plugin_worker ADDRESS NAMESPACE QUEUE BINDING

Same wiring as the in-process harness, against the databases named by the environment.
The provider is a file-driven stand-in: every request is appended to the journal, and
while the ``hang`` flag exists the request never returns, like a call cut off mid-flight.
"""

import asyncio
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from temporalio.client import Client
from temporalio.worker import Worker

import pdos_next.workflows.worker as worker_module


class FileProvider:
    def __init__(self, journal):
        self.journal = Path(journal)

    def turn(self, route, **kwargs):
        from tests.agent.kernel.xiaopai_graph_plugin_harness import final

        with self.journal.open("a") as handle:
            handle.write("request\n")
        while self.journal.with_suffix(".hang").exists():
            time.sleep(0.05)
        return final()

    def close(self):
        pass


async def main(address, namespace, queue, binding):
    from pdos_next.agent.kernel import graph_activities
    from pdos_next.agent.kernel.activities import KernelActivities, configure_agent_kernel
    from pdos_next.agent.kernel.bootstrap import Bootstrap
    from pdos_next.agent.model_configuration.ports import SecretBinding
    from pdos_next.core.database import engine_for
    from pdos_next.workflows.xiaopai_graph import XiaopaiGraphWork
    from tests.agent.kernel import test_model_configuration_transactions as configuration

    graph_activities.RECONCILE_AFTER_SECONDS = 1
    engine = engine_for(os.environ["DATABASE_URL"])
    dispatch = engine_for(os.environ["DISPATCH_DATABASE_URL"])
    value = json.loads(binding)
    secrets = configuration.SyntheticSecrets(UUID(value[0]))
    # The parent registered the tenant's model connection under this exact binding.
    secrets.binding = SecretBinding(
        UUID(value[0]), UUID(value[1]), UUID(value[2]), value[3], value[4],
    )
    bootstrap = Bootstrap(engine, ports=configuration.RuntimePorts(secrets=secrets))
    configure_agent_kernel(engine, replace(
        bootstrap.adapters(), provider_for=lambda *_: "synthetic-offline-provider",
        provider_client=FileProvider(os.environ["PDOS_GRAPH_PILOT_JOURNAL"]),
        cost_required=False, preload=lambda _: ("public_research",),
    ))
    plugin, run_activities = worker_module.graph_plugin(engine, technical_engine=dispatch)
    legacy = KernelActivities(engine, technical_engine=dispatch)
    client = await Client.connect(address, namespace=namespace)
    with ThreadPoolExecutor(max_workers=4) as executor:
        async with Worker(
            client, task_queue=queue, workflows=[XiaopaiGraphWork],
            activities=[*run_activities, legacy.reconcile], plugins=[plugin],
            activity_executor=executor,
        ):
            with Path(os.environ["PDOS_GRAPH_PILOT_JOURNAL"]).open("a") as handle:
                handle.write("worker:ready\n")
            await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:5]))
