"""Pure evidence/metadata/weekly-contract tests; no database or model port."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from pdos_next.domain.knowledge import assistant_reviews as reviews
from pdos_next.domain.knowledge import assistant_sources as sources
from pdos_next.domain.knowledge.assistant_gaps import week_bounds
from pdos_next.domain.knowledge.assistant_schemas import AnswerOrigin, GapInput, KnowledgeReview
from pdos_next.domain.knowledge.assistant_storage import downgrade_sql, upgrade_sql
from pdos_next.domain.knowledge.schemas import CandidatePayload
from pdos_next.domain.preproject.category_schemas import KnowledgeAdd, KnowledgePromote
from pdos_next.enterprise_search.sources import catalog, retrieval_catalog
from pdos_next.errors import DomainError
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import dialect


@pytest.fixture
def source(monkeypatch):
    tenant, category, person, identity, cid = (uuid4() for _ in range(5))
    ctx = NS(
        tenant_id=tenant,
        category_id=category,
        requester_id=person,
        actor_id=person,
        run_id=None,
        agent_run_id=None,
    )
    ref = dict(
        source_type="artifact",
        source_id=str(identity),
        source_revision=1,
        content_hash="a" * 64,
        category_id=str(category),
    )
    actual = {**ref, "private": False, "customer_original": False, "fixed_body_available": True}
    run = NS(
        id=uuid4(),
        tenant_id=tenant,
        category_id=category,
        requester_id=person,
        state="completed",
        reverted_at=None,
        product_id=None,
        project_id=None,
        private_context=False,
        goal="合成原问题",
        result={
            "summary": "合成回答",
            "result": {
                "assistant": {
                    "citation_ids": [str(cid)],
                    "sources": [
                        {"citation_id": str(cid), "quote": "完整行", "locator": {"line_start": 1}}
                    ],
                }
            },
        },
    )
    session = NS(get=lambda _model, _id: run)
    monkeypatch.setattr(sources, "human", lambda *_: None)
    monkeypatch.setattr(sources, "require_access", lambda *_args, **_kw: None)
    monkeypatch.setattr(sources, "scope_for_run", lambda run: run)
    monkeypatch.setattr(sources, "checked_sources", lambda *_: {str(cid): actual})
    monkeypatch.setattr(sources.ledger, "carried", lambda *_: ({str(cid): ref}, {}))
    from pdos_next.domain.quality_execution import evidence

    monkeypatch.setattr(
        evidence, "source_for", lambda *_: NS(id=identity, revision=1, content="完整行原文\n下一行")
    )
    return ctx, session, run, ref, actual


def test_actual_answer_captures_exact_native_line_hash_without_fabricating_artifact(source):
    ctx, session, run, ref, _ = source
    value = sources.capture(session, ctx, run.id)
    assert value["question"] == "合成原问题" and value["answer"] == "合成回答"
    assert value["source_proof"] == [ref]
    assert value["artifacts"] == [
        {
            "kind": "artifact",
            "id": ref["source_id"],
            "revision": 1,
            "position": "line:1;quote_sha256:" + sha256("完整行原文".encode()).hexdigest(),
        }
    ]
    assert (
        sources.capture(session, ctx, run.id, expected_digest=value["answer_digest"])[
            "answer_digest"
        ]
        == value["answer_digest"]
    )
    with pytest.raises(DomainError):
        sources.capture(session, ctx, run.id, expected_digest="b" * 64)


@pytest.mark.parametrize(
    "mutation", ["hash", "version", "unavailable", "other_category", "other_owner", "reverted"]
)
def test_answer_save_rejects_changed_or_unreadable_fixed_origin(source, mutation):
    ctx, session, run, _ref, actual = source
    if mutation == "hash":
        actual["content_hash"] = "b" * 64
    elif mutation == "version":
        actual["source_revision"] = 2
    elif mutation == "unavailable":
        actual["fixed_body_available"] = False
    elif mutation == "other_category":
        actual["category_id"] = str(uuid4())
    elif mutation == "other_owner":
        run.requester_id = uuid4()
    else:
        run.reverted_at = datetime.now(UTC)
    with pytest.raises(DomainError):
        sources.capture(session, ctx, run.id)


def test_structured_discussion_source_never_turns_into_fake_artifact(source):
    ctx, session, run, ref, _ = source
    ref["source_type"] = "issue"
    value = sources.capture(session, ctx, run.id)
    assert value["source_proof"][0]["source_type"] == "issue"
    assert value["artifacts"] == []


def test_review_state_is_half_open_and_overdue_stays_searchable():
    at = datetime(2026, 10, 29, tzinfo=UTC)
    row = NS(
        review_due_at=at,
        verified_by=uuid4(),
        responsible_id=uuid4(),
        applicability_scope="只限合成用途",
    )
    assert reviews.status(row, at - timedelta(microseconds=1))["priority"] == 1
    assert reviews.status(row, at)["state"] == "needs_review"
    assert reviews.status(row, at)["priority"] == -1
    row.verified_by = None
    assert reviews.status(row, at - timedelta(days=1))["state"] == "draft"


def test_shared_review_reuses_native_promotion_and_does_not_copy_private_source_ids(
    monkeypatch, source
):
    ctx, session, _run, ref, _ = source
    metadata = KnowledgeReview(
        responsible_id=ctx.requester_id,
        applicability_scope="仅此用途",
        review_due_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    prior = NS(
        source_proof=[ref],
        responsible_id=ctx.requester_id,
        applicability_scope="旧用途",
        review_due_at=metadata.review_due_at,
        origin_run_id=uuid4(),
        answer_digest="a" * 64,
    )
    monkeypatch.setattr(reviews, "validate_review", lambda *_args, **_kw: None)
    monkeypatch.setattr(
        reviews, "recheck", lambda *_: {"0": {"private": True, "customer_original": True}}
    )
    payload = NS(knowledge_review=metadata, answer_origin=None, kind="verified_answer")
    with pytest.raises(DomainError, match="去标识"):
        reviews.prepare(session, ctx, payload, shared=True, previous=prior)
    promoted = reviews.prepare(session, ctx, payload, shared=True, previous=prior, promoted=True)
    assert promoted["source_proof"] == [] and promoted["private"] is True


def test_review_is_explicit_human_and_inherited_expiry_is_not_an_extra_publish_gate(
    monkeypatch, source
):
    ctx, session, _run, ref, _ = source
    checks = []
    monkeypatch.setattr(reviews, "validate_review", lambda *_args, **kw: checks.append(kw))
    monkeypatch.setattr(
        reviews, "recheck", lambda *_: {"0": {"private": False, "customer_original": False}}
    )
    prior = NS(
        source_proof=[ref],
        responsible_id=ctx.requester_id,
        applicability_scope="旧用途",
        review_due_at=datetime(2020, 1, 1, tzinfo=UTC),
        origin_run_id=None,
        answer_digest=None,
    )
    payload = NS(knowledge_review=None, answer_origin=None)
    assert reviews.prepare(session, ctx, payload, previous=prior)["review_due_at"].startswith(
        "2020"
    )
    assert checks == [{"new_date": False}]
    ctx.actor_id = uuid4()
    with pytest.raises(DomainError):
        reviews.prepare(session, ctx, payload, previous=prior)


def test_knowledge_inheritance_flattens_fixed_children_but_preserves_native_deidentified_root(
    monkeypatch, source
):
    _ctx, session, _run, ref, _ = source
    knowledge = {**ref, "source_type": "knowledge", "source_id": str(uuid4())}
    monkeypatch.setattr(sources, "review_for", lambda *_: NS(source_proof=[ref]))
    assert sources.inherited_proof(session, [knowledge]) == [ref]
    monkeypatch.setattr(sources, "review_for", lambda *_: NS(source_proof=[]))
    assert sources.inherited_proof(session, [knowledge]) == [knowledge]
    monkeypatch.setattr(sources, "review_for", lambda *_: NS(source_proof=[knowledge]))
    with pytest.raises(DomainError, match="循环"):
        sources.inherited_proof(session, [knowledge])


def test_optional_fields_preserve_legacy_digests_and_do_not_add_authority():
    original = {
        "title": "合成经验",
        "lesson": "实际教训",
        "evidence_summary": "原文依据",
        "applicability_hypothesis": "待核对",
        "sources": [
            {
                "id": str(uuid4()),
                "revision": 1,
                "kind": "artifact",
                "position": "line:1;quote_sha256:" + "a" * 64,
            }
        ],
        "reason": "记录",
    }
    legacy = CandidatePayload.model_validate(original).model_dump(mode="json")
    assert "knowledge_review" not in legacy and "answer_origin" not in legacy
    for key in ("verified_by", "priority", "audience", "rank_version"):
        with pytest.raises(ValidationError):
            CandidatePayload.model_validate({**original, key: "injected"})
    with pytest.raises(ValidationError):
        CandidatePayload.model_validate({**original, "sources": []})
    with pytest.raises(ValidationError):
        AnswerOrigin(run_id=uuid4(), answer_digest="fake")


def test_category_review_does_not_fake_model_prepared_candidate():
    metadata = {
        "responsible_id": str(uuid4()),
        "applicability_scope": "合成用途",
        "review_due_at": "2027-01-01T00:00:00Z",
    }
    payload = KnowledgeAdd(
        kind="verified_answer",
        content={"title": "合成答案", "question": "原问题", "answer": "已核回答"},
        knowledge_review=metadata,
    )
    assert payload.prepared_by_run_id is None and payload.candidate_digest is None
    raw = payload.model_dump(mode="json")
    assert raw["content"]["draft_origin"] == "ai_draft"
    assert "answer_origin" not in raw
    with pytest.raises(ValidationError):
        KnowledgeAdd.model_validate({**raw, "knowledge_review": None})
    legacy = KnowledgePromote(
        source_proposal_id=uuid4(),
        source_proposal_revision=1,
        kind="research_question",
        content={"question": "原问题"},
        deidentified_confirmed=True,
    )
    assert "supersedes" not in legacy.model_dump(mode="json")


@pytest.mark.parametrize(
    "kinds", [["knowledge"], ["knowledge", "artifact"], ["knowledge", "issue", "build"]]
)
def test_native_rules_and_fixed_proof_authority_compile_before_paging(kinds):
    statement = select(retrieval_catalog(kinds)).limit(11)
    sql = str(statement.compile(dialect=dialect()))
    assert "knowledge_rule_versions" in sql and "knowledge_answer_reviews" in sql
    assert "verified_answer_authority" in sql and "published_rule_authority" in sql
    assert sql.index("verified_answer_authority") < sql.rindex("LIMIT")
    assert "content_hash" in sql and "source_revision" in sql
    # The same shape can be used for an indexing read, not just new search.
    str(select(catalog(kinds)).compile(dialect=dialect()))


def test_schema_binds_actual_human_native_receipt_atom_and_threshold_without_private_text():
    up, down = "\n".join(upgrade_sql()), "\n".join(downgrade_sql())
    for expression in [
        "public.scope_actor() IS DISTINCT FROM public.scope_requester()",
        "h.kind='human'",
        "receipt.actor_id<>public.scope_actor()",
        "nx IS DISTINCT FROM sx",
        "receipt.confirmation_id IS NULL",
        "knowledge_answer_sources_known",
        "DEFERRABLE INITIALLY DEFERRED",
        "REVOKE ALL",
        "n>=5",
        "z<>a+interval '7 days'",
    ]:
        assert expression in up
    rate = up[up.index("CREATE FUNCTION public.knowledge_weekly_lookup_stats") :]
    assert "question" not in rate and "goal" not in rate and "comment" not in rate
    assert "Cannot discard recorded knowledge contributions" in down
    assert down.index("DROP TRIGGER knowledge_answer_origin") < down.index("DROP TABLE")


def test_week_is_fixed_utc_and_not_a_differencing_window():
    start, end = week_bounds("2026-10-26")
    assert start.tzinfo == UTC and end - start == timedelta(days=7)
    for value in ("2026-10-27", "bad", "2026-10-26T01:00:00Z"):
        with pytest.raises(DomainError):
            week_bounds(value)
    with pytest.raises(ValidationError):
        GapInput(
            run_id=uuid4(),
            kind="missing_material",
            request_key=uuid4(),
            preview_digest="a" * 64,
            question="browser injection",
        )


def test_policy_is_invoker_bounded_and_does_not_reenter_review_or_knowledge_catalog():
    from pdos_next.domain.knowledge.assistant_acl import upgrade_sql as acl_sql
    from pdos_next.domain.knowledge.assistant_storage import GUARD
    from pdos_next.enterprise_search.schemas import SOURCE_TYPES

    function = acl_sql()[0]
    assert "SECURITY INVOKER" in function and "SECURITY DEFINER" not in function
    assert "knowledge_answer_reviews" not in function
    assert "reviewed_enterprise_sources" not in function
    assert "ordinary_knowledge_leaves" in function
    assert "ordinary_knowledge_leaves" in function
    assert function.count(" INTO visible;") == len(SOURCE_TYPES)
    assert all(f" WHEN '{kind}' THEN" in function for kind in SOURCE_TYPES)
    assert "must flatten existing answer-derived parents" in GUARD
    assert "Native proof and review must be identical" in GUARD
    sql = "\n".join(upgrade_sql())
    assert sql.count("AS RESTRICTIVE FOR SELECT") == 3
    assert "answer_sources IS NULL OR" in sql
