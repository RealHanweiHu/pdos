"""Native D -> isolated answer -> F save -> ordinary owner/peer reads.

Root runs the single case with its verified isolated PG configuration after the
unnumbered visibility function delta. Import/collection creates no engine.
"""
# ruff: noqa: F401,F811 -- register the actual native fixture dependency tree

from uuid import UUID

from pdos_next.database import tenant_session
from pdos_next.domain.field_feedback.schemas import CREATE
from pdos_next.domain.knowledge.assistant_models import KnowledgeAnswerReview
from pdos_next.domain.preproject.category_models import KnowledgeEntry
from pdos_next.enterprise_search.embedding_sources import categories
from pdos_next.enterprise_search.indexing import project as project_source
from pdos_next.models import Artifact
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.enterprise_search.test_field_feedback_sources_pg import (
    answer,
    apply_event,
    configuration,
    definition,
    knowledge_work,
    project,
    records,
)
from tests.enterprise_search.test_retrieval_pg import query
from tests.field_feedback_pg.test_field_chain import prepare
from tests.knowledge_pg.test_assistant_knowledge import from_seed, root, seed, submit
from tests.knowledge_pg.test_publication import command, register, send


def test_native_field_answer_saved_as_knowledge_is_visible_to_ordinary_owner_and_peer(
    knowledge_work,
):
    work, person = knowledge_work, knowledge_work.setup
    original = register(
        work,
        "合成内部现场记录",
        "内部现场观察：漏气处理可讨论更换密封圈。",
        category_only=True,
        visibility="category",
    )
    prepared, _inputs = prepare(work, command(work, CREATE, {
        "visibility": "category",
        "title": "合成内部现场漏气反馈",
        "description": "内部现场观察：漏气处理可讨论更换密封圈。RAW_ONLY_CHILD_MARKER",
        "channel": "field",
        "feedback_kind": "observation",
        "received_at": work.at.isoformat(),
        "reported": {"product_label": None, "batch_label": None,
                     "configuration_label": None},
        "purpose": "固定未定位的内部现场观察，供本人审阅后整理讨论知识",
        "sources": [original],
        "reason": "保留原始报告与未知定位，不声明质量关闭或产品适用",
    }, category_only=True))
    response = send(work, prepared)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert apply_event(person, receipt["id"])["processed"] == 1
    row = next(item for item in records(person)
               if str(item["source_id"]) == receipt["subject_id"])
    assert row["nature"] == "untrusted" and row["is_current"]
    assert not row["private"] and not row["customer_original"]
    assert categories(row) == {"internal"}

    cited, provider, _owner, scope, _adapter = answer(person, row)
    assert cited["source_type"] == "field_feedback"
    assert provider.child.child_calls >= 2  # Raw report used the actual isolated graph.
    assert all("RAW_ONLY_CHILD_MARKER" not in str(messages)
               for messages in provider.main_messages)
    with Session(person.admin) as session:
        artifact_count = session.scalar(select(func.count()).select_from(Artifact).where(
            Artifact.tenant_id == person.tenant,
        ))
    saved = submit(person, from_seed(seed(person, scope.run_id)))
    assert saved.status_code == 200, saved.text
    entry_id = UUID(saved.json()["result"]["entry_id"])
    expected = [{
        "source_type": "field_feedback",
        "source_id": str(row["source_id"]),
        "source_revision": row["source_revision"],
        "content_hash": row["content_hash"],
        "category_id": str(person.category),
    }]
    with tenant_session(person.engine, person.tenant, actor_id=person.human,
                        requester_id=person.human, category_id=person.category) as session:
        entry = session.get(KnowledgeEntry, entry_id)
        assert entry is not None
        review = session.scalar(select(KnowledgeAnswerReview).where(
            KnowledgeAnswerReview.subject_id == entry_id,
        ))
        assert review is not None and review.origin_run_id == scope.run_id
        assert review.verified_by == person.human
        assert review.source_proof == entry.answer_sources == expected
        assert entry.source_refs == []  # The native Field proof was not made into an Artifact.
        assert project_source(session, person.ctx, "knowledge", entry_id)["status"] == "ready"
    with Session(person.admin) as session:
        assert session.scalar(select(func.count()).select_from(Artifact).where(
            Artifact.tenant_id == person.tenant,
        )) == artifact_count

    before_calls = provider.calls, provider.child.child_calls
    for principal in (person.human, person.peer):
        with tenant_session(person.engine, person.tenant, actor_id=principal,
                            requester_id=principal, category_id=person.category,
                            read_snapshot=True) as session:
            assert session.get(KnowledgeEntry, entry_id) is not None
        visible = person.client.get(
            root(person) + "/verified-answers",
            headers={"Authorization": "Bearer " + person.tokens[principal]},
        )
        assert visible.status_code == 200, visible.text
        actual = next(item for item in visible.json()["items"] if item["id"] == str(entry_id))
        assert actual["review"]["state"] == "verified" and actual["basis_count"] == 1
        found = query(person, str(entry_id), actor=principal, source_types=["knowledge"])
        assert any(item["source_id"] == str(entry_id) for item in found["items"]), found
    assert (provider.calls, provider.child.child_calls) == before_calls
