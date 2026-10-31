"""Knowledge dependency authority precedes HTTP metadata, paging and counts."""
# ruff: noqa: F811 -- explicitly register the actual scan fixture

import statistics
import time
from dataclasses import replace
from uuid import UUID

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from pdos_next.enterprise_search.query import SearchInput, search
from pdos_next.models import Artifact
from pdos_next.original_security import configure
from tests.enterprise_search.test_knowledge_dependencies_pg import indexed_knowledge
from tests.enterprise_search.test_retrieval_pg import index, query, register, session_for
from tests.preproject.test_g0 import post, request
from tests.test_original_security import parsed, uploaded
from tests.test_original_security import security_work as security_work


def reference(identity, *, kind="artifact", quote="漏气"):
    value = {"type": kind, "id": str(identity), "version": 1}
    if kind != "claim":
        value.update(line=1, quote=quote)
    return value


def test_unreadable_knowledge_is_removed_before_limit_and_truncation_without_reindex(setup):
    visible = indexed_knowledge(setup, reference(register(setup, "有效依据", "漏气处理。")),
                                definition="漏气有效记录，核对密封圈。")
    hidden = []
    for number in range(3):
        root = register(setup, f"待撤回依据 {number}", "漏气处理。")
        entry = indexed_knowledge(setup, reference(root),
                                  definition=f"漏气漏气漏气，隐藏知识编号 {number}。")
        hidden.append(entry)
        with Session(setup.admin) as session, session.begin():
            session.get(Artifact, root).status = "withdrawn"
    page = query(setup, "漏气", source_types=["knowledge"], limit=1)
    assert page["returned"] == 1 and page["truncated"] is False, page
    assert page["items"][0]["source_id"] == str(visible)
    assert not any(str(identity) in str(page) for identity in hidden)
    all_rows = query(setup, "漏气", source_types=["knowledge"], include_history=True)
    assert all_rows["returned"] == 1 and all_rows["truncated"] is False


def test_changed_knowledge_dependency_obeys_current_fixed_version(setup):
    root = register(setup, "共享依据", "漏气处理。")
    entry = indexed_knowledge(setup, reference(root))
    assert query(setup, "漏气", source_types=["knowledge"])["returned"] == 1
    with Session(setup.admin) as session, session.begin():
        row = session.get(Artifact, root)
        row.revision += 1
    peer = query(setup, "漏气", actor=setup.peer, personal=True, source_types=["knowledge"])
    assert peer["returned"] == 0 and peer["truncated"] is False
    assert str(entry) not in str(peer)
    owner = query(setup, "漏气", source_types=["knowledge"])
    assert owner["returned"] == 0


def test_private_root_cannot_enter_shared_knowledge_or_search_metadata(setup):
    root = register(setup, "本人私有依据", "漏气处理。", visibility="private")
    rejected = post(setup, request(setup, "category.knowledge.add", {
        "kind": "boundary", "content": {"definition": "漏气私有内容不允许共享。"},
        "source_refs": [reference(root)],
    }))
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["reason"] == "private_source_in_shared"
    page = query(setup, "漏气", actor=setup.peer, personal=True, source_types=["knowledge"])
    assert page["returned"] == 0 and str(root) not in str(page)


def test_named_claim_withdrawal_removes_dependent_search_metadata_without_reindex(setup):
    root = register(setup, "事实依据", "更换密封圈。")
    recorded = post(setup, request(setup, "evidence.claim.record", {
        "source": {"kind": "artifact", "id": str(root), "version": 1,
                   "line": 1, "quote": "更换密封圈"},
        "content": {"text": "漏气处理更换密封圈。"},
    }))
    assert recorded.status_code == 200, recorded.text
    entry = indexed_knowledge(setup, reference(UUID(recorded.json()["subject_id"]), kind="claim"))
    assert query(setup, "漏气", source_types=["knowledge"])["returned"] == 1
    command = request(setup, "evidence.claim.withdraw", {
        "claim_id": recorded.json()["subject_id"], "expected_version": 1,
        "reason": "合成事实具名撤回",
    })
    preview = post(setup, command, preview=True)
    assert preview.status_code == 200, preview.text
    withdrawn = post(setup, preview.json()["command"])
    assert withdrawn.status_code == 200, withdrawn.text
    page = query(setup, "漏气", source_types=["knowledge"], include_history=True)
    assert page["returned"] == 0 and str(entry) not in str(page)


def test_knowledge_original_scan_proof_precedes_http_metadata(security_work):
    work, setup = security_work, security_work.setup
    root = parsed(work, uploaded(work, visibility="category", content="更换密封圈。".encode()))
    entry = indexed_knowledge(setup, reference(root, quote="更换密封圈"))
    good = query(setup, "漏气", source_types=["knowledge"])
    assert good["returned"] == 1 and good["items"][0]["customer_original"] is True
    scan_calls = work.scanner.calls
    configuration = replace(work.runtime.configuration, scanner=replace(
        work.runtime.configuration.scanner, rules_version="knowledge-search-current-proof@2"))
    configure(setup.engine, replace(work.runtime, configuration=configuration))
    page = query(setup, "漏气", source_types=["knowledge"])
    assert page["returned"] == 0 and str(entry) not in str(page)
    assert work.scanner.calls == scan_calls


@pytest.mark.parametrize("through_claim", [False, True])
def test_registered_snapshot_dependency_remains_in_ordinary_current_authority(
    setup, tmp_path, through_claim,
):
    from tests.agent_kernel.test_snapshot_proof_transactions import registration

    _parent, snapshot, _receipt = registration(setup, tmp_path, human=True)
    ref = reference(snapshot.id, kind="snapshot", quote="合成目录😀")
    if through_claim:
        response = post(setup, request(setup, "evidence.claim.record", {
            "source": {"kind": "snapshot", "id": str(snapshot.id), "version": 1,
                       "line": 1, "quote": "合成目录😀"},
            "content": {"text": "漏气案例的登记网页依据。"},
        }))
        assert response.status_code == 200, response.text
        ref = reference(UUID(response.json()["subject_id"]), kind="claim")
    entry = indexed_knowledge(setup, ref)
    page = query(setup, "漏气", source_types=["knowledge"])
    assert page["returned"] == 1 and page["items"][0]["source_id"] == str(entry)
    assert page["items"][0]["customer_original"] is False
    assert snapshot.markdown not in str(page)


def test_knowledge_dependency_sql_count_is_batched_and_warm_latency_under_one_second(
    setup, record_property,
):
    roots = [register(setup, f"复用依据 {i}", "更换密封圈。") for i in range(2)]
    for root in roots:
        index(setup, root)
    for i in range(8):
        indexed_knowledge(setup, reference(roots[i % 2], quote="更换密封圈"),
                          definition=f"漏气知识 {i}：更换密封圈。")
    statements, counts, timings = [], [], []

    def count(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(setup.engine, "before_cursor_execute", count)
    try:
        for limit in [1] + [8] * 12:
            with session_for(setup, personal=True) as session:
                statements.clear()
                started = time.perf_counter()
                page = search(session, replace(setup.ctx, category_id=None), SearchInput(
                    query="漏气", source_types=["artifact", "knowledge"], limit=limit))
                elapsed = time.perf_counter() - started
                assert page["returned"] == limit
                counts.append(len(statements))
                if limit == 8:
                    timings.append(elapsed)
    finally:
        event.remove(setup.engine, "before_cursor_execute", count)
    p95 = statistics.quantiles(timings, n=20)[18]
    record_property("knowledge_retrieval_p95_seconds", p95)
    record_property("knowledge_retrieval_sql_counts", counts)
    record_property("knowledge_retrieval_sources", 8)
    record_property("knowledge_retrieval_samples", len(timings))
    assert len(set(counts)) == 1 and counts[0] == 3, counts
    assert p95 < 1.0
