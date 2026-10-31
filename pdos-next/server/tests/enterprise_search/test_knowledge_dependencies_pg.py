"""Actual knowledge reads preserve history while reauthorizing every fixed old root."""
# ruff: noqa: F811 -- explicitly register the actual scan fixture

import statistics
import time
from copy import deepcopy
from dataclasses import replace
from uuid import UUID

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.domain.preproject.category_models import KnowledgeEntry
from pdos_next.enterprise_search import assistant_ledger as ledger
from pdos_next.enterprise_search.assistant_sources import current, human_snapshot
from pdos_next.enterprise_search.indexing import project
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Claim, Grant
from pdos_next.original_security import configure
from tests.enterprise_search.test_assistant_pg import SyntheticClient, execute, fixture
from tests.enterprise_search.test_citation_inheritance_pg import FollowupClient, continuation
from tests.enterprise_search.test_retrieval_pg import index, register, session_for
from tests.preproject.test_g0 import post, request
from tests.test_original_security import parsed, uploaded
from tests.test_original_security import security_work as security_work


class KnowledgeClient(SyntheticClient):
    def turn(self, route, **kwargs):
        turn = super().turn(route, **kwargs)
        if turn.calls and turn.calls[0].name == "assistant.search":
            return replace(turn, calls=(turn.calls[0].model_copy(update={"arguments": {
                "query": "漏气", "source_types": ["knowledge"],
            }}),))
        return turn


def indexed_knowledge(setup, ref, *, definition="漏气处理：更换密封圈。原知识说明。"):
    response = post(setup, request(setup, "category.knowledge.add", {
        "kind": "boundary", "content": {"definition": definition},
        "source_refs": [ref],
    }))
    assert response.status_code == 200, response.text
    with session_for(setup) as session:
        row = session.scalar(select(KnowledgeEntry).where(
            KnowledgeEntry.lineage_id == UUID(response.json()["subject_id"])))
        project(session, setup.ctx, "knowledge", row.id)
        return row.id


def knowledge(setup, ref):
    indexed_knowledge(setup, ref)
    client = KnowledgeClient()
    owner, scope, host, adapter = fixture(setup, client)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    assert client.calls == 3 and client.child_calls == 0
    with owner.store.transaction(scope) as (session, _run):
        selected = ledger.issued(session, scope)
    item = next(iter(selected.values()))
    assert item["source_type"] == "knowledge" and item["dependency_basis"]["version"] == 1
    assert "原知识说明" not in str(item["dependency_basis"])
    return owner, scope, adapter, client, output, selected


def history(setup, scope):
    return setup.client.get(f"/v1/personal/agent-runs/{scope.run_id}", headers=setup.headers)


def test_artifact_dependency_update_keeps_answer_but_never_extracts_a_new_body(setup):
    source = register(setup, "知识的合成依据", "更换密封圈。")
    owner, scope, adapter, client, _output, selected = knowledge(setup, {
        "type": "artifact", "id": str(source), "version": 1, "line": 1, "quote": "更换密封圈",
    })
    with Session(setup.admin) as session, session.begin():
        session.get(Artifact, source).revision += 1
    response = history(setup, scope)
    assert response.status_code == 200, response.text
    answer = response.json()["result"]["result"]["assistant"]
    assert answer["sources"][0]["currentness"] == "updated"
    assert answer["sources"][0]["read_basis_status"] == "needs_recheck"
    assert answer["sources"][0]["fixed_body_available"] is True
    assert "原知识说明" in str(answer) and "资料已更新" in answer["notice"]
    with human_snapshot(setup.engine, scope) as session:
        actual, missing = current(session, selected, with_body=True)
        assert not actual and set(missing.values()) == {"source_dependency_changed"}
        legacy = deepcopy(selected)
        for item in legacy.values():
            item.pop("dependency_basis")
        assert current(session, legacy, allow_updated=set(legacy))[1]
    with owner.store.transaction(scope) as (session, _run):
        call = session.scalar(select(AgentToolCall).where(
            AgentToolCall.run_id == scope.run_id, AgentToolCall.tool == "assistant.search"))
        original = deepcopy(call.result)
    with pytest.raises(DomainError) as failure:
        adapter.restore_search(scope, {"query": "漏气", "source_types": ["knowledge"]}, original)
    assert failure.value.code == "SOURCE_STALE"
    child_client = FollowupClient()
    child_owner, child, child_host, _adapter = continuation(setup, owner, scope, child_client)
    context = child_owner.project_context(child, "原说明还在吗？")
    assert context["work_state"]["citations"][0]["currentness"] == "history"
    assert context["work_state"]["citations"][0]["read_basis_status"] == "needs_recheck"
    turn = context["conversation"]["turns"][0]
    assert turn["outcome_state"] == "updated"
    assert turn["historical_outcome"]["summary"] == _output["summary"]
    child_client.citation = context["work_state"]["citations"][0]["citation_id"]
    continued = execute(child_owner, child, child_host)
    assert continued["status"] == "completed", continued
    fixed = continued["result"]["assistant"]
    assert fixed["sources"][0]["currentness"] == "history"
    assert fixed["sources"][0]["read_basis_status"] == "needs_recheck"
    assert "当前适用性待重核" in fixed["notice"]
    opened = setup.client.get(
        fixed["sources"][0]["url"].removeprefix("/api"), headers=setup.headers)
    assert opened.status_code == 200, opened.text
    assert "原知识说明" in opened.json()["text"]
    assert opened.json()["read_basis_status"] == "needs_recheck"
    assert child_client.calls == 2 and child_client.child_calls == 0
    assert client.calls == 3
    with Session(setup.admin) as session, session.begin():
        session.get(Artifact, source).status = "withdrawn"
    assert history(setup, scope).status_code == 403
    with pytest.raises(DomainError):
        child_owner.check_conversation(child)
    assert client.calls == 3


def test_primary_revision_change_never_offers_a_replacement_body_as_the_old_fixed_snippet(setup):
    source = register(setup, "漏气原固定资料", "更换密封圈。RAW_ONLY_CHILD_MARKER")
    index(setup, source)
    client = SyntheticClient()
    owner, scope, host, _adapter = fixture(setup, client)
    assert execute(owner, scope, host)["status"] == "completed"
    with Session(setup.admin) as session, session.begin():
        session.get(Artifact, source).revision += 1
    response = history(setup, scope)
    assert response.status_code == 200, response.text
    card = response.json()["result"]["result"]["assistant"]["sources"][0]
    assert card["currentness"] == "updated" and card["fixed_body_available"] is False
    opened = setup.client.get(card["url"].removeprefix("/api"), headers=setup.headers)
    assert opened.status_code == 409 and opened.json()["code"] == "SOURCE_UNAVAILABLE"
    assert "RAW_ONLY_CHILD_MARKER" not in opened.text
    assert client.calls == 5 and client.child_calls == 2
    owner.store.current(scope)


@pytest.mark.parametrize("revoked", ["old_root", "claim"])
def test_claim_dependency_keeps_fixed_root_and_named_withdrawal_in_the_read_proof(setup, revoked):
    source = register(setup, "原知识依据", "更换密封圈。")
    newer = register(setup, "后续依据", "更换密封圈。新的依据说明。")
    response = post(setup, request(setup, "evidence.claim.record", {
        "source": {"kind": "artifact", "id": str(source), "version": 1,
                   "line": 1, "quote": "更换密封圈"},
        "content": {"text": "漏气处理更换密封圈。"},
    }))
    assert response.status_code == 200, response.text
    claim_id = UUID(response.json()["subject_id"])
    owner, scope, _adapter, client, _output, selected = knowledge(setup, {
        "type": "claim", "id": str(claim_id), "version": 1,
    })
    with pytest.raises(DBAPIError, match="claim only permits named withdrawal"):
        with Session(setup.admin) as session, session.begin():
            claim = session.get(Claim, claim_id)
            claim.artifact_id, claim.revision = newer, 2
    with Session(setup.admin) as session, session.begin():
        assert session.get(Claim, claim_id).artifact_id == source
        session.get(Artifact, source).revision += 1
    response = history(setup, scope)
    assert response.status_code == 200, response.text
    answer = response.json()["result"]["result"]["assistant"]
    assert answer["sources"][0]["currentness"] == "updated"
    assert "原知识说明" in str(answer) and "新的依据说明" not in str(answer)
    with human_snapshot(setup.engine, scope) as session:
        actual, missing = current(session, selected, allow_updated=set(selected))
        assert not missing and all(row["updated"] for row in actual.values())
        corrupt = deepcopy(selected)
        next(iter(corrupt.values()))["dependency_basis"]["dependencies"] = []
        assert current(session, corrupt, allow_updated=set(corrupt))[1]
    if revoked == "old_root":
        with Session(setup.admin) as session, session.begin():
            session.get(Artifact, source).status = "withdrawn"
    else:
        withdrawal = request(setup, "evidence.claim.withdraw", {
            "claim_id": str(claim_id), "expected_version": 1, "reason": "合成事实具名撤回",
        })
        preview = post(setup, withdrawal, preview=True)
        assert preview.status_code == 200, preview.text
        withdrawn = post(setup, preview.json()["command"])
        assert withdrawn.status_code == 200, withdrawn.text
    with Session(setup.admin) as session:
        assert session.get(Artifact, newer).status == "active"
    assert history(setup, scope).status_code == 403
    assert client.calls == 3 and client.child_calls == 0
    owner.store.current(scope)


def test_updated_knowledge_dependency_still_uses_actual_original_scan_proofs(security_work):
    work, setup = security_work, security_work.setup
    source = parsed(work, uploaded(work, visibility="category", content="更换密封圈。".encode()))
    _owner, scope, _adapter, client, _output, selected = knowledge(setup, {
        "type": "artifact", "id": str(source), "version": 1, "line": 1, "quote": "更换密封圈",
    })
    scans = work.scanner.calls
    root = next(iter(selected.values()))["dependency_basis"]["dependencies"][0]["root"]
    assert root["original_id"]
    with Session(setup.admin) as session, session.begin():
        session.get(Artifact, source).revision += 1
    assert history(setup, scope).status_code == 200
    configuration = replace(work.runtime.configuration, scanner=replace(
        work.runtime.configuration.scanner, rules_version="knowledge-dependency-changed@2"))
    configure(setup.engine, replace(work.runtime, configuration=configuration))
    assert history(setup, scope).status_code == 403
    assert work.scanner.calls == scans and client.calls == 3 and client.child_calls == 0


def test_registered_snapshot_dependency_is_signed_without_original_text_and_cannot_be_retargeted(
    setup, tmp_path,
):
    from tests.agent_kernel.test_snapshot_proof_transactions import registration

    _parent, snapshot, _receipt = registration(setup, tmp_path, human=True)
    _owner, scope, _adapter, client, _output, selected = knowledge(setup, {
        "type": "snapshot", "id": str(snapshot.id), "version": 1,
        "line": 1, "quote": "合成目录😀",
    })
    root = next(iter(selected.values()))["dependency_basis"]["dependencies"][0]["root"]
    assert root["type"] == "snapshot" and root["content_hash"] == snapshot.content_hash
    assert snapshot.markdown not in str(selected)
    corrupt = deepcopy(selected)
    next(iter(corrupt.values()))["dependency_basis"]["dependencies"][0]["root"]["version"] = 2
    with human_snapshot(setup.engine, scope) as session:
        assert current(session, corrupt, allow_updated=set(corrupt))[1]
    assert history(setup, scope).status_code == 200
    with Session(setup.admin) as session, session.begin():
        session.delete(session.scalar(select(Grant).where(
            Grant.category_id == setup.category, Grant.principal_id == setup.human)))
    assert history(setup, scope).status_code == 403
    assert client.calls == 3 and client.child_calls == 0


def test_knowledge_dependency_rechecks_batch_claims_and_roots_with_bounded_warm_latency(
    setup, record_property,
):
    claims = []
    for number in range(2):
        source = register(setup, f"内部知识依据 {number}", "更换密封圈。")
        response = post(setup, request(setup, "evidence.claim.record", {
            "source": {"kind": "artifact", "id": str(source), "version": 1,
                       "line": 1, "quote": "更换密封圈"},
            "content": {"text": "漏气处理更换密封圈。"},
        }))
        assert response.status_code == 200, response.text
        claims.append(response.json()["subject_id"])
    for number in range(6):
        indexed_knowledge(setup, {"type": "claim", "id": claims[number % 2], "version": 1},
                          definition=f"漏气处理：更换密封圈。原知识说明 {number}。")
    owner, scope, host, _adapter = fixture(setup, KnowledgeClient())
    assert execute(owner, scope, host)["status"] == "completed"
    with owner.store.transaction(scope) as (session, _run):
        selected = ledger.issued(session, scope)
    assert len(selected) == 6
    statements, counts, durations = [], [], []

    def counted(*_args):
        statements.append(True)

    event.listen(setup.engine, "before_cursor_execute", counted)
    try:
        with human_snapshot(setup.engine, scope) as session:
            statements.clear()
            one = dict(list(selected.items())[:1])
            assert not current(session, one, allow_updated=set(one))[1]
            baseline = len(statements)
        for _ in range(12):
            with human_snapshot(setup.engine, scope) as session:
                statements.clear()
                start = time.perf_counter()
                actual, missing = current(session, selected, allow_updated=set(selected))
                durations.append(time.perf_counter() - start)
                counts.append(len(statements))
                assert len(actual) == 6 and not missing
    finally:
        event.remove(setup.engine, "before_cursor_execute", counted)
    p95 = statistics.quantiles(durations, n=20)[18]
    record_property("knowledge_dependency_warm_p95_seconds", p95)
    record_property("knowledge_dependency_queries_per_request", str(sorted(set(counts))))
    record_property("knowledge_dependency_sources", 6)
    record_property("knowledge_dependency_samples", len(durations))
    assert set(counts) == {baseline} and baseline == 3
    assert p95 < 1.0
