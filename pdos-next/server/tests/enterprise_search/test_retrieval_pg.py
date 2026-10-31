"""Actual command→Outbox→projection→RR/RLS metadata retrieval. No model calls."""

import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.enterprise_search.events import process_event
from pdos_next.enterprise_search.indexing import project, rebuild
from pdos_next.enterprise_search.models import SearchChunk, SearchCorpus, SearchTerm
from pdos_next.enterprise_search.query import SearchInput, search
from pdos_next.models import Artifact, Grant, Outbox, Receipt
from tests.preproject.test_g0 import post, request


def register(setup, title, body, visibility="category"):
    response = post(
        setup,
        request(
            setup,
            "evidence.artifact.register",
            {
                "title": title,
                "content": body,
                "source_label": "企业检索合成材料",
                "visibility": visibility,
            },
        ),
    )
    assert response.status_code == 200, response.text
    return UUID(response.json()["subject_id"])


def session_for(setup, *, actor=None, personal=False):
    return tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=actor or setup.human,
        requester_id=actor or setup.human,
        category_id=None if personal else setup.category,
    )


def index(setup, identity):
    with session_for(setup) as session:
        return project(session, setup.ctx, "artifact", identity)


def query(setup, text, *, actor=None, personal=False, **kwargs):
    path = (
        "/v1/personal/enterprise-search"
        if personal
        else f"/v1/categories/{setup.category}/enterprise-search"
    )
    response = setup.client.post(
        path,
        headers={"Authorization": f"Bearer {setup.tokens[actor or setup.human]}"},
        json={"query": text, **kwargs},
    )
    assert response.status_code == 200, response.text
    return response.json()


def event_reference(setup, identity):
    with Session(setup.admin) as session:
        outbox, receipt = session.execute(
            select(Outbox, Receipt)
            .join(Receipt, Outbox.receipt_id == Receipt.id)
            .where(Outbox.subject_id == identity)
        ).one()
        return {
            "tenant_id": str(setup.tenant),
            "category_id": str(setup.category),
            "actor_id": str(outbox.actor_id),
            "requester_id": str(receipt.requester_id),
            "event_id": str(outbox.id),
            "subject_id": str(identity),
            "subject_revision": outbox.subject_revision,
            "event_type": outbox.type,
        }


def test_or_recall_identifier_priority_and_no_raw_text_in_http_result(setup):
    exact = register(
        setup, "D16-01 气密复验记录", "连接头漏气，处理措施是更换密封圈。独有正文标记NO_RAW_TEXT。"
    )
    family = register(setup, "D16-02 旧项目记录", "装配时出现漏气问题。")
    generic = register(setup, "常见问题处理", "问题处理问题处理，不涉及气密。")
    for identity in (exact, family, generic):
        index(setup, identity)
    found = query(setup, "D16-01以前漏气怎么处理，还有根因和复验呢")
    assert found["items"][0]["source_id"] == str(exact)
    assert found["items"][0]["channel"] == "exact_code"
    assert str(family) in {item["source_id"] for item in found["items"]}
    assert "NO_RAW_TEXT" not in str(found) and "text" not in found["items"][0]
    assert found["query_trace"]["codes"] == ["D16-01"]
    assert found["coverage"]["indexed_as_of"] is not None
    assert found["coverage"]["indexed_as_of"] <= found["as_of"]
    assert query(setup, "D16")["items"][0]["channel"] == "code_family"
    direct = query(setup, str(exact))
    assert (
        direct["items"][0]["source_id"] == str(exact)
        and direct["items"][0]["channel"] == "exact_id"
    )


def test_authoritative_private_scope_and_tenant_filter_precede_returned_counts(setup):
    shared = register(setup, "公开可读气密记录", "漏气与密封圈。")
    private = register(setup, "PRIVATE_OWNER_TITLE", "漏气与密封圈。", visibility="private")
    for identity in (shared, private):
        index(setup, identity)
    owner = query(setup, "漏气")
    peer = query(setup, "漏气", actor=setup.peer, personal=True)
    assert owner["returned"] == 2 and peer["returned"] == 1
    assert {item["source_id"] for item in peer["items"]} == {str(shared)}
    assert str(private) not in str(peer) and "PRIVATE_OWNER_TITLE" not in str(peer)
    other = setup.client.post(
        "/v1/personal/enterprise-search",
        json={"query": "漏气"},
        headers={"Authorization": f"Bearer {setup.tokens[setup.other_human]}"},
    )
    assert other.status_code == 200 and other.json()["returned"] == 0
    denied = setup.client.post(
        "/v1/personal/enterprise-search",
        json={"query": "漏气", "category_id": str(setup.category)},
        headers={"Authorization": f"Bearer {setup.tokens[setup.other_human]}"},
    )
    assert denied.status_code == 403


def test_outbox_replay_and_full_rebuild_do_not_duplicate_df_or_business_facts(setup):
    identity = register(setup, "D16 气密记录", "漏气，复验。")
    with Session(setup.admin) as session:
        outbox, receipt = session.execute(
            select(Outbox, Receipt)
            .join(Receipt, Outbox.receipt_id == Receipt.id)
            .where(Outbox.subject_id == identity)
        ).one()
        reference = {
            "tenant_id": str(setup.tenant),
            "category_id": str(setup.category),
            "actor_id": str(outbox.actor_id),
            "requester_id": str(receipt.requester_id),
            "event_id": str(outbox.id),
            "subject_id": str(identity),
            "subject_revision": outbox.subject_revision,
            "event_type": outbox.type,
        }
        facts = session.scalar(
            select(func.count()).select_from(Receipt).where(Receipt.tenant_id == setup.tenant)
        )
    assert process_event(setup.engine, reference) == {"processed": 1, "changed": 1}
    assert process_event(setup.engine, reference) == {"processed": 1, "changed": 0}
    with session_for(setup) as session:
        before = session.get(SearchCorpus, setup.tenant)
        expected = before.chunk_count, before.token_count
        frequencies = dict(
            session.execute(select(SearchTerm.term, SearchTerm.document_count)).all()
        )
    assert rebuild(setup.engine, setup.ctx)["processed"] == 1
    with session_for(setup) as session:
        after = session.get(SearchCorpus, setup.tenant)
        assert (after.chunk_count, after.token_count) == expected
        assert (
            dict(session.execute(select(SearchTerm.term, SearchTerm.document_count)).all())
            == frequencies
        )
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Receipt).where(Receipt.tenant_id == setup.tenant)
            )
            == facts
        )


def test_withdrawal_and_membership_revocation_take_effect_without_reindex(setup):
    identity = register(setup, "撤回前的记录", "漏气复验。")
    index(setup, identity)
    assert query(setup, "漏气")["returned"] == 1
    with Session(setup.admin) as session, session.begin():
        session.get(Artifact, identity).status = "withdrawn"
    assert query(setup, "漏气")["returned"] == 0
    with session_for(setup) as session:
        assert project(session, setup.ctx, "artifact", identity)["status"] == "unavailable"
        assert session.get(SearchCorpus, setup.tenant).chunk_count == 0
    another = register(setup, "仍有效的记录", "漏气复验。")
    index(setup, another)
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.category_id == setup.category, Grant.principal_id == setup.human
            )
        )
        session.delete(grant)
    assert query(setup, "漏气", personal=True)["returned"] == 0


def test_query_count_is_constant_and_local_warm_latency_below_one_second(setup, record_property):
    for i in range(8):
        index(setup, register(setup, f"D{i + 10}-01 复验", "气密性漏气问题，核对工况。"))
    statements, durations = [], []

    def count(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(setup.engine, "before_cursor_execute", count)
    try:
        for _ in range(12):
            with session_for(setup, personal=True) as session:
                statements.clear()
                begin = time.perf_counter()
                result = search(
                    session, replace(setup.ctx, category_id=None), SearchInput(query="漏气怎么复验")
                )
                durations.append(time.perf_counter() - begin)
                assert result["returned"] == 8
                # Disable JIT before RLS planning, then presence, dependencies and page/health.
                assert statements[0] == "SET LOCAL jit=off"
                assert len(statements) == 4, len(statements)
    finally:
        event.remove(setup.engine, "before_cursor_execute", count)
    p95 = statistics.quantiles(durations, n=20)[18]
    record_property("keyword_warm_p95_seconds", p95)
    record_property("keyword_queries_per_request", 4)
    record_property("keyword_source_count", 8)
    record_property("keyword_samples", len(durations))
    assert p95 < 1.0


def test_missing_or_corrupt_projection_is_partial_and_never_leaks_wrong_scope(setup):
    identity = register(setup, "待索引的气密记录", "漏气复验。")
    pending = query(setup, "漏气")
    assert pending["items"] == [] and pending["coverage"]["status"] == "partial"
    index(setup, identity)
    assert query(setup, "漏气")["coverage"]["status"] == "current"
    with Session(setup.admin) as session, session.begin():
        row = session.scalar(select(SearchChunk).where(SearchChunk.source_id == identity))
        row.category_id = uuid4()  # Only this synthetic corrupt derived row; no authority changes.
    hidden = query(setup, "漏气")
    assert hidden["items"] == [] and hidden["coverage"]["status"] == "partial"
    assert str(identity) not in str(hidden)


def test_knowledge_versions_are_fixed_and_withdrawal_invalidates_history_without_reindex(setup):
    from pdos_next.domain.preproject.category_models import KnowledgeEntry

    first = post(
        setup,
        request(
            setup,
            "category.knowledge.add",
            {
                "kind": "boundary",
                "content": {"definition": "D16 气密性，漏气先核对密封圈。"},
            },
        ),
    )
    assert first.status_code == 200, first.text
    lineage = UUID(first.json()["subject_id"])
    with session_for(setup) as session:
        old = session.scalar(select(KnowledgeEntry).where(KnowledgeEntry.lineage_id == lineage))
        old_id = old.id
        assert project(session, setup.ctx, "knowledge", old_id)["status"] == "ready"
    second = post(
        setup,
        request(
            setup,
            "category.knowledge.add",
            {
                "kind": "boundary",
                "content": {"definition": "D16 气密性，漏气采用新的复验流程。"},
                "supersedes": {"lineage_id": str(lineage), "expected_version": 1},
            },
        ),
    )
    assert second.status_code == 200, second.text
    with session_for(setup) as session:
        current = session.scalar(
            select(KnowledgeEntry).where(
                KnowledgeEntry.lineage_id == lineage,
                KnowledgeEntry.version == 2,
            )
        )
        new_id = current.id
        project(session, setup.ctx, "knowledge", new_id)
    latest = query(setup, "漏气", source_types=["knowledge"])
    assert [item["source_id"] for item in latest["items"]] == [str(new_id)]
    history = query(setup, "漏气", source_types=["knowledge"], include_history=True)
    assert {item["source_id"] for item in history["items"]} == {str(old_id), str(new_id)}
    assert (
        next(item for item in history["items"] if item["source_id"] == str(old_id))["is_current"]
        is False
    )
    assert all(item["nature"] == "structured" for item in history["items"])
    # A source withdrawal is the existing confirmed domain operation, not index mutation.
    from tests.preproject.test_g0 import save

    save(
        setup,
        request(
            setup,
            "category.knowledge.withdraw",
            {
                "lineage_id": str(lineage),
                "expected_version": 2,
                "reason": "合成知识撤回",
            },
        ),
    )
    assert query(setup, "漏气", source_types=["knowledge"], include_history=True)["returned"] == 0


def test_projection_failure_is_recorded_then_same_event_recovers(setup, monkeypatch):
    from pdos_next.enterprise_search import indexing
    from pdos_next.enterprise_search.models import SearchSource
    from pdos_next.errors import DomainError

    identity = register(setup, "气密投影恢复", "漏气复验。")
    with Session(setup.admin) as session:
        outbox, receipt = session.execute(
            select(Outbox, Receipt)
            .join(
                Receipt,
                Outbox.receipt_id == Receipt.id,
            )
            .where(Outbox.subject_id == identity)
        ).one()
        reference = {
            "tenant_id": str(setup.tenant),
            "category_id": str(setup.category),
            "actor_id": str(outbox.actor_id),
            "requester_id": str(receipt.requester_id),
            "event_id": str(outbox.id),
            "subject_id": str(identity),
            "subject_revision": outbox.subject_revision,
            "event_type": outbox.type,
        }

    def unavailable(*_args, **_kwargs):
        raise DomainError("SOURCE_UNAVAILABLE", "Synthetic index failure")

    with monkeypatch.context() as patch:
        patch.setattr(indexing, "chunks", unavailable)
        with pytest.raises(DomainError):
            process_event(setup.engine, reference)
    with session_for(setup) as session:
        state = session.scalar(select(SearchSource).where(SearchSource.source_id == identity))
        assert state.status == "failed" and state.last_error == "SOURCE_UNAVAILABLE"
    assert process_event(setup.engine, reference)["changed"] == 1
    assert query(setup, "漏气")["returned"] == 1
    with session_for(setup) as session:
        state = session.scalar(select(SearchSource).where(SearchSource.source_id == identity))
        assert state.status == "ready" and state.last_error is None


def test_projection_rejects_forged_envelopes_and_revoked_background_actor(setup):
    from pdos_next.enterprise_search.models import SearchSource
    from pdos_next.errors import DomainError

    identity = register(setup, "不能伪造的实际来源", "漏气复验。")
    reference = event_reference(setup, identity)
    for key, value in (
        ("event_id", str(uuid4())),
        ("subject_id", str(uuid4())),
        ("subject_revision", 2),
        ("requester_id", str(setup.peer)),
        ("actor_id", str(setup.peer)),
        ("category_id", str(uuid4())),
        ("tenant_id", str(setup.other_tenant)),
        ("event_type", "category.knowledge_added"),
    ):
        with pytest.raises(DomainError) as error:
            process_event(setup.engine, {**reference, key: value})
        assert error.value.code == "FORBIDDEN_SCOPE"
    with Session(setup.admin) as session, session.begin():
        assert (
            session.scalar(
                select(func.count())
                .select_from(SearchSource)
                .where(SearchSource.tenant_id == setup.tenant)
            )
            == 0
        )
        session.delete(
            session.scalar(
                select(Grant).where(
                    Grant.category_id == setup.category, Grant.principal_id == setup.human
                )
            )
        )
    with pytest.raises(DomainError) as error:
        process_event(setup.engine, reference)
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_personal_rebuild_derives_each_category_from_actual_readable_sources(setup):
    identity = register(setup, "本人全局重建", "漏气复验。")
    private = register(setup, "OWNER_ONLY_REBUILD", "漏气复验。", visibility="private")
    result = rebuild(setup.engine, replace(setup.ctx, category_id=None))
    assert result == {"processed": 2, "changed": 2, "failed": 0}
    assert {row["source_id"] for row in query(setup, "漏气", personal=True)["items"]} == {
        str(identity),
        str(private),
    }
    peer = replace(setup.ctx, actor_id=setup.peer, requester_id=setup.peer, category_id=None)
    assert rebuild(setup.engine, peer) == {"processed": 1, "changed": 1, "failed": 0}
    assert query(setup, "漏气", actor=setup.peer, personal=True)["returned"] == 1


def test_search_parameters_only_narrow_and_never_accept_policy_facts(setup):
    index(setup, register(setup, "范围过滤", "漏气复验。"))
    for extra in (
        {"tenant_id": str(setup.other_tenant)},
        {"requester_id": str(setup.peer)},
        {"visibility": "category"},
        {"include_private": True},
        {"limit": 51},
        {"after": "2026-10-28T00:00:00"},
    ):
        response = setup.client.post(
            "/v1/personal/enterprise-search",
            headers=setup.headers,
            json={"query": "漏气", **extra},
        )
        assert response.status_code == 422, response.text
    denied = setup.client.post(
        f"/v1/categories/{setup.category}/enterprise-search",
        headers=setup.headers,
        json={"query": "漏气", "category_id": str(uuid4())},
    )
    assert denied.status_code == 403
    assert query(setup, "漏气", product_id=str(setup.product))["returned"] == 0
    empty = setup.client.post(
        "/v1/personal/enterprise-search",
        headers=setup.headers,
        json={"query": "， ？"},
    )
    assert empty.status_code == 422 and empty.json()["code"] == "VALIDATION_FAILED"


def test_concurrent_source_batches_keep_corpus_df_consistent_without_cross_source_deadlock(setup):
    identities = [register(setup, f"并发 D{i}-01", "漏气复验，核对密封圈。") for i in (16, 17)]
    barrier = Barrier(2)

    def batch(order):
        barrier.wait(timeout=5)
        with session_for(setup) as session:
            return [
                project(session, setup.ctx, "artifact", identity, force=True) for identity in order
            ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        forward = executor.submit(batch, identities)
        reverse = executor.submit(batch, list(reversed(identities)))
        assert all(row["status"] == "ready" for row in forward.result(timeout=15))
        assert all(row["status"] == "ready" for row in reverse.result(timeout=15))
    with session_for(setup) as session:
        corpus = session.get(SearchCorpus, setup.tenant)
        assert corpus.chunk_count == 2
        assert session.scalar(select(func.count()).select_from(SearchChunk)) == 2
        assert (
            session.scalar(select(SearchTerm.document_count).where(SearchTerm.term == "漏气")) == 2
        )
    assert query(setup, "漏气")["returned"] == 2
