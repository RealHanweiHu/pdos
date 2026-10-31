"""Actual PG draft: root runs after the unnumbered F schema and hook merge.

Only the existing offline SyntheticClient is used. No database access occurs on
import/collection, and TEST_DATABASE_URL remains mandatory in shared conftest.
"""
# ruff: noqa: F401,F811 -- reuse the actual native fixture dependency tree

from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from pdos_next.database import tenant_session
from pdos_next.domain.knowledge.assistant_models import (
    KnowledgeAnswerReview,
    KnowledgeGapSubmission,
)
from pdos_next.enterprise_search.indexing import project as project_source
from pdos_next.models import Artifact, Receipt, now
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_builds import accepted, build_command, configuration, definition, project
from tests.enterprise_search.test_assistant_pg import SyntheticClient, execute, fixture
from tests.enterprise_search.test_retrieval_pg import index, query, register
from tests.knowledge_pg.test_publication import (
    authorize,
    command,
    knowledge_work,
    prepare,
    rule_payload,
    send,
)


def root(setup):
    return f"/v1/categories/{setup.category}/experience"


def answer(setup, *, visibility="category"):
    identity = register(
        setup, "F 合成漏气处理", "措施：更换密封圈。RAW_ONLY_CHILD_MARKER", visibility
    )
    # Native publication fixtures register configuration evidence as well. Keep
    # their real index projection current before asserting complete coverage.
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        identities = session.scalars(select(Artifact.id)).all()
    for source_id in identities:
        index(setup, source_id)
    client = SyntheticClient()
    owner, scope, host, _ = fixture(
        setup, client, read_sources=({"artifact_id": str(identity), "expected_revision": 1},)
    )
    output = execute(owner, scope, host)
    assert output["status"] == "completed" and output["result"]["assistant"]["lookup"] == "cited", (
        output
    )
    return identity, scope.run_id, client


def seed(setup, run, kind="category"):
    response = setup.client.post(
        root(setup) + "/answer-draft",
        headers=setup.headers,
        json={"run_id": str(run), "kind": kind},
    )
    assert response.status_code == 200, response.text
    value = response.json()
    value["payload"]["knowledge_review"] = {
        "responsible_id": str(setup.human),
        "applicability_scope": "合成密封案例的讨论参考",
        "review_due_at": (now() + timedelta(days=7)).isoformat(),
    }
    return value


def from_seed(value):
    return {
        **value["command_scope"],
        "operation": value["operation"],
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "source_read_set": [],
        "payload": deepcopy(value["payload"]),
    }


def submit(setup, value):
    return setup.client.post(
        f"/v1/categories/{setup.category}/commands", headers=setup.headers, json=value
    )


def test_answer_native_category_receipt_replay_reopen_and_manual_review_revision(setup):
    identity, run, client = answer(setup)
    original = from_seed(seed(setup, run))
    saved = submit(setup, original)
    assert saved.status_code == 200, saved.text
    receipt = saved.json()
    assert submit(setup, original).json()["id"] == receipt["id"]
    read = setup.client.get(root(setup) + "/verified-answers", headers=setup.headers)
    assert read.status_code == 200, read.text
    entry = next(
        item for item in read.json()["items"] if item["id"] == receipt["result"]["entry_id"]
    )
    assert entry["review"]["state"] == "verified" and entry["basis_count"] == 1
    assert entry["content"]["draft_origin"] == "ai_draft"
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        annotation = session.scalar(
            select(KnowledgeAnswerReview).where(
                KnowledgeAnswerReview.subject_id == UUID(entry["id"])
            )
        )
        actual = session.get(Receipt, UUID(receipt["id"]))
        assert annotation.receipt_id == actual.id and annotation.command_id == actual.command_id
        assert annotation.source_proof[0]["source_id"] == str(identity)
        assert annotation.verified_by == setup.human
        assert session.scalar(
            text("SELECT xmin FROM public.knowledge_answer_reviews WHERE id=:id"),
            {"id": annotation.id},
        ) == session.scalar(
            text("SELECT xmin FROM public.action_receipts WHERE id=:id"), {"id": actual.id}
        )
        project_source(session, setup.ctx, "knowledge", UUID(entry["id"]))
    results = query(setup, "更换密封圈", source_types=["knowledge", "artifact"])
    assert results["items"][0]["source_id"] == entry["id"]
    assert results["items"][0]["knowledge_review"]["state"] == "verified"
    renew = setup.client.post(
        root(setup) + "/review-draft", headers=setup.headers, json={"entry_id": entry["id"]}
    )
    assert renew.status_code == 200, renew.text
    updated = from_seed(renew.json())
    updated["payload"]["knowledge_review"]["review_due_at"] = (
        now() + timedelta(days=14)
    ).isoformat()
    result = submit(setup, updated)
    assert result.status_code == 200, result.text
    assert result.json()["result"]["lineage_id"] == receipt["result"]["lineage_id"]
    assert result.json()["result"]["version"] == 2 and client.calls == 5


def test_private_answer_cannot_enter_shared_category_without_native_deidentification(setup):
    _identity, run, _client = answer(setup, visibility="private")
    response = setup.client.post(
        root(setup) + "/answer-draft",
        headers=setup.headers,
        json={"run_id": str(run), "kind": "category"},
    )
    assert response.status_code == 403, response.text
    value = seed(setup, run, "rule")
    assert value["payload"]["visibility"] == "private"
    # A browser cannot flip this source-derived audience to a shared candidate.
    forged = from_seed(value)
    forged["payload"]["visibility"] = "category"
    forged["source_read_set"] = [
        {"artifact_id": item["id"], "expected_revision": item["revision"]}
        for item in forged["payload"]["sources"]
    ]
    response = setup.client.post(root(setup) + "/inputs", headers=setup.headers, json=forged)
    assert response.status_code == 403, response.text


def test_answer_candidate_uses_real_native_named_publication_and_becomes_retrievable(
    knowledge_work,
):
    work, setup = knowledge_work, knowledge_work.setup
    _identity, run, client = answer(setup)
    value = from_seed(seed(setup, run, "rule"))
    value["source_read_set"] = [
        {"artifact_id": item["id"], "expected_revision": item["revision"]}
        for item in value["payload"]["sources"]
    ]
    prepared = prepare(work, value)
    saved = send(work, prepared)
    assert saved.status_code == 200, saved.text
    candidate = {"id": saved.json()["result"]["candidate_id"], "revision": 1}
    unauthorized = prepare(
        work,
        command(work, "knowledge.rule.publish", rule_payload(work, candidate)),
        expected=403,
    )
    assert unauthorized.status_code == 403, unauthorized.text
    authorize(work)
    native = prepare(work, command(work, "knowledge.rule.publish", rule_payload(work, candidate)))
    preview = send(work, native, preview=True)
    assert preview.status_code == 200, preview.text
    assert preview.json()["write_tier"] == "T2" and preview.json()["named_decision"] is True
    published = send(work, preview.json()["command"])
    assert published.status_code == 200, published.text
    identity = UUID(published.json()["subject_id"])
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        project_source(session, setup.ctx, "knowledge", identity)
    results = query(
        setup,
        "configured purpose",
        source_types=["knowledge"],
        product_id=str(setup.product),
        project_id=str(work.project_id),
    )
    assert str(identity) in {item["source_id"] for item in results["items"]}
    assert client.calls == 5


def test_gap_is_explicit_atomic_replayed_and_weekly_omits_questioner_and_private_comment(setup):
    _identity, run, client = answer(setup)
    feedback = setup.client.post(
        f"/v1/categories/{setup.category}/agent-runs/{run}/feedback",
        headers=setup.headers,
        json={
            "idempotency_key": str(uuid4()),
            "categories": ["not_useful"],
            "comment": "PRIVATE_COMMENT_MUST_NOT_SHARE",
        },
    )
    assert feedback.status_code == 200, feedback.text
    feedback_id = feedback.json()["feedback"]["id"]
    preview = setup.client.post(
        root(setup) + "/gaps/preview",
        headers=setup.headers,
        json={"run_id": str(run), "kind": "shared_feedback", "feedback_id": feedback_id},
    )
    assert preview.status_code == 200, preview.text
    assert "PRIVATE_COMMENT_MUST_NOT_SHARE" not in preview.text
    value = {
        "run_id": str(run),
        "kind": "shared_feedback",
        "feedback_id": feedback_id,
        "preview_digest": preview.json()["preview_digest"],
        "request_key": str(uuid4()),
    }
    response = setup.client.post(root(setup) + "/gaps", headers=setup.headers, json=value)
    assert response.status_code == 200, response.text
    assert (
        setup.client.post(root(setup) + "/gaps", headers=setup.headers, json=value).json()["id"]
        == response.json()["id"]
    )
    from pdos_next.domain.knowledge.assistant_gaps import week_bounds

    at = now()
    week = (at - timedelta(days=at.weekday())).date().isoformat()
    week_bounds(week)
    weekly = setup.client.get(
        root(setup) + "/gaps/weekly", headers=setup.headers, params={"week": week}
    )
    assert weekly.status_code == 200, weekly.text
    assert weekly.json()["lookup_rate"] == {
        "total": None,
        "not_found": None,
        "rate": None,
        "suppressed": True,
    }
    item = weekly.json()["items"][0]
    assert "PRIVATE_COMMENT_MUST_NOT_SHARE" not in weekly.text
    assert not {"owner_id", "requester_id", "recorded_by", "comment"}.intersection(item)
    peer = setup.client.get(
        root(setup) + "/gaps/weekly",
        headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"},
        params={"week": week},
    )
    assert peer.status_code == 403
    assert client.calls == 5


@pytest.mark.parametrize(
    "table", ["knowledge_answer_reviews", "knowledge_gap_submissions", "knowledge_gap_attributions"]
)
def test_agent_has_no_direct_fact_select_or_append(setup, table):
    with Session(setup.admin) as session:
        with pytest.raises(DBAPIError) as failure:
            with session.begin():
                session.execute(text("SET LOCAL ROLE pdos_agent"))
                session.execute(text(f"SELECT * FROM public.{table}"))
        assert failure.value.orig.sqlstate == "42501"
    # Table grants cover every write verb, even a syntactically valid INSERT.
    with Session(setup.admin) as session:
        assert not session.scalar(
            text("SELECT has_table_privilege('pdos_agent',:name,'INSERT')"),
            {"name": f"public.{table}"},
        )


def test_withdrawn_actual_dependency_hides_new_knowledge_in_every_original_read_path(setup):
    identity, run, _client = answer(setup)
    value = from_seed(seed(setup, run))
    saved = submit(setup, value)
    assert saved.status_code == 200, saved.text
    entry = UUID(saved.json()["result"]["entry_id"])
    # Existing authorized synthetic fault injection; immutable bytes/hash stay untouched.
    with Session(setup.admin) as session, session.begin():
        session.get(Artifact, identity).status = "withdrawn"
    current = setup.client.get(root(setup) + "/verified-answers", headers=setup.headers)
    assert current.status_code == 200 and current.json()["items"] == [], current.text
    generic = setup.client.get(
        f"/v1/categories/{setup.category}/knowledge",
        headers=setup.headers,
        params={"kind": "verified_answer"},
    )
    assert generic.status_code == 200 and str(entry) not in generic.text, generic.text
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        assert (
            session.scalar(
                text("SELECT id FROM public.category_knowledge_entries WHERE id=:id"), {"id": entry}
            )
            is None
        )
        assert (
            session.scalar(
                select(KnowledgeAnswerReview).where(KnowledgeAnswerReview.subject_id == entry)
            )
            is None
        )
    retry = setup.client.post(
        root(setup) + "/review-draft", headers=setup.headers, json={"entry_id": str(entry)}
    )
    assert retry.status_code == 403
