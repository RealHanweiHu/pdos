"""Pinned materials→separate graph→verified rows→private saved table, no real model."""

import json
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.enterprise_search import assistant_ledger as ledger
from pdos_next.enterprise_search.assistant_materials import read as read_materials
from pdos_next.enterprise_search.assistant_schemas import MaterialsInput
from pdos_next.enterprise_search.assistant_sources import human_snapshot
from pdos_next.errors import DomainError
from pdos_next.models import Artifact
from pdos_next.providers.types import ProviderUsage
from tests.enterprise_search.test_assistant_pg import execute, fixture
from tests.enterprise_search.test_retrieval_pg import register


class CompareClient:
    def __init__(self, ids, *, batch_size=2, invalid_impact=False, impact_quote=None):
        self.ids = [str(identity) for identity in ids]
        self.calls, self.child_calls, self.messages = 0, 0, []
        self.batch_size, self.invalid_impact = batch_size, invalid_impact
        self.impact_quote = impact_quote
        self.after_compare = None

    def close(self):
        pass

    def turn(self, _route, **kwargs):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        assert in_registered_agent_graph()
        self.calls += 1
        names = {row["name"] for row in kwargs["tools"]}
        messages = kwargs["messages"]
        values = [json.loads(row["content"]) for row in messages if row["role"] == "tool"]
        self.messages.append((names, deepcopy(messages)))
        if names == {"assistant.comparison.read", "result.read"}:
            self.child_calls += 1
            context = json.loads(messages[0]["content"])["context"]
            if not values:
                return ModelTurn(
                    calls=(
                        ToolCall(
                            id="read-differences",
                            name="assistant.comparison.read",
                            arguments={"comparison_id": context["comparison_id"]},
                        ),
                    ),
                    usage=ProviderUsage(10, 2),
                )
            payload = {
                "differences": [
                    {
                        "change_id": row["change_id"],
                        "label": "固定参数变化",
                        "impact_citation_id": row["new"]["citation_id"]
                        if (self.invalid_impact or self.impact_quote) and row["new"]
                        else None,
                        "impact_quote": "已批准免于复验"
                        if self.invalid_impact
                        else self.impact_quote,
                        "questions": ["工况与影响待确认。"],
                    }
                    for row in values[-1]["changes"]
                ]
            }
        else:
            assert (
                "assistant.comparison.read" not in names and "assistant.passage.read" not in names
            )
            assert "UNCHANGED_RAW_ONLY" not in str(messages)
            if not values:
                return ModelTurn(
                    calls=(
                        ToolCall(
                            id="pinned-materials",
                            name="assistant.materials.read",
                            arguments={"artifact_ids": self.ids},
                        ),
                    ),
                    usage=ProviderUsage(10, 2),
                )
            value = values[-1]
            if "items" in value:
                assert len(value["items"]) == 2, value
                args = {
                    "left_citation_id": value["items"][0]["citation_id"],
                    "right_citation_id": value["items"][1]["citation_id"],
                    "batch_size": self.batch_size,
                }
            elif value.get("has_more"):
                args = {
                    "left_citation_id": value["citation_ids"][0],
                    "right_citation_id": value["citation_ids"][1],
                    "cursor": value["next_cursor"],
                    "batch_size": self.batch_size,
                }
            else:
                if self.after_compare:
                    self.after_compare()
                payload = {"assistant": {"citation_ids": value["citation_ids"]}}
                return ModelTurn(
                    structured={
                        "status": "completed",
                        "summary": "已比较固定资料，影响待核对。",
                        "result": payload,
                        "questions": [],
                        "unfinished": [],
                    },
                    usage=ProviderUsage(10, 2),
                )
            return ModelTurn(
                calls=(
                    ToolCall(
                        id="compare-fixed-materials",
                        name="assistant.compare",
                        arguments=args,
                    ),
                ),
                usage=ProviderUsage(10, 2),
            )
        return ModelTurn(
            structured={
                "status": "completed",
                "summary": "本批变化解读完成。",
                "result": payload,
                "questions": [],
                "unfinished": [],
            },
            usage=ProviderUsage(10, 2),
        )


def starting(setup, old, new, **kwargs):
    ids = [register(setup, "比较旧版", old), register(setup, "比较新版", new)]
    client = CompareClient(ids, **kwargs)
    refs = [
        {"artifact_id": str(identity), "expected_revision": 1, "product_id": None}
        for identity in ids
    ]
    return ids, client, fixture(setup, client, read_sources=refs)


def test_pinned_documents_compare_without_index_and_save_verified_private_table(setup):
    ids, client, (owner, scope, host, adapter) = starting(
        setup,
        "共同标题\n\n压力 10 bar\n\nUNCHANGED_RAW_ONLY\n",
        "共同标题\n\n压力 12 bar\n\nUNCHANGED_RAW_ONLY\n",
    )
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    answer = output["result"]["assistant"]
    comparison = answer["comparison"]
    assert answer["lookup"] == "cited" and comparison["complete"]
    assert comparison["stats"]["changes"] == 1
    row = comparison["rows"][0]
    assert "10 bar" in row["old"]["quote"] and "12 bar" in row["new"]["quote"]
    assert row["impact"] is None and row["status"] == "needs_review"
    assert "UNCHANGED_RAW_ONLY" not in str(output)
    assert client.calls == 5 and client.child_calls == 2
    with owner.store.transaction(scope) as (session, _run):
        calls = ledger.completed(session, scope)
        metadata = next(call for call, _args in calls if call.tool == "assistant.materials.read")
        compared, args = next(
            (call, args) for call, args in calls if call.tool == "assistant.compare"
        )
        previous, arguments = deepcopy(compared.result), deepcopy(args)
        assert metadata.result["coverage"]["status"] == "current"
        assert not any(call.tool == "assistant.search" for call, _args in calls)
        raw = session.scalar(
            select(AgentToolCall).where(
                AgentToolCall.run_id == scope.run_id,
                AgentToolCall.tool == "assistant.comparison.read",
            )
        )
        assert raw.execution_binding["isolation"] == "assistant_compare"
        assert "10 bar" in str(raw.result) and "UNCHANGED_RAW_ONLY" not in str(raw.result)
    assert adapter.restore_compare(scope, arguments, previous) == previous
    assert client.calls == 5
    for source in answer["sources"]:
        response = setup.client.get(source["url"].removeprefix("/api"), headers=setup.headers)
        assert response.status_code == 200, response.text
        assert source["quote"] in response.json()["text"]
    foreign = setup.client.get(
        answer["sources"][0]["url"].removeprefix("/api"),
        headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"},
    )
    assert foreign.status_code == 403
    saved = setup.client.post(
        "/v1/personal/work-products/from-run",
        headers=setup.headers,
        json={
            "run_id": str(scope.run_id),
            "kind": "table",
            "request_key": str(uuid4()),
        },
    )
    assert saved.status_code == 201, saved.text
    assert "10 bar" in str(saved.json()) and "12 bar" in str(saved.json())
    events_path = f"/v1/categories/{setup.category}/agent-runs/{scope.run_id}/events"
    assert setup.client.get(events_path, headers=setup.headers).status_code == 200
    assert client.calls == 5
    with Session(setup.admin) as session, session.begin():
        session.get(Artifact, ids[0]).status = "withdrawn"
    blocked = setup.client.get(
        answer["sources"][0]["url"].removeprefix("/api"), headers=setup.headers
    )
    assert blocked.status_code == 403 and "10 bar" not in blocked.text
    hidden = setup.client.get(
        "/v1/personal/work-products/" + saved.json()["id"], headers=setup.headers
    )
    assert hidden.status_code == 403 and "10 bar" not in hidden.text
    hidden_events = setup.client.get(events_path, headers=setup.headers)
    assert hidden_events.status_code == 403 and "10 bar" not in hidden_events.text


def test_comparison_batches_are_complete_only_after_every_actual_change_is_read(setup):
    old = "\n\n".join(f"参数 {number}：10 bar" for number in range(5)) + "\n\nUNCHANGED_RAW_ONLY"
    new = "\n\n".join(f"参数 {number}：12 bar" for number in range(5)) + "\n\nUNCHANGED_RAW_ONLY"
    _ids, client, (owner, scope, host, _adapter) = starting(setup, old, new)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    comparison = output["result"]["assistant"]["comparison"]
    assert comparison["complete"] and comparison["stats"]["changes"] == len(comparison["rows"]) == 5
    assert client.child_calls == 6 and client.calls == 11


def test_unchanged_parsed_documents_need_no_interpretation_model(setup):
    _ids, client, (owner, scope, host, _adapter) = starting(
        setup, "相同解析正文\n\nUNCHANGED_RAW_ONLY", "相同解析正文\n\nUNCHANGED_RAW_ONLY"
    )
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    assert output["result"]["assistant"]["comparison"]["stats"]["changes"] == 0
    assert client.calls == 3 and client.child_calls == 0
    assert "UNCHANGED_RAW_ONLY" not in str(output)


def test_invented_impact_is_rejected_and_partial_is_not_presented_as_complete(setup):
    _ids, client, (owner, scope, host, _adapter) = starting(
        setup, "参数压力：10 bar\n", "参数压力：12 bar\n", invalid_impact=True
    )
    output = execute(owner, scope, host)
    assert output["status"] == "partial", output
    comparison = output["result"]["assistant"]["comparison"]
    assert not comparison["complete"] and not comparison["rows"]
    assert "已批准免于复验" not in str(output)


def test_materials_reader_cannot_sign_an_unpinned_source(setup):
    _ids, _client, (owner, scope, _host, _adapter) = starting(setup, "旧版", "新版")
    foreign = register(setup, "未选择资料", "当前本人可读也不能自动代替明确选择。")
    with human_snapshot(setup.engine, scope) as session:
        with pytest.raises(DomainError):
            read_materials(session, scope, MaterialsInput(artifact_ids=[foreign]), uuid4())


def test_documented_impact_has_a_literal_side_reference_without_inventing_authority(setup):
    _ids, _client, (owner, scope, host, _adapter) = starting(
        setup,
        "参数压力：10 bar。文中注明：按原工况复验。",
        "参数压力：12 bar。文中注明：调整后须重新复验。",
        impact_quote="调整后须重新复验",
    )
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    row = output["result"]["assistant"]["comparison"]["rows"][0]
    assert row["impact"]["quote"] in row["new"]["quote"]
    assert row["impact"]["citation_id"] == row["new"]["citation_id"]
    assert row["impact"]["status"] == "documented_quote"


def test_withdrawal_during_final_model_removes_comparison_and_unverified_unknowns(setup):
    ids, client, (owner, scope, host, _adapter) = starting(
        setup, "参数压力：10 bar\n", "参数压力：12 bar\n"
    )

    def withdraw():
        with Session(setup.admin) as session, session.begin():
            session.get(Artifact, ids[0]).status = "withdrawn"

    client.after_compare = withdraw
    output = execute(owner, scope, host)
    assert output["status"] == "partial", output
    assert "comparison" not in output["result"]["assistant"]
    assert "10 bar" not in str(output)
