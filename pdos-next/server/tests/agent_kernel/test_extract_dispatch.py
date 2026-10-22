"""Isolated extraction dispatch; pure graph harness, no database receipts."""
# ruff: noqa: F811

import hashlib
import json
from contextlib import nullcontext
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from pdos_next.agent_kernel.extract_graph import (
    ExtractGraph,
    ExtractTask,
    budget_for,
    replay_pages,
)
from pdos_next.agent_kernel.extract_pages import located_page
from pdos_next.agent_kernel.extract_read_ledger import ArtifactSeal, ExtractReadLedger
from pdos_next.agent_kernel.extract_schemas import RowSchemaDeclaration, draft_registry
from pdos_next.agent_kernel.types import ModelTurn, RunScope, ToolCall
from pdos_next.errors import DomainError
from tests.agent_kernel.test_graph import Host

TEXT = "额定压力 20 psi\n流量不低于 15 L/min\n噪声上限 65 dB\n备注：仅供参考\n最终条款以合同为准\n"


def seal(text=TEXT):
    return ArtifactSeal.from_server(
        artifact_id=str(uuid4()),
        revision=1,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        total_lines=len(text.splitlines()),
        locator_map=[],
        parse_status="parsed",
    )


def scope(item):
    return RunScope(
        tenant_id=uuid4(),
        requester_id=uuid4(),
        session_id=uuid4(),
        writer_id=uuid4(),
        run_id=uuid4(),
        category_id=uuid4(),
        isolation="extract",
        artifact_ids=frozenset({UUID(item.artifact_id)}),
    )


def task(focus=None, content="pinned synthetic extraction skill"):
    declaration = RowSchemaDeclaration(kind="rfq_requirement", version="1")
    return ExtractTask(
        declaration=declaration,
        row_model=draft_registry().row_model(declaration),
        skill_key="rfq_extraction",
        skill_version="0.3.0-draft",
        skill_digest="0" * 64,
        skill_content=content,
        focus=focus,
    )


def row(item, locator, quote, **extra):
    return {
        "artifact_version_id": item.artifact_id,
        "locator": locator,
        "quote": quote,
        "kind": "functional",
        "statement": "合成需求陈述",
        "missing": [],
        **extra,
    }


class ExtractHost(Host):
    """Pure harness host: no persistent call ledger, no trusted receipts."""

    def __init__(self, item, turns):
        super().__init__(turns)
        self.item = item


def run_graph(host, item, bound_task=None, bound_scope=None, memory=None):
    ledger = ExtractReadLedger([item])
    graph = ExtractGraph(
        host,
        artifact_read=lambda bound, arguments: located_page(item, arguments),
        checkpointer_factory=(lambda: nullcontext(memory)) if memory is not None else None,
    )
    outcome = graph(bound_scope or scope(item), item, bound_task or task(), ledger)
    return outcome, ledger


def test_child_reads_pages_and_returns_only_citation_verified_rows():
    item = seal()

    class TurnDriven(ExtractHost):
        def model(self, bound, **kwargs):
            assert bound.isolation == "extract"
            assert {tool["name"] for tool in kwargs["tools"]} == {"evidence.artifact.read"}
            initial = json.loads(kwargs["messages"][0]["content"])
            assert initial["context"]["extraction_task"]["total_lines"] == 5
            if not hasattr(self, "read_done"):
                self.read_done = True
                return ModelTurn(
                    calls=(
                        ToolCall(
                            id="page-1",
                            name="evidence.artifact.read",
                            arguments={
                                "artifact_version_id": item.artifact_id,
                                "cursor": 0,
                                "page_size": 200,
                            },
                        ),
                    )
                )
            return ModelTurn(
                structured={
                    "status": "completed",
                    "summary": "合成抽取",
                    "result": {
                        "rows": [
                            row(item, "line:1", "额定压力 20 psi"),
                            row(item, "line:2", "流量不低于 15 L/min"),
                            row(item, "line:4", "备注：仅供参考"),
                            row(item, "line:3", "噪声上限 70 dB"),  # fabricated quote
                            {**row(item, "line:3", "噪声上限 65 dB"), "statement": ""},
                        ]
                    },
                    "questions": [],
                    "unfinished": [],
                }
            )

    host = TurnDriven(item, [])
    (rows, rejected), ledger = run_graph(host, item)
    assert [r["locator"] for r in rows] == ["line:1", "line:2", "line:4"]
    assert all(r["revision"] == 1 and r["read_call_ids"] for r in rows)
    assert rows[0]["fields"]["kind"] == "functional"
    assert "artifact_version_id" not in rows[0]["fields"]
    assert {r["code"] for r in rejected} == {"quote_not_in_source", "invalid_extraction_row"}
    coverage = ledger.coverage(item.artifact_id)
    assert coverage["parsed_text"]["fully_read"] is True
    assert coverage["parsed_text"]["read_ranges"] == [[1, 5]]
    assert not hasattr(host, "result")  # The child never finishes the parent Run.
    assert all(
        event["type"] == "extract_child" and "text" not in event for event in host.events
    )


def test_rows_outside_read_pages_are_rejected():
    item = seal()

    class PartialReader(ExtractHost):
        def model(self, bound, **kwargs):
            if not hasattr(self, "read_done"):
                self.read_done = True
                return ModelTurn(
                    calls=(
                        ToolCall(
                            id="page-1",
                            name="evidence.artifact.read",
                            arguments={
                                "artifact_version_id": item.artifact_id,
                                "cursor": 0,
                                "page_size": 2,
                            },
                        ),
                    )
                )
            return ModelTurn(
                structured={
                    "status": "completed",
                    "summary": "部分读取",
                    "result": {"rows": [row(item, "line:5", "最终条款以合同为准")]},
                    "questions": [],
                    "unfinished": [],
                }
            )

    (rows, rejected), ledger = run_graph(PartialReader(item, []), item)
    assert rows == [] and [r["code"] for r in rejected] == ["source_location_not_read"]
    coverage = ledger.coverage(item.artifact_id)
    assert coverage["parsed_text"]["read_ranges"] == [[1, 2]]
    assert coverage["parsed_text"]["unread_ranges"] == [[3, 5]]
    assert coverage["parsed_text"]["fully_read"] is False


def test_child_has_only_the_registered_page_read():
    item = seal()

    class Greedy(ExtractHost):
        def model(self, bound, **kwargs):
            if not hasattr(self, "tried"):
                self.tried = True
                return ModelTurn(
                    calls=(
                        ToolCall(id="s", name="evidence.search", arguments={"query": "x"}),
                        ToolCall(
                            id="w",
                            name="proposal.item.patch",
                            arguments={"proposal_id": str(uuid4())},
                        ),
                        ToolCall(
                            id="r",
                            name="evidence.artifact.read",
                            arguments={
                                "artifact_version_id": str(uuid4()),
                                "cursor": 0,
                                "page_size": 10,
                            },
                        ),
                    )
                )
            return ModelTurn(
                structured={
                    "status": "completed",
                    "summary": "空",
                    "result": {"rows": []},
                    "questions": [],
                    "unfinished": [],
                }
            )

    host = Greedy(item, [])
    (rows, rejected), ledger = run_graph(host, item)
    assert rows == [] and rejected == []
    # All three attempts were refused before any read happened.
    assert ledger.coverage(item.artifact_id)["parsed_text"]["read_ranges"] == []
    assert host.writes == [] and host.prepared == []


def test_budget_exhaustion_fails_the_child_without_invented_coverage():
    item = seal()

    class Endless(ExtractHost):
        def model(self, bound, **kwargs):
            return ModelTurn(
                calls=(
                    ToolCall(
                        id=str(uuid4()),
                        name="evidence.artifact.read",
                        arguments={
                            "artifact_version_id": item.artifact_id,
                            "cursor": 0,
                            "page_size": 1,
                        },
                    ),
                )
            )

    host = Endless(item, [])
    ledger = ExtractReadLedger([item])
    graph = ExtractGraph(
        host, artifact_read=lambda bound, arguments: located_page(item, arguments)
    )
    with pytest.raises(DomainError) as error:
        graph(scope(item), item, task(), ledger)
    assert error.value.code == "SOURCE_UNAVAILABLE"
    # Actually completed reads remain honestly recorded even in the failed child.
    assert ledger.coverage(item.artifact_id)["parsed_text"]["read_ranges"] == [[1, 1]]


def test_resume_with_changed_skill_content_is_refused():
    item = seal()
    memory = InMemorySaver()
    bound_scope = scope(item)

    class CrashAfterRead(ExtractHost):
        def model(self, bound, **kwargs):
            if not hasattr(self, "read_done"):
                self.read_done = True
                return ModelTurn(
                    calls=(
                        ToolCall(
                            id="page-1",
                            name="evidence.artifact.read",
                            arguments={
                                "artifact_version_id": item.artifact_id,
                                "cursor": 0,
                                "page_size": 3,
                            },
                        ),
                    )
                )
            raise DomainError("SOURCE_UNAVAILABLE", "synthetic crash")

    graph = ExtractGraph(
        CrashAfterRead(item, []),
        artifact_read=lambda bound, arguments: located_page(item, arguments),
        checkpointer_factory=lambda: nullcontext(memory),
    )
    with pytest.raises(DomainError) as crash:
        graph(bound_scope, item, task(), ExtractReadLedger([item]))
    assert crash.value.code == "SOURCE_UNAVAILABLE"

    class Finish(ExtractHost):
        def model(self, bound, **kwargs):
            return ModelTurn(
                structured={
                    "status": "completed",
                    "summary": "恢复",
                    "result": {"rows": [row(item, "line:1", "额定压力 20 psi")]},
                    "questions": [],
                    "unfinished": [],
                }
            )

    resumed = ExtractGraph(
        Finish(item, []),
        artifact_read=lambda bound, arguments: located_page(item, arguments),
        checkpointer_factory=lambda: nullcontext(memory),
    )
    with pytest.raises(DomainError) as conflict:
        resumed(
            bound_scope, item, task(content="tampered skill body"), ExtractReadLedger([item])
        )
    assert conflict.value.code == "VERSION_CONFLICT"


def test_resume_replays_checkpointed_pages_into_a_fresh_ledger():
    item = seal()
    memory = InMemorySaver()
    bound_scope = scope(item)

    class CrashAfterRead(ExtractHost):
        def model(self, bound, **kwargs):
            if not hasattr(self, "read_done"):
                self.read_done = True
                return ModelTurn(
                    calls=(
                        ToolCall(
                            id="page-1",
                            name="evidence.artifact.read",
                            arguments={
                                "artifact_version_id": item.artifact_id,
                                "cursor": 0,
                                "page_size": 3,
                            },
                        ),
                    )
                )
            raise DomainError("SOURCE_UNAVAILABLE", "synthetic crash")

    graph = ExtractGraph(
        CrashAfterRead(item, []),
        artifact_read=lambda bound, arguments: located_page(item, arguments),
        checkpointer_factory=lambda: nullcontext(memory),
    )
    with pytest.raises(DomainError):
        graph(bound_scope, item, task(), ExtractReadLedger([item]))

    class Finish(ExtractHost):
        def model(self, bound, **kwargs):
            return ModelTurn(
                structured={
                    "status": "completed",
                    "summary": "恢复",
                    "result": {
                        "rows": [
                            row(item, "line:1", "额定压力 20 psi"),
                            row(item, "line:5", "最终条款以合同为准"),
                        ]
                    },
                    "questions": [],
                    "unfinished": [],
                }
            )

    resumed = ExtractGraph(
        Finish(item, []),
        artifact_read=lambda bound, arguments: located_page(item, arguments),
        checkpointer_factory=lambda: nullcontext(memory),
    )
    fresh = ExtractReadLedger([item])
    rows, rejected = resumed(bound_scope, item, task(), fresh)
    # line:1 was read before the crash and replayed; line:5 was never read.
    assert [r["locator"] for r in rows] == ["line:1"]
    assert [r["code"] for r in rejected] == ["source_location_not_read"]
    assert fresh.coverage(item.artifact_id)["parsed_text"]["read_ranges"] == [[1, 3]]


def test_replay_pages_rejects_drifted_source_text():
    item = seal()
    ledger = ExtractReadLedger([item])
    wire = located_page(
        item, {"artifact_version_id": item.artifact_id, "cursor": 0, "page_size": 2}
    )
    results = [
        {
            "tool": "evidence.artifact.read",
            "tier": "READ",
            "taint": "external",
            "value": {
                **wire,
                "execution_ref": {"call_id": str(uuid4()), "read_kind": "ordinary/v1"},
            },
        }
    ]
    replay_pages(ledger, item, results)
    assert ledger.coverage(item.artifact_id)["parsed_text"]["read_ranges"] == [[1, 2]]

    with pytest.raises(DomainError) as error:
        replay_pages(
            ExtractReadLedger([item]),
            item,
            [{**results[0], "value": {**results[0]["value"], "revision": 2}}],
        )
    assert error.value.code == "SOURCE_STALE"


def test_budget_bounds():
    assert budget_for(0).tool_calls == 9
    assert budget_for(200).tool_calls == 9
    assert budget_for(201).tool_calls == 10
    with pytest.raises(DomainError) as error:
        budget_for(24001)
    assert error.value.code == "VALIDATION_FAILED"
    assert error.value.detail["reason_key"] == "artifact_too_large"


def test_focus_reaches_the_child_context():
    item = seal()
    seen = {}

    class Observer(ExtractHost):
        def model(self, bound, **kwargs):
            seen["context"] = json.loads(kwargs["messages"][0]["content"])["context"]
            return ModelTurn(
                structured={
                    "status": "completed",
                    "summary": "空",
                    "result": {"rows": []},
                    "questions": [],
                    "unfinished": [],
                }
            )

    run_graph(Observer(item, []), item, bound_task=task(focus={"text": "压力"}))
    assert seen["context"]["extraction_task"]["focus"] == {"text": "压力"}
    assert seen["context"]["extraction_task"]["row_schema"] == {
        "kind": "rfq_requirement",
        "version": "1",
    }
    assert "额定压力" not in json.dumps(seen["context"]["extraction_task"], ensure_ascii=False)
