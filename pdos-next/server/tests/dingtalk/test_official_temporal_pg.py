"""PG/Temporal draft: official MockTransport → native 小Pai → private receipt and explicit share."""
# ruff: noqa: F401 -- shared PG fixture is intentionally re-exported

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from pdos_next.agent_kernel.activities import KernelActivities, configure_agent_kernel
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.temporal_port import TemporalPort, workflow_id
from pdos_next.dingtalk.models import Delivery, Message
from pdos_next.dingtalk.workflow import ChannelActivities, ChannelSender, DingTalkCompletion
from pdos_next.enterprise_search.assistant_graph import AssistantExtractGraph
from pdos_next.workflows.checkpoints import verified_checkpoint_url
from pdos_next.workflows.xiaopai import XiaopaiWork
from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.client import Client
from temporalio.worker import Worker
from tests.agent_kernel.test_model_configuration_transactions import configured, submit
from tests.dingtalk.test_channel_pg import channel as channel
from tests.dingtalk.test_official_pg import bind_official, incoming_official, protocol
from tests.enterprise_search.test_assistant_pg import SyntheticClient
from tests.enterprise_search.test_retrieval_pg import index, register


@pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS")
    or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Explicit verified local Temporal and checkpoint required",
)
def test_official_wire_uses_same_temporal_graph_and_current_private_delivery(
    setup, request, monkeypatch
):
    endpoint = urlsplit("//" + os.environ["PDOS_TEMPORAL_ADDRESS"])
    assert endpoint.hostname in {"127.0.0.1", "localhost", "::1"} and endpoint.port
    # Configure actual native model metadata/secret binding with an offline provider.
    management, ports, command = configured(setup)
    command["payload"]["metadata"]["context_window_tokens"] = 200_000
    saved, _prepared = submit(setup, management, command)
    assert saved.status_code == 200, saved.text
    work = request.getfixturevalue("channel")
    index(setup, register(setup, "D16 气密记录", "漏气。更换密封圈。RAW_ONLY_CHILD_MARKER"))
    wire = protocol(work)
    bind_official(work)
    provider = SyntheticClient()
    bootstrap = Bootstrap(
        setup.engine, ports=replace(ports, provider_client=provider, preload=lambda _: ())
    )
    adapters = replace(
        bootstrap.adapters(),
        cost_required=False,
        provider_for=lambda *_: "synthetic-assistant-no-egress",
    )
    checkpoint_url = os.environ["PDOS_CHECKPOINT_DATABASE_URL"]
    bootstrap._assistant_adapter.graph = AssistantExtractGraph(
        BoundHost(bootstrap.store, adapters),
        bootstrap._assistant_adapter,
        checkpointer_factory=lambda: PostgresSaver.from_conn_string(
            verified_checkpoint_url(checkpoint_url)
        ),
    )
    configure_agent_kernel(setup.engine, adapters)
    # Match the native assistant's explicit synthetic accounting allowance for
    # the complete tool surface; the production Run budget remains enforced.
    native_binding = Bootstrap.binding_for

    def synthetic_binding(owner, *args):
        binding = native_binding(owner, *args)
        binding.token_limit = 2_000_000
        return binding

    monkeypatch.setattr(Bootstrap, "binding_for", synthetic_binding)
    admitted = incoming_official(work, wire.runtime)
    assert admitted.status_code == 200 and admitted.json() == {"msgtype": "empty"}
    with Session(setup.admin) as session:
        message = session.scalar(select(Message).where(Message.tenant_id == setup.tenant))
        run_id, message_id = message.run_id, message.id

    async def actual():
        client = await Client.connect(
            os.environ["PDOS_TEMPORAL_ADDRESS"], namespace=os.environ["PDOS_TEMPORAL_NAMESPACE"]
        )
        native = TemporalPort(client, task_queue="dingtalk-offline-" + str(uuid4()))
        kernel = KernelActivities(
            setup.engine, checkpoint_url=checkpoint_url, technical_engine=setup.dispatch
        )
        delivery = ChannelActivities(setup.engine, setup.dispatch, native, runtime=wire.runtime)
        sender = ChannelSender(client, setup.dispatch, native, task_queue=native.task_queue)
        with ThreadPoolExecutor(max_workers=4) as executor:
            async with Worker(
                client,
                task_queue=native.task_queue,
                workflows=[XiaopaiWork, DingTalkCompletion],
                activities=[kernel.advance, kernel.reconcile, delivery.deliver, delivery.cancel],
                activity_executor=executor,
            ):
                await sender.discover(setup.tenant)
                native_handle = client.get_workflow_handle(workflow_id(setup.tenant, run_id))
                outcome = await asyncio.wait_for(native_handle.result(), 65)
                assert outcome["status"] in {"completed", "partial"}, outcome
                completion = client.get_workflow_handle(
                    f"pdos-next:dingtalk:{setup.tenant}:{message_id}:reply"
                )
                sent = await asyncio.wait_for(completion.result(), 200)
                assert sent["state"] == "delivered", sent
                assert wire.calls.count("/v1.0/robot/oToMessages/batchSend") == 2
                assert wire.calls.count("/v1.0/robot/groupMessages/send") == 1
                assert wire.calls.count("/v1.0/robot/oToMessages/readStatus") == 2
                before = provider.calls
                assert before == 5
                preview = work.client.post(
                    "/v1/personal/dingtalk/share/preview",
                    headers=setup.headers,
                    json={"run_id": str(run_id), "include_citations": False},
                )
                assert preview.status_code == 200, preview.text
                assert not preview.json()["citations_included"]
                body = {
                    "run_id": str(run_id),
                    "include_citations": False,
                    "preview_digest": preview.json()["preview_digest"],
                    "request_key": str(uuid4()),
                }
                confirmed = work.client.post(
                    "/v1/personal/dingtalk/share/confirm", headers=setup.headers, json=body
                )
                assert confirmed.status_code == 202, confirmed.text
                assert (
                    work.client.post(
                        "/v1/personal/dingtalk/share/confirm", headers=setup.headers, json=body
                    ).json()["consent_id"]
                    == confirmed.json()["consent_id"]
                )
                await sender.discover(setup.tenant)
                shared = client.get_workflow_handle(
                    f"pdos-next:dingtalk:{setup.tenant}:{message_id}:{confirmed.json()['consent_id']}"
                )
                assert (await asyncio.wait_for(shared.result(), 65))["state"] == "delivered"
                assert provider.calls == before
                assert wire.calls.count("/v1.0/robot/groupMessages/send") == 2
                history = str(await completion.fetch_history()) + str(await shared.fetch_history())
                for original in ["RAW_ONLY_CHILD_MARKER", "更换密封圈", "synthetic-fixture-only"]:
                    assert original not in history
        with Session(setup.admin) as session:
            run = session.get(AgentRun, run_id)
            assert run.writer_id == setup.agent and run.requester_id == setup.human
            rows = list(session.scalars(select(Delivery).where(Delivery.message_id == message_id)))
            assert len(rows) == 4 and all(r.state == "delivered" and r.attempts == 1 for r in rows)
            assert all(r.p26["provider"] == "dingtalk" for r in rows)
            private = next(r for r in rows if r.phase == "answer")
            assert private.payload["target_kind"] == "direct" and "citations" not in private.payload
            group = next(r for r in rows if r.phase == "share")
            assert "citations" not in group.payload and group.consent_id is not None
            assert all(r.provider_receipt["status"] == "delivered" for r in rows)

    asyncio.run(actual())
