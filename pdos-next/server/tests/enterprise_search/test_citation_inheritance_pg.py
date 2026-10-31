"""Offline actual graph/proof chains for fixed citations across conversation turns."""

import json
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.enterprise_search import assistant_ledger as ledger
from pdos_next.enterprise_search.assistant_inheritance import page
from pdos_next.enterprise_search.assistant_schemas import CitationsInput
from pdos_next.enterprise_search.assistant_sources import human_snapshot
from pdos_next.errors import DomainError
from pdos_next.models import Artifact
from pdos_next.providers.types import ProviderUsage
from tests.enterprise_search.test_assistant_pg import SyntheticClient, execute, fixture
from tests.enterprise_search.test_retrieval_pg import index, register
from tests.preproject.test_g0 import post, request


class FollowupClient(SyntheticClient):
    def __init__(self, *, selector=None, citation=None):
        super().__init__()
        self.selector, self.citation = selector, citation

    def turn(self, route, **kwargs):
        names = {row["name"] for row in kwargs["tools"]}
        values = [json.loads(row["content"]) for row in kwargs["messages"] if row["role"] == "tool"]
        if (names == {"assistant.passage.read", "result.read"}
                or values and "items" not in values[-1]):
            return super().turn(route, **kwargs)
        self.calls += 1
        self.messages.append((names, deepcopy(kwargs["messages"])))
        if not values:
            name = "assistant.extract" if self.citation else "assistant.citations.read"
            arguments = {"citation_ids": [self.citation]} if self.citation else self.selector or {}
        else:
            assert values[-1]["items"], values[-1]
            name, arguments = (
                "assistant.extract",
                {"citation_ids": [values[-1]["items"][0]["citation_id"]]},
            )
        return ModelTurn(
            calls=(ToolCall(id="synthetic-followup", name=name, arguments=arguments),),
            usage=ProviderUsage(10, 2),
        )


def parent(setup, count=1):
    ids = []
    for number in range(count):
        identity = register(setup, f"漏气处理记录 {number}", "更换密封圈。RAW_ONLY_CHILD_MARKER")
        index(setup, identity)
        ids.append(identity)
    client = SyntheticClient()
    owner, scope, host, adapter = fixture(setup, client)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    return ids, owner, scope, adapter, output


def continuation(setup, owner, scope, client):
    with owner.store.transaction(scope) as (_session, run):
        session_id = run.session_id
    return fixture(setup, client, session_id=session_id, continued_from_id=scope.run_id)


def test_frozen_child_citation_extracts_without_search_and_replays_without_inference(setup):
    ids, owner, scope, _adapter, output = parent(setup)
    original = output["result"]["assistant"]["citation_ids"][0]
    client = FollowupClient()
    child_owner, child, host, adapter = continuation(setup, owner, scope, client)
    frozen = child_owner.project_context(child, "上一条依据是什么？")["work_state"]
    ref = frozen["citations"][0]
    assert ref["citation_id"] != original and ref["origin_citation_id"] == original
    assert ref["origin_run_id"] == str(scope.run_id)
    assert "RAW_ONLY_CHILD_MARKER" not in str(frozen)
    client.citation = ref["citation_id"]
    answer = execute(child_owner, child, host)
    assert answer["status"] == "completed", answer
    final = answer["result"]["assistant"]
    assert final["lookup"] == "cited" and final["notice"] is None
    assert final["as_of"] is not None
    assert final["sources"][0]["source_id"] == str(ids[0])
    assert final["citation_ids"] == [ref["citation_id"]]
    with child_owner.store.transaction(child) as (session, _run):
        calls = session.scalars(
            select(AgentToolCall).where(AgentToolCall.run_id == child.run_id)
        ).all()
        assert not any(call.tool == "assistant.search" for call in calls)
        extracted = next(call for call in calls if call.tool == "assistant.extract")
        previous = deepcopy(extracted.result)
        fixed = ledger.issued(session, child)[ref["citation_id"]]
        assert fixed["origin_citation_id"] == original
        assert fixed["source_revision"] == final["sources"][0]["source_revision"]
    before = client.calls
    assert (
        adapter.restore_extract(child, {"citation_ids": [ref["citation_id"]]}, previous) == previous
    )
    source = setup.client.get(
        final["sources"][0]["url"].removeprefix("/api"), headers=setup.headers
    )
    assert source.status_code == 200 and "更换密封圈" in source.json()["text"]
    assert client.calls == before and before == 4
    saved = setup.client.get(f"/v1/personal/agent-runs/{child.run_id}", headers=setup.headers)
    assert saved.status_code == 200, saved.text


def test_reference_alias_resolves_across_three_turns_and_ledger_records_origin(setup):
    _ids, owner, scope, _adapter, output = parent(setup)
    root = output["result"]["assistant"]["citation_ids"][0]
    client = FollowupClient(selector={"reference_id": root})
    middle_owner, middle, host, adapter = continuation(setup, owner, scope, client)
    result = execute(middle_owner, middle, host)
    assert result["status"] == "completed", result
    alias = result["result"]["assistant"]["citation_ids"][0]
    with middle_owner.store.transaction(middle) as (session, _run):
        call = next(
            call for call, _ in ledger.completed(session, middle) if call.tool.endswith("read")
        )
        previous = deepcopy(call.result)
        assert previous["items"][0]["origin_run_id"] == str(scope.run_id)
    before = client.calls
    assert adapter.restore_citations(middle, {}, previous) == previous
    assert client.calls == before
    third_client = FollowupClient(selector={"reference_id": alias})
    third_owner, third, third_host, _adapter = continuation(
        setup, middle_owner, middle, third_client
    )
    result = execute(third_owner, third, third_host)
    assert result["status"] == "completed", result
    cid = result["result"]["assistant"]["citation_ids"][0]
    assert len({root, alias, cid}) == 3


def test_bounded_preview_and_pages_preserve_older_refs_without_research(setup):
    _ids, owner, scope, _adapter, _output = parent(setup, count=5)
    client = FollowupClient()
    child_owner, child, host, _adapter = continuation(setup, owner, scope, client)
    state = child_owner.project_context(child, "继续核对其他记录")["work_state"]
    assert len(state["citations"]) == 3
    directory = state["citation_directory"]
    assert directory["has_more"] and directory["next_cursor"]
    # A derivable CID outside the delivered preview is not an issued read.
    from pdos_next.enterprise_search.assistant_inheritance import fixed, registry

    with child_owner.store.transaction(child) as (session, run):
        roots, _rows = registry(session, run)
        unseen = fixed(child.run_id, list(roots.values())[3])["citation_id"]
        with pytest.raises(DomainError):
            ledger.select_issued(session, child, [UUID(unseen)])
    client.selector = {"cursor": directory["next_cursor"], "page_size": 1}
    output = execute(child_owner, child, host)
    assert output["status"] == "completed", output
    with child_owner.store.transaction(child) as (session, _run):
        call = next(
            call for call, _ in ledger.completed(session, child) if call.tool.endswith("read")
        )
        assert len(call.result["items"]) == 1 and call.result["has_more"]
        cid = call.result["items"][0]["citation_id"]
        assert cid not in {item["citation_id"] for item in state["citations"]}
        assert len(ledger.issued(session, child)) == 4


@pytest.mark.parametrize("change", ["withdrawn", "updated"])
def test_current_authority_rechecked_and_fixed_body_never_silently_replaced(setup, change):
    ids, owner, scope, _adapter, output = parent(setup)
    client = FollowupClient()
    child_owner, child, _host, adapter = continuation(setup, owner, scope, client)
    state = child_owner.project_context(child, "继续核对")["work_state"]
    ref = state["citations"][0]
    with Session(setup.admin) as session, session.begin():
        artifact = session.get(Artifact, ids[0])
        if change == "updated":
            artifact.revision += 1
        else:
            artifact.status = "withdrawn"
    if change == "withdrawn":
        with pytest.raises(DomainError) as error:
            child_owner.check_conversation(child)
        assert error.value.reason == "CONVERSATION_HISTORY_REVOKED"
        with pytest.raises(DomainError):
            adapter.guard(child)
        public = setup.client.get(
            f"/v1/personal/agent-sessions/{child.session_id}/work-state", headers=setup.headers
        )
        assert public.status_code == 200 and public.json()["citations"] == []
        assert ref["title"] not in public.text and ref["citation_id"] not in public.text
    else:
        child_owner.check_conversation(child)
        with human_snapshot(setup.engine, child) as session:
            run = session.get(AgentRun, child.run_id)
            continued = page(
                session, run, CitationsInput(reference_id=UUID(ref["origin_citation_id"]))
            )
            assert continued["items"][0]["currentness"] == "history"
            assert continued["items"][0]["source_revision"] == ref["source_revision"]
        selected = adapter._selected(child, [UUID(ref["citation_id"])])
        _actual, missing = adapter._current(child, selected, body=True)
        assert missing == {ref["citation_id"]: "source_changed"}
    assert client.calls == 0
    assert output["result"]["assistant"]["sources"][0]["source_revision"] == 1


def test_same_session_without_lineage_and_foreign_reference_do_not_expand_scope(setup):
    _ids, owner, scope, _adapter, output = parent(setup)
    cid = output["result"]["assistant"]["citation_ids"][0]
    with owner.store.transaction(scope) as (_session, run):
        session_id = run.session_id
    unrelated, other, _host, adapter = fixture(setup, FollowupClient(), session_id=session_id)
    assert unrelated.project_context(other, "新工作")["work_state"]["citations"] == []
    with pytest.raises(DomainError):
        adapter._selected(other, [UUID(cid)])
    child_owner, child, _host, _adapter = continuation(setup, owner, scope, FollowupClient())
    with human_snapshot(setup.engine, child) as session:
        run = session.get(AgentRun, child.run_id)
        with pytest.raises(DomainError):
            page(session, run, CitationsInput(reference_id=uuid4()))
        with pytest.raises(DomainError):
            page(session, run, CitationsInput(cursor=uuid4()))


def test_explicit_exclusion_is_versioned_and_keeps_refs_out_of_next_turn(setup):
    _ids, owner, scope, _adapter, output = parent(setup)
    cid = output["result"]["assistant"]["citation_ids"][0]
    child_owner, child, _host, _adapter = continuation(setup, owner, scope, FollowupClient())
    path = f"/v1/personal/agent-sessions/{child.session_id}/work-state"
    before = setup.client.get(path, headers=setup.headers).json()
    assert before["citations"][0]["citation_id"] == cid
    data = {
        "expected_revision": before["revision"],
        "request_key": str(uuid4()),
        "action": "exclude_source",
        "item_id": cid,
    }
    changed = setup.client.post(path, headers=setup.headers, json=data)
    assert changed.status_code == 200, changed.text
    assert changed.json()["exclusions"] == [
        {"id": cid, "kind": "citation", "reason": "用户标记不相关"}
    ]
    replay = setup.client.post(path, headers=setup.headers, json=data)
    assert replay.status_code == 200 and replay.json()["revision"] == changed.json()["revision"]
    frozen = child_owner.project_context(child, "换一个依据")["work_state"]
    assert frozen["citations"] == [] and not frozen["citation_directory"]["has_more"]
    with human_snapshot(setup.engine, child) as session:
        run = session.get(AgentRun, child.run_id)
        selected = page(session, run, CitationsInput(reference_id=UUID(cid)), excluded={cid})
        assert selected["items"] == []
    remove = setup.client.post(
        path,
        headers=setup.headers,
        json={
            "expected_revision": changed.json()["revision"],
            "request_key": str(uuid4()),
            "action": "remove_exclusion",
            "item_id": cid,
        },
    )
    assert remove.status_code == 200, remove.text
    assert child_owner.project_context(child, "运行中仍冻结")["work_state"] == frozen


def test_real_new_knowledge_version_preserves_old_fixed_citation_and_labels_history(setup):
    from pdos_next.domain.preproject.category_models import KnowledgeEntry
    from pdos_next.enterprise_search.indexing import project
    from tests.enterprise_search.test_retrieval_pg import session_for

    created = post(
        setup,
        request(
            setup,
            "category.knowledge.add",
            {
                "kind": "boundary",
                "content": {"definition": "漏气处理：更换密封圈。原固定依据。"},
            },
        ),
    )
    assert created.status_code == 200, created.text
    with session_for(setup) as session:
        row = session.scalar(
            select(KnowledgeEntry).where(
                KnowledgeEntry.lineage_id == UUID(created.json()["subject_id"])
            )
        )
        project(session, setup.ctx, "knowledge", row.id)
    owner, scope, host, _adapter = fixture(setup, SyntheticClient())
    first = execute(owner, scope, host)
    assert first["status"] == "completed", first
    changed = post(
        setup,
        request(
            setup,
            "category.knowledge.add",
            {
                "kind": "boundary",
                "content": {"definition": "漏气改用新的验证方法。"},
                "supersedes": {"lineage_id": created.json()["subject_id"], "expected_version": 1},
            },
        ),
    )
    assert changed.status_code == 200, changed.text
    client = FollowupClient()
    child_owner, child, child_host, _adapter = continuation(setup, owner, scope, client)
    ref = child_owner.project_context(child, "原依据说了什么？")["work_state"]["citations"][0]
    assert ref["currentness"] == "history" and ref["source_revision"] == 1
    client.citation = ref["citation_id"]
    output = execute(child_owner, child, child_host)
    assert output["status"] == "completed", output
    answer = output["result"]["assistant"]
    assert answer["sources"][0]["currentness"] == "history"
    assert "原历史版本" in answer["notice"] and "原固定依据" in answer["sources"][0]["quote"]
    assert "新的验证方法" not in str(answer)
    assert answer["as_of"] and client.child_calls == 0 and client.calls == 2
