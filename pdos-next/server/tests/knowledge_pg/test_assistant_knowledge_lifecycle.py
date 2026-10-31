"""Root-run PG draft for F original retention and ordinary-caller RLS.

Collection never creates an engine. Native positive paths use only existing
synthetic provider/scanner fixtures. Negative lifecycle states are rolled back
in the same transaction; they are never committed as real lifecycle decisions.
"""
# ruff: noqa: F401,F811 -- explicitly register the native fixture dependency tree

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.database import tenant_session
from pdos_next.domain.knowledge.assistant_models import (
    KnowledgeAnswerReview,
    KnowledgeGapAttribution,
    KnowledgeGapSubmission,
)
from pdos_next.domain.knowledge.models import KnowledgeCandidateVersion
from pdos_next.domain.preproject.category_models import KnowledgeEntry
from pdos_next.enterprise_search.indexing import project as project_source
from pdos_next.models import Artifact, Category, LifecycleObject, Principal, Product
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.enterprise_search.test_assistant_pg import SyntheticClient, execute, fixture
from tests.enterprise_search.test_business_sources_pg import (
    NativeClient,
    accepted_work,
    apply_event,
    change_work,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)
from tests.enterprise_search.test_knowledge_dependencies_pg import KnowledgeClient
from tests.enterprise_search.test_retrieval_pg import index, query
from tests.knowledge_pg.test_assistant_knowledge import (
    answer,
    from_seed,
    root,
    seed,
    submit,
)
from tests.test_original_security import parsed, uploaded
from tests.test_original_security import security_work as security_work


def scoped(setup, *, admin=False, person=None, tenant=None):
    person = person or setup.human
    return tenant_session(
        setup.admin if admin else setup.engine,
        tenant or setup.tenant,
        actor_id=person,
        requester_id=person,
        category_id=setup.category,
    )


def saved_candidate(setup, run):
    value = from_seed(seed(setup, run, "rule"))
    path = f"/v1/categories/{setup.category}"
    if value["product_id"] is not None:
        path += f"/products/{value['product_id']}"
    response = setup.client.post(
        path + "/experience/inputs", headers=setup.headers, json=value
    )
    assert response.status_code == 200, response.text
    value.update(
        payload=response.json()["payload"],
        source_read_set=response.json()["required_source_read_set"],
    )
    response = submit(setup, value)
    assert response.status_code == 200, response.text
    return UUID(response.json()["subject_id"])


def shared_gap(setup, run):
    response = setup.client.post(
        f"/v1/categories/{setup.category}/agent-runs/{run}/feedback",
        headers=setup.headers,
        json={"idempotency_key": str(uuid4()), "categories": ["not_useful"]},
    )
    assert response.status_code == 200, response.text
    data = {
        "run_id": str(run),
        "kind": "shared_feedback",
        "feedback_id": response.json()["feedback"]["id"],
    }
    response = setup.client.post(
        root(setup) + "/gaps/preview", headers=setup.headers, json=data
    )
    assert response.status_code == 200, response.text
    response = setup.client.post(
        root(setup) + "/gaps",
        headers=setup.headers,
        json={
            **data,
            "preview_digest": response.json()["preview_digest"],
            "request_key": str(uuid4()),
        },
    )
    assert response.status_code == 200, response.text
    return UUID(response.json()["id"])


def roots_for(session, setup, model, identity):
    return set(
        session.scalar(
            text(
                f"SELECT m3_lifecycle_roots(:t,:c,:table,to_jsonb(row)) "
                f"FROM public.{model.__tablename__} row WHERE row.id=:id"
            ),
            {
                "t": setup.tenant,
                "c": setup.category,
                "table": model.__tablename__,
                "id": identity,
            },
        )
    )


def epochs(session, setup):
    return (
        session.scalar(
            select(Category.lifecycle_epoch).where(Category.id == setup.category)
        ),
        session.scalar(
            select(Product.lifecycle_epoch).where(Product.id == setup.product)
        ),
    )


@pytest.fixture
def retained_answer(security_work):
    work, setup = security_work, security_work.setup
    original = uploaded(
        work,
        visibility="category",
        content="漏气处理：更换密封圈。RAW_ONLY_CHILD_MARKER\n".encode(),
    )
    source = parsed(work, original)
    index(setup, source)
    client = SyntheticClient()
    owner, scope, host, _ = fixture(
        setup,
        client,
        product_id=setup.product,
        read_sources=({"artifact_id": str(source), "expected_revision": 1},),
    )
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    candidate = saved_candidate(setup, scope.run_id)
    gap = shared_gap(setup, scope.run_id)
    with scoped(setup, admin=True) as session:
        review = session.scalar(
            select(KnowledgeAnswerReview).where(
                KnowledgeAnswerReview.subject_id == candidate
            )
        )
        assert review is not None
        review_id = review.id
    return SimpleNamespace(
        setup=setup,
        original=original,
        source=source,
        run=scope.run_id,
        candidate=candidate,
        review=review_id,
        gap=gap,
        client=client,
        scanner=work.scanner,
        scan_calls=work.scanner.calls,
    )


def test_native_uploaded_original_is_retained_by_both_f_facts_and_not_attribution(
    retained_answer,
):
    work, setup = retained_answer, retained_answer.setup
    with scoped(setup, admin=True) as session:
        review = session.get(KnowledgeAnswerReview, work.review)
        gap = session.get(KnowledgeGapSubmission, work.gap)
        for fact in (review, gap):
            assert fact.source_proof
            assert all(
                set(ref)
                == {
                    "source_type",
                    "source_id",
                    "source_revision",
                    "content_hash",
                    "category_id",
                }
                for ref in fact.source_proof
            )
            assert {ref["source_id"] for ref in fact.source_proof} == {str(work.source)}
            assert work.original in roots_for(session, setup, type(fact), fact.id)
        assert work.original in roots_for(
            session, setup, KnowledgeCandidateVersion, work.candidate
        )
        assert session.get(Artifact, work.source).original_id == work.original
        nodes = session.execute(
            text(
                "SELECT table_name,node_id FROM m3_lifecycle_nodes(:t,:c,CAST(:ids AS uuid[]))"
            ),
            {"t": setup.tenant, "c": setup.category, "ids": [work.review, work.gap]},
        ).all()
        assert set(nodes) == {
            (KnowledgeAnswerReview.__tablename__, work.review),
            (KnowledgeGapSubmission.__tablename__, work.gap),
        }
        before = epochs(session, setup)
    response = setup.client.post(
        root(setup) + "/gaps/attributions",
        headers=setup.headers,
        json={
            "request_key": str(uuid4()),
            "submission_id": str(work.gap),
            "reason": "unclear_content",
        },
    )
    assert response.status_code == 200, response.text
    with scoped(setup, admin=True) as session:
        assert (
            session.get(KnowledgeGapAttribution, UUID(response.json()["id"]))
            is not None
        )
        assert epochs(session, setup) == before
    assert work.client.calls == 5 and work.scanner.calls == work.scan_calls


class ProbeRollback(Exception):
    """An intentional rollback, including synthetic LifecycleObject inserts."""


@pytest.mark.parametrize("state", ["pending", "quarantined"])
def test_actual_app_append_fences_both_f_tables_before_deferred_atoms(
    retained_answer, state
):
    work, setup = retained_answer, retained_answer.setup
    with pytest.raises(ProbeRollback):
        with scoped(setup, admin=True) as session:
            rows = []
            for model, identity in (
                (KnowledgeAnswerReview, work.review),
                (KnowledgeGapSubmission, work.gap),
            ):
                value = dict(
                    session.execute(select(model.__table__).where(model.id == identity))
                    .mappings()
                    .one()
                )
                value["id"] = uuid4()
                if model is KnowledgeGapSubmission:
                    value["request_key"] = uuid4()
                rows.append((model, value))
            # Match the existing M3 rollback probe: never commit an invented intent.
            session.add(
                LifecycleObject(
                    id=work.original,
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    product_id=setup.product,
                    owner_id=setup.human,
                    reference={},
                    state={
                        "value": {
                            "pending_intent_id": str(uuid4())
                            if state == "pending"
                            else None,
                            "disposition": "active"
                            if state == "pending"
                            else "quarantined",
                        }
                    },
                )
            )
            session.flush()
            session.execute(text("SET LOCAL ROLE pdos_next_app"))
            session.execute(text("SET LOCAL statement_timeout='8s'"))
            before = epochs(session, setup)
            for model, value in rows:
                count = session.scalar(select(func.count()).select_from(model))
                with pytest.raises(DBAPIError) as failure:
                    with session.begin_nested():
                        session.execute(
                            insert(model.__table__).values(**deepcopy(value))
                        )
                assert failure.value.orig.sqlstate == "23514"
                assert (
                    failure.value.orig.diag.constraint_name
                    == "m3_source_reference_fence"
                )
                assert session.scalar(select(func.count()).select_from(model)) == count
                assert epochs(session, setup) == before
            raise ProbeRollback
    with Session(setup.admin) as session:
        assert session.get(LifecycleObject, work.original) is None
    assert work.client.calls == 5 and work.scanner.calls == work.scan_calls


def test_reused_review_proofs_allow_current_peer_reads_without_private_run_or_rls_recursion(
    setup,
):
    source, first_run, client = answer(setup)
    response = submit(setup, from_seed(seed(setup, first_run)))
    assert response.status_code == 200, response.text
    first = UUID(response.json()["result"]["entry_id"])
    with scoped(setup) as session:
        project_source(session, setup.ctx, "knowledge", first)
    reader = KnowledgeClient()
    owner, scope, host, _ = fixture(
        setup,
        reader,
        read_sources=({"artifact_id": str(source), "expected_revision": 1},),
    )
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    assert {
        item["source_type"] for item in output["result"]["assistant"]["sources"]
    } == {
        "knowledge",
    }
    response = submit(setup, from_seed(seed(setup, scope.run_id)))
    assert response.status_code == 200, response.text
    second = UUID(response.json()["result"]["entry_id"])
    with scoped(setup) as session:
        project_source(session, setup.ctx, "knowledge", second)
        proof = session.scalar(
            select(KnowledgeAnswerReview.source_proof).where(
                KnowledgeAnswerReview.subject_id == second
            )
        )
        assert [(ref["source_type"], ref["source_id"]) for ref in proof] == [
            ("artifact", str(source)),
        ]

    def visible(person, *, tenant=None):
        with scoped(setup, person=person, tenant=tenant) as session:
            session.execute(text("SET LOCAL statement_timeout='8s'"))
            # The shared subject/review must not make its owner's private Run visible.
            if person != setup.human:
                assert session.get(AgentRun, scope.run_id) is None
            subjects = set(
                session.scalars(
                    select(KnowledgeEntry.id).where(
                        KnowledgeEntry.id.in_([first, second])
                    )
                )
            )
            reviews = set(
                session.scalars(
                    select(KnowledgeAnswerReview.subject_id).where(
                        KnowledgeAnswerReview.subject_id.in_([first, second])
                    )
                )
            )
            assert subjects == reviews
            return subjects

    assert visible(setup.peer) == {first, second}
    assert visible(setup.other_human, tenant=setup.other_tenant) == set()
    assert (
        query(
            setup,
            "更换密封圈",
            actor=setup.peer,
            personal=True,
            source_types=["knowledge"],
        )["returned"]
        == 2
    )
    with scoped(setup, admin=True) as session:
        session.get(Principal, setup.peer).active = False
    assert visible(setup.peer) == set()
    assert visible(setup.human) == {first, second}
    with scoped(setup, admin=True) as session:
        session.get(Principal, setup.peer).active = True
    assert visible(setup.peer) == {first, second}
    # Existing isolated synthetic withdrawal/authorization fault injection.
    # No fixed content, version or proof is rewritten, and no index rebuild occurs.
    with scoped(setup, admin=True) as session:
        session.get(Artifact, source).status = "withdrawn"
    assert visible(setup.peer) == set()
    assert visible(setup.human) == set()
    assert (
        query(
            setup,
            "更换密封圈",
            actor=setup.peer,
            personal=True,
            source_types=["knowledge"],
        )["returned"]
        == 0
    )
    # Withdrawal is terminal; the preserved version is never reactivated.
    assert client.calls == 5 and reader.calls == 3 and reader.child_calls == 0


def test_native_issue_and_capa_answer_proofs_resolve_real_uploaded_roots(change_work):
    work, setup = change_work, change_work.quality
    assert apply_event(setup, work.issue_receipt["id"])["processed"] == 2
    project_id = UUID(work.config["project"])
    for kind, identity in (("issue", work.issue_id), ("capa", work.capa_id)):
        client = NativeClient(str(identity), [kind], expected_scope=str(project_id))
        owner, scope, host, _ = fixture(setup, client, project_id=project_id)
        output = execute(owner, scope, host)
        assert output["status"] == "completed", output
        candidate = saved_candidate(setup, scope.run_id)
        with scoped(setup, admin=True) as session:
            review = session.scalar(
                select(KnowledgeAnswerReview).where(
                    KnowledgeAnswerReview.subject_id == candidate
                )
            )
            assert review is not None and len(review.source_proof) == 1
            proof = review.source_proof[0]
            assert proof["source_type"] == kind
            # The actual five-field source ID is the fixed IssueVersion row,
            # not the logical Issue/CAPA identity shown in its page link.
            from pdos_next.domain.quality_execution.models import QualityIssueVersion

            fixed = session.get(QualityIssueVersion, UUID(proof["source_id"]))
            assert fixed is not None and proof["source_revision"] == fixed.revision
            originals = set(
                session.scalars(
                    select(Artifact.original_id).where(
                        Artifact.id.in_(
                            [
                                UUID(ref["artifact_id"])
                                for ref in fixed.required_source_read_set
                            ]
                        ),
                        Artifact.original_id.is_not(None),
                    )
                )
            )
            assert originals, (
                "The native failure fixture must retain its uploaded report"
            )
            assert originals <= roots_for(
                session, setup, KnowledgeAnswerReview, review.id
            )
            assert originals <= roots_for(
                session, setup, KnowledgeCandidateVersion, candidate
            )
        assert client.calls == 3
