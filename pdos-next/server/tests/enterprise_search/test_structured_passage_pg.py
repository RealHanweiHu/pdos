"""A structured cell's registered source remains reachable beyond the title quote."""
# ruff: noqa: F401, F811 -- actual work fixture dependency registration

import json

from external_wait_pg.test_workflow import create_record, original_security_work, work
from external_wait_pg.test_workflow import execute as wait_execute
from sqlalchemy import select

from pdos_next.agent_kernel.context_budget import estimate_tokens
from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.agent_kernel.result_continuation import serialized
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.domain.external_wait.schemas import Create
from pdos_next.providers.types import ProviderUsage
from pdos_next.service import digest
from tests.enterprise_search.test_assistant_pg import execute, fixture
from tests.enterprise_search.test_business_sources_pg import NativeClient, apply_event


def test_fixed_structured_record_can_be_paged_to_the_last_registered_field(work):
    data = create_record()
    marker = "登记请求末尾逐字标记"
    data["request_content"] = "这是实际登记的请求内容。" * 160 + marker
    _command, receipt = wait_execute(work, data)
    setup = work.setup
    assert apply_event(setup, receipt["id"])["processed"] == 1
    client = NativeClient(receipt["result"]["wait_id"], ["external_wait"])
    owner, scope, host, _adapter = fixture(setup, client)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    source = output["result"]["assistant"]["sources"][0]
    url = source["url"].removeprefix("/api")
    cursor, collected, ranges = 0, [], []
    while cursor is not None:
        response = setup.client.get(url, params={"cursor": cursor, "page_chars": 400},
                                    headers=setup.headers)
        assert response.status_code == 200, response.text
        page = response.json()
        assert len(page["text"]) <= 400
        assert page["source_revision"] == source["source_revision"]
        collected.append(page["text"])
        ranges.append(page["range_chars"])
        cursor = page["next_cursor"]
    text = "".join(collected)
    assert marker in text and data["request_content"] in text
    assert len(text) == ranges[0] and len(set(ranges)) == 1
    assert len(collected) > 3 and client.calls == 3


class LongStructuredClient:
    """Offline provider fixture; it sees only the real graph's model messages."""

    def __init__(self, wait_id, request_content, closure_condition):
        self.wait_id = wait_id
        self.request_content, self.closure_condition = request_content, closure_condition
        self.calls, self.total_pages, self.full_extraction = 0, None, None
        self.handle, self.received_pages = None, []

    def close(self):
        pass

    def turn(self, _route, **kwargs):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        assert in_registered_agent_graph()
        names = {tool["name"] for tool in kwargs["tools"]}
        assert {"assistant.search", "assistant.extract", "result.read"} <= names
        assert "assistant.passage.read" not in names
        self.calls += 1
        values = [json.loads(message["content"]) for message in kwargs["messages"]
                  if message["role"] == "tool"]
        if not values:
            call = ToolCall(id="long-search", name="assistant.search", arguments={
                "query": self.wait_id, "source_types": ["external_wait"],
            })
        elif "items" in values[-1]:
            assert len(values[-1]["items"]) == 1
            call = ToolCall(id="long-extract", name="assistant.extract", arguments={
                "citation_ids": [values[-1]["items"][0]["citation_id"]],
            })
        else:
            page = values[-1]
            assert page["truncated"] and page["format"] == "json_fragment"
            assert estimate_tokens(serialized(page)) <= 4_000
            self.handle = self.handle or page["result_handle"]
            assert page["result_handle"] == self.handle
            self.total_pages = page["total_pages"]
            self.received_pages.append(page["page"])
            if page["read_more"]:
                continuation = page["read_more"]
                assert continuation["tool"] == "result.read"
                call = ToolCall(id=f"long-page-{page['page'] + 1}", name="result.read",
                                arguments=continuation["arguments"])
            else:
                # Reconstruct only fragments actually delivered through model
                # messages, never database rows or a test-injected read result.
                fragments = [value["preview"] for value in values
                             if value.get("result_handle") == self.handle]
                self.full_extraction = json.loads("".join(fragments))
                assert self.received_pages == list(range(1, self.total_pages + 1))
                assert self.full_extraction["row_count"] == 1
                row = self.full_extraction["rows"][0]
                wait = row["values"]["facts"]["wait"]
                assert wait["request_content"] == self.request_content
                assert wait["closure_condition"] == self.closure_condition
                assert not self.full_extraction["failures"] and not self.full_extraction["partial"]
                return ModelTurn(usage=ProviderUsage(10, 2), structured={
                    "status": "completed", "summary": "已完整读取登记记录，依据固定版本回答。",
                    "result": {"assistant": {"citation_ids": [row["citation_id"]]}},
                    "questions": [], "unfinished": [],
                })
        return ModelTurn(calls=(call,), usage=ProviderUsage(10, 2))


def test_long_registered_wait_uses_real_kernel_result_continuation_and_final_verification(work):
    data = create_record()
    request_marker, closure_marker = "请求内容末尾核对标记", "关闭条件末尾核对标记"
    data["request_content"] = "请" * (4_000 - len(request_marker)) + request_marker
    data["closure_condition"] = "结" * (4_000 - len(closure_marker)) + closure_marker
    Create.model_validate(data)  # Both actual domain fields remain individually legal.
    assert len(data["request_content"]) == len(data["closure_condition"]) == 4_000
    assert len(json.dumps(data, ensure_ascii=False)) > 6_000
    _command, receipt = wait_execute(work, data)
    setup, wait_id = work.setup, receipt["result"]["wait_id"]
    assert apply_event(setup, receipt["id"])["processed"] == 1
    client = LongStructuredClient(wait_id, data["request_content"], data["closure_condition"])
    owner, scope, host, adapter = fixture(setup, client)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    answer = output["result"]["assistant"]
    assert answer["lookup"] == "cited" and answer["matched_count"] == 1
    assert answer["sources"][0]["source_type"] == "external_wait"
    assert answer["sources"][0]["object_id"] == wait_id
    assert client.total_pages >= 2 and client.calls == client.total_pages + 2
    with owner.store.transaction(scope) as (session, _run):
        calls = session.scalars(select(AgentToolCall).where(
            AgentToolCall.run_id == scope.run_id, AgentToolCall.state == "completed",
        )).all()
        extraction = next(call for call in calls if call.tool == "assistant.extract")
        saved = extraction.result
        assert len(json.dumps(saved["rows"][0]["values"], ensure_ascii=False)) > 6_000
        received = {key: value for key, value in client.full_extraction.items()
                    if key != "execution_ref"}
        assert digest(saved) == digest(received)
        pages = [call for call in calls if call.tool == "result.read"]
        assert len(pages) == client.total_pages - 1
        assert all(call.execution_binding["kind"] == "read"
                   and call.execution_binding["isolation"] == "main" for call in pages)
        assert not any(call.tool == "assistant.passage.read" for call in calls)
    assert adapter.restore_extract(scope, {"citation_ids": answer["citation_ids"]}, saved) == saved
    assert client.calls == client.total_pages + 2  # Source revalidation causes no provider call.
