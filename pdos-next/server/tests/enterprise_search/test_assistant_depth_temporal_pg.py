"""Draft actual HTTP/Temporal/PG depth proof; only root runs guarded DB cases."""

import asyncio
import json
import os
from collections import Counter
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.database import tenant_session
from pdos_next.providers.types import ProviderUsage
from tests.enterprise_search.test_assistant_pg import SyntheticClient
from tests.enterprise_search.test_retrieval_pg import index, register
from tests.enterprise_search.verification_action_harness import actual_runtime, start

pytestmark = pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS")
    or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Root-owned explicit guarded PG, checkpoint and local Temporal required",
)


class DepthClient(SyntheticClient):
    def turn(self, route, **kwargs):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        assert in_registered_agent_graph()
        names = {item["name"] for item in kwargs["tools"]}
        if names == {"assistant.passage.read", "result.read"}:
            return super().turn(route, **kwargs)
        self.calls += 1
        messages = kwargs["messages"]
        context = json.loads(messages[0]["content"])["context"]
        mode = context["assistant_depth"]["mode"]
        values = [json.loads(item["content"]) for item in messages if item["role"] == "tool"]

        def call(name, arguments):
            return ModelTurn(calls=(ToolCall(id="offline-" + str(uuid4()), name=name,
                                             arguments=arguments),),
                             usage=ProviderUsage(10, 2))

        if not values:
            return call("assistant.search", {"query": "漏气"})
        found = values[0]["items"]
        assert len(found) >= 4
        if len(values) == 1:
            amount = 3 if mode == "quick" else 4
            return call("assistant.extract", {"citation_ids": [
                item["citation_id"] for item in found[:amount]
            ]})
        if len(values) == 2 and mode == "quick":
            return call("assistant.extract", {"citation_ids": [
                item["citation_id"] for item in found[:4]
            ]})
        if len(values) == (3 if mode == "quick" else 2):
            return call("assistant.search", {"query": "密封 漏气"})
        ids = list(dict.fromkeys(row["citation_id"] for row in values[1]["rows"]))
        return ModelTurn(structured={
            "status": "completed", "summary": "已核对本轮允许范围内的密封措施。",
            "result": {"assistant": {"citation_ids": ids,
                "unknowns": ["更多来源可在同会话继续深入查。"] if mode == "quick" else []}},
            "questions": [], "unfinished": [],
        }, usage=ProviderUsage(10, 2))


def completed_claims(person, identity):
    with tenant_session(person.engine, person.tenant, actor_id=person.human,
                        category_id=person.category) as session:
        return [(row.tool, row.state) for row in session.scalars(select(AgentToolCall).where(
            AgentToolCall.run_id == identity,
            AgentToolCall.tool.in_(["assistant.search", "assistant.extract"]),
        ))]


def test_public_fast_then_deep_same_session_uses_actual_claim_limits_and_idempotent_replay(
    setup, monkeypatch,
):
    for number in range(4):
        source = register(setup, f"合成密封历史{number}", "漏气处理：更换密封圈。")
        index(setup, source)
    provider = DepthClient()

    async def scenario():
        async with actual_runtime(setup, provider, monkeypatch) as runtime:
            source_calls = Counter()
            adapters = setup.engine._pdos_agent_kernel_adapters
            for tool in ("assistant.search", "assistant.extract"):
                original = adapters.read_resumes[tool]

                def observe(scope, arguments, *, intent_key, original=original, tool=tool):
                    source_calls[scope.run_id, tool] += 1
                    return original(scope, arguments, intent_key=intent_key)

                monkeypatch.setitem(adapters.read_resumes, tool, observe)
            quick_payload = {"goal": "以前漏气如何处理？", "idempotency_key": str(uuid4()),
                             }
            quick_id, _handle = await start(runtime, quick_payload)
            quick = await runtime.http.get(runtime.path + f"/{quick_id}", headers=setup.headers)
            assert quick.status_code == 200, quick.text
            fast = quick.json()
            assert fast["versions"]["assistant_depth"]["mode"] == "quick"
            assert len(fast["result"]["result"]["assistant"]["citation_ids"]) == 3
            claims = completed_claims(setup, quick_id)
            assert claims.count(("assistant.search", "completed")) == 1
            assert claims.count(("assistant.search", "failed")) == 1
            assert claims.count(("assistant.extract", "completed")) == 1
            assert claims.count(("assistant.extract", "failed")) == 1
            assert fast["process"]["steps"]
            assert source_calls[quick_id, "assistant.search"] == 1
            assert source_calls[quick_id, "assistant.extract"] == 1

            deep_payload = {"goal": "深入核对剩余来源和测试条件。",
                            "idempotency_key": str(uuid4()),
                            "continue_from_run_id": str(quick_id), "lookup_depth": "deep"}
            deep_id, _handle = await start(runtime, deep_payload)
            deep = await runtime.http.get(runtime.path + f"/{deep_id}", headers=setup.headers)
            assert deep.status_code == 200, deep.text
            value = deep.json()
            assert value["session_id"] == fast["session_id"]
            assert value["versions"]["assistant_depth"] == {
                "version": 1, "mode": "deep", "parent_run_id": str(quick_id),
            }
            assert value["conversation"]["previous_run_id"] == str(quick_id)
            assert len(value["result"]["result"]["assistant"]["citation_ids"]) == 4
            assert completed_claims(setup, deep_id).count(("assistant.search", "completed")) == 2
            assert source_calls[deep_id, "assistant.search"] == 2
            assert source_calls[deep_id, "assistant.extract"] == 1
            before = provider.calls
            replay = await runtime.http.post(runtime.path, headers=setup.headers, json=deep_payload)
            assert replay.status_code == 202 and UUID(replay.json()["run_id"]) == deep_id
            reopened = await runtime.http.get(runtime.path + f"/{deep_id}", headers=setup.headers)
            assert reopened.status_code == 200 and provider.calls == before
            assert reopened.json()["result"] == value["result"]

    asyncio.run(scenario())
