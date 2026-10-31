"""Offline provider, actual authenticated HTTP→Temporal→registered graphs→source viewer."""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from temporalio.client import Client
from temporalio.worker import Worker

from pdos_next.agent_kernel.activities import KernelActivities, configure_agent_kernel
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.temporal_port import TemporalPort, workflow_id
from pdos_next.api import create_app
from pdos_next.enterprise_search.assistant_graph import AssistantExtractGraph
from pdos_next.workflows.checkpoints import verified_checkpoint_url
from pdos_next.workflows.xiaopai import XiaopaiWork
from tests.agent_kernel.test_model_configuration_transactions import configured, submit
from tests.enterprise_search.test_assistant_pg import SyntheticClient
from tests.enterprise_search.test_retrieval_pg import index, register


async def fixed_quote(http, headers, citation):
    """Read bounded native pages rather than assuming the quote is on page one."""
    cursor, pages, previous_end = 0, [], None
    url = httpx.URL(citation["url"].removeprefix("/api"))
    while True:
        response = await http.get(url.copy_merge_params({"cursor": cursor}), headers=headers)
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["citation_id"] == citation["citation_id"]
        assert page["source_revision"] == citation["source_revision"]
        assert page["content_hash"] == citation["content_hash"]
        if previous_end is not None:
            assert page["locator"]["char_start"] == previous_end
        previous_end = page["locator"]["char_end"]
        pages.append(page["text"])
        next_cursor = page["next_cursor"]
        if next_cursor is None:
            break
        assert cursor < next_cursor < page["range_chars"]
        cursor = next_cursor
    assert len("".join(pages)) == page["range_chars"]
    assert citation["quote"] in "".join(pages)


def run_http_case(
    setup,
    monkeypatch,
    provider,
    *,
    expected_kind="artifact",
    expected_calls=5,
    forbidden_history_tokens=(),
    continue_once=False,
    category_scoped=False,
    start_payload=None,
    expected_matches=1,
    expect_comparison=False,
    expected_relation=None,
    expected_group=None,
    expected_continuation_calls=5,
):
    address = os.environ["PDOS_TEMPORAL_ADDRESS"]
    endpoint = urlsplit("//" + address)
    assert endpoint.hostname in {"127.0.0.1", "localhost", "::1"} and endpoint.port
    checkpoint_url = os.environ["PDOS_CHECKPOINT_DATABASE_URL"]
    checkpoint = verified_checkpoint_url(checkpoint_url)
    management, runtime, command = configured(setup)
    command["payload"]["metadata"]["context_window_tokens"] = 200_000
    saved, _command = submit(setup, management, command)
    assert saved.status_code == 200, saved.text
    runtime = replace(runtime, provider_client=provider, preload=lambda _: ())
    bootstrap = Bootstrap(setup.engine, ports=runtime)
    adapters = replace(
        bootstrap.adapters(),
        cost_required=False,
        provider_for=lambda *_args: "synthetic-assistant-no-egress",
    )
    bootstrap._assistant_adapter.graph = AssistantExtractGraph(
        BoundHost(bootstrap.store, adapters),
        bootstrap._assistant_adapter,
        checkpointer_factory=lambda: PostgresSaver.from_conn_string(checkpoint),
    )
    from pdos_next.enterprise_search.comparison_graph import AssistantComparisonGraph

    bootstrap._assistant_adapter.comparison_graph = AssistantComparisonGraph(
        BoundHost(bootstrap.store, adapters), bootstrap._assistant_adapter,
        checkpointer_factory=lambda: PostgresSaver.from_conn_string(checkpoint),
    )
    monkeypatch.setattr(setup.engine, "_pdos_agent_kernel_adapters", None, raising=False)
    configure_agent_kernel(setup.engine, adapters)

    async def actual():
        temporal = await Client.connect(address, namespace=os.environ["PDOS_TEMPORAL_NAMESPACE"])
        assert await temporal.service_client.check_health()
        port = TemporalPort(temporal, task_queue="assistant-offline-" + str(uuid4()))
        ports = bootstrap.api_ports(port)

        def synthetic_binding(*args):
            binding = bootstrap.binding_for(*args)
            binding.token_limit = 2_000_000
            return binding

        app = create_app(
            setup.engine,
            setup.auth,
            agent_runtime_ports=runtime,
            agent_api_ports=replace(ports, binding_for=synthetic_binding),
        )
        activities = KernelActivities(
            setup.engine, checkpoint_url=checkpoint_url, technical_engine=setup.dispatch
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            async with (
                Worker(
                    temporal,
                    task_queue=port.task_queue,
                    workflows=[XiaopaiWork],
                    activities=[activities.advance, activities.reconcile],
                    activity_executor=executor,
                ),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://synthetic.local"
                ) as http,
            ):
                path = (
                    f"/v1/categories/{setup.category}/agent-runs" if category_scoped
                    else "/v1/personal/agent-runs"
                )
                payload = {
                    "goal": "以前漏气怎么处理？", **(start_payload or {}),
                    "idempotency_key": str(uuid4()),
                }
                started = await http.post(path, headers=setup.headers, json=payload)
                assert started.status_code == 202, started.text
                identity = UUID(started.json()["run_id"])
                handle = temporal.get_workflow_handle(workflow_id(setup.tenant, identity))
                outcome = await asyncio.wait_for(handle.result(), 55)
                assert outcome["status"] == "completed", outcome
                record = await http.get(path + "/" + str(identity), headers=setup.headers)
                assert record.status_code == 200, record.text
                answer = record.json()["result"]["result"]["assistant"]
                assert answer["lookup"] == "cited" and answer["matched_count"] == expected_matches
                await fixed_quote(http, setup.headers, answer["sources"][0])
                assert answer["sources"][0]["source_type"] == expected_kind
                if expected_group:
                    assert answer["sources"][0]["group"] == expected_group
                    assert answer["scope_policy"]["fallback_performed"]
                if expected_relation:
                    assert answer["sources"][0]["relation"]["type"] == expected_relation
                    assert answer["sources"][0]["object_url"].startswith("/?area=cockpit&")
                repeat = await http.post(path, headers=setup.headers, json=payload)
                assert repeat.status_code == 202 and repeat.json()["run_id"] == str(identity)
                assert provider.calls == expected_calls
                assert getattr(provider, "child_calls", 0) == (
                    2 if expected_kind == "artifact" else 0
                )
                history = await handle.fetch_history()
                assert "RAW_ONLY_CHILD_MARKER" not in str(history)
                assert "更换密封圈" not in str(history)
                for token in forbidden_history_tokens:
                    assert token not in str(history)
                if expect_comparison:
                    assert answer["comparison"]["complete"] and answer["comparison"]["rows"]
                    save_payload = {
                        "run_id": str(identity), "kind": "table", "request_key": str(uuid4())
                    }
                    product = await http.post(
                        "/v1/personal/work-products/from-run",
                        headers=setup.headers, json=save_payload,
                    )
                    assert product.status_code == 201, product.text
                    again = await http.post(
                        "/v1/personal/work-products/from-run",
                        headers=setup.headers, json=save_payload,
                    )
                    assert again.status_code == 201 and again.json()["id"] == product.json()["id"]
                    assert provider.calls == expected_calls
                if continue_once:
                    before = provider.calls
                    previous_cid = answer["citation_ids"][0]
                    provider.continue_with(previous_cid)
                    payload = {
                        "goal": "上一条来源里还说了什么？",
                        "continue_from_run_id": str(identity),
                        "idempotency_key": str(uuid4()),
                    }
                    child = await http.post(path, headers=setup.headers, json=payload)
                    assert child.status_code == 202, child.text
                    child_id = UUID(child.json()["run_id"])
                    child_handle = temporal.get_workflow_handle(
                        workflow_id(setup.tenant, child_id)
                    )
                    outcome = await asyncio.wait_for(child_handle.result(), 55)
                    assert outcome["status"] == "completed", outcome
                    saved = await http.get(path + "/" + str(child_id), headers=setup.headers)
                    assert saved.status_code == 200, saved.text
                    continued = saved.json()["result"]["result"]["assistant"]
                    assert continued["lookup"] == "cited"
                    assert continued["citation_ids"][0] != previous_cid
                    assert continued["sources"][0]["source_id"] == answer["sources"][0]["source_id"]
                    if expected_group:
                        assert continued["sources"][0]["group"] == expected_group
                    await fixed_quote(http, setup.headers, continued["sources"][0])
                    repeated = await http.post(path, headers=setup.headers, json=payload)
                    assert repeated.status_code == 202
                    assert repeated.json()["run_id"] == str(child_id)
                    assert provider.calls == before + expected_continuation_calls
                    if expected_relation:
                        assert (continued["sources"][0]["relation"]
                                == answer["sources"][0]["relation"])

                    child_history = str(await child_handle.fetch_history())
                    for token in ("RAW_ONLY_CHILD_MARKER", "更换密封圈", *forbidden_history_tokens):
                        assert token not in child_history

    asyncio.run(actual())


@pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS")
    or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Explicit verified local Temporal and checkpoint runtime required",
)
def test_authenticated_question_runs_durably_and_opens_fixed_source_without_new_inference(
    setup, monkeypatch
):
    index(setup, register(setup, "D16 气密记录", "漏气。更换密封圈。RAW_ONLY_CHILD_MARKER"))
    run_http_case(setup, monkeypatch, SyntheticClient())
