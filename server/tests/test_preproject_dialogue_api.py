"""New intake dialogue: real authority/domain transactions, synthetic model/public I/O."""

import json
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.ai.conversation_reply import ConversationReplies
from app.ai.gateway import GatewayResult
from app.auth.repository import AuthRepository
from app.db.schema import tables
from tests.test_application_budget_factory import factory_setup as factory_setup
from tests.test_product_conversations_api import candidate as candidate
from tests.test_product_conversations_api import colleague
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database
from tests.test_xiaopai_conversation_search import model, run


class Gateway:
    def __init__(self, output):
        self.output, self.calls = output, []

    def invoke_structured(self, invocation, output_type):
        self.calls.append(invocation)
        return GatewayResult(
            status="succeeded",
            output=output_type.model_validate(self.output),
            error_code=None,
            structured_attempts=1,
            removed_context_paths=(),
        )


def message(c, conversation, goal, body="研究欧美桨板充气泵，休闲用户在码头使用"):
    return c.save(
        conversation,
        c.message(conversation, body, reply_only=True, action="note", preproject_goal=goal),
    )


def answer(c, conversation, msg, output):
    gateway = Gateway(output)
    ctx = AuthRepository(c.scope.engine).find_user_context(c.scope.owner_id)
    result = ConversationReplies(c.scope.engine, gateway).answer(
        ctx, UUID(conversation["id"]), UUID(msg["id"]), lambda _: None
    )
    return result, gateway


def category_candidate(code="SUP-new"):
    return dict(
        goal="category",
        stage="ready",
        category=dict(
            code=code,
            title="桨板充气泵研究",
            user_groups=["休闲桨板用户"],
            regions=["EU", "US"],
            use_scenarios=["码头充气"],
            research_questions=["测试条件与法规适用性需专家核对"],
            parameters=[
                dict(
                    key="runtime",
                    label="续航",
                    unit="min",
                    conditions="温度与负载待专家确认",
                    direction="higher",
                )
            ],
            notes=[
                dict(
                    kind="competitor",
                    title="竞品资料缺口",
                    body="本次搜索不可用，未知",
                    state="unknown",
                ),
                dict(kind="scene", title="场景假设", body="码头使用待用户验证", state="unknown"),
            ],
        ),
    )


def confirm(c, conversation, msg, result, **changes):
    body = dict(
        candidate_digest=result["preproject"]["candidate_digest"],
        confirmed=True,
        confirmed_shared=True,
    )
    body.update(changes)
    return c.client.post(
        f"/api/conversations/{conversation['id']}/messages/{msg['id']}/preproject/confirm",
        headers=c.headers,
        json=body,
    )


def count(c, table):
    with c.scope.engine.connect() as conn:
        return conn.execute(
            select(func.count()).select_from(table).where(table.c.tenant_id == c.scope.tenant_id)
        ).scalar_one()


def test_clarification_carries_typed_question_forward_and_scope_cannot_be_spoofed(candidate):
    c = candidate
    conversation = c.create("personal")
    q = dict(
        goal="category",
        stage="clarify",
        questions=[
            dict(
                id="region",
                question="首批销售地区？",
                options=["EU", "US"],
                recommendation="先选一个地区",
            )
        ],
    )
    before = count(c, tables.market_spaces)
    msg = message(c, conversation, "category")
    result, _ = answer(c, conversation, msg, dict(answer="先确认销售地区", preproject=q))
    assert (
        result["status"] == "answered" and confirm(c, conversation, msg, result).status_code == 409
    )
    follow = message(c, conversation, "category", "region：EU")
    _, gateway = answer(c, conversation, follow, dict(answer="再确认使用场景", preproject=q))
    context = gateway.calls[0].context["preproject"]
    assert context["previous_assessment"]["questions"][0]["question"] == "首批销售地区？"
    assert "region：EU" in context["user_brief"] and count(c, tables.market_spaces) == before
    c.save(
        conversation,
        c.message(conversation, reply_only=True, preproject_goal="proposal"),
        status=409,
    )
    space_chat = c.create("market_space")
    c.save(
        space_chat, c.message(space_chat, reply_only=True, preproject_goal="category"), status=409
    )


def test_category_search_candidate_requires_one_human_share_confirmation_and_replays(
    candidate, factory_setup, monkeypatch, tmp_path
):
    c = candidate
    conversation = c.create("personal")
    msg = message(c, conversation, "category")
    environment, calls = model(
        factory_setup,
        monkeypatch,
        tmp_path,
        choice=dict(action="search", target="桨板充气泵"),
        answer=dict(answer="搜索当前不可用，先列未知骨架。", preproject=category_candidate()),
    )
    result = run(c, environment, conversation, msg)
    assert result["status"] == "answered", result
    assert len(calls) == 2 and result["research"]["observations"][0]["status"] == "unavailable"
    wire_contexts = [
        json.loads(
            json.loads(call.content)["messages"][-1]["content"].split("PDOS_CONTEXT_JSON\n", 1)[1]
        )
        for call in calls
    ]
    assert all(ctx["preproject"]["goal"] == "category" for ctx in wire_contexts)
    assert wire_contexts[0]["preproject"]["category"] is None
    assert wire_contexts[1]["research"]["searches"] == 1
    assert wire_contexts[1]["research"]["failures"][0]["target"] == "桨板充气泵"
    before = count(c, tables.market_spaces)
    assert confirm(c, conversation, msg, result, confirmed_shared=False).status_code == 409
    assert count(c, tables.market_spaces) == before
    _, other = colleague(c)
    path = f"/api/conversations/{conversation['id']}/messages/{msg['id']}/preproject/confirm"
    assert (
        c.client.post(
            path,
            headers=other,
            json=dict(
                candidate_digest=result["preproject"]["candidate_digest"],
                confirmed=True,
                confirmed_shared=True,
            ),
        ).status_code
        == 403
    )
    saved = confirm(c, conversation, msg, result)
    assert saved.status_code == 201, saved.text
    assert confirm(c, conversation, msg, result).json() == saved.json()
    assert (
        count(c, tables.market_spaces) == before + 1
        and count(c, tables.preproject_confirmations) == 1
    )
    bundle = c.client.get(
        f"/api/product-work/categories/{saved.json()['category_id']}/shared", headers=c.headers
    ).json()
    assert bundle["parameters"][0]["key"] == "runtime"
    assert bundle["test_template"]["items"][0]["state"] == "expert_pending"
    assert (
        "未知" in bundle["knowledge"][0]["body"]
        and bundle["research_drafts"][0]["public_data"]["notes"][0]["state"] == "unknown"
    )
    with c.scope.engine.begin() as conn, pytest.raises(DBAPIError):
        conn.execute(tables.preproject_confirmations.delete())
    with c.scope.engine.connect() as conn:
        assert not conn.execute(
            text(
                "SELECT has_table_privilege('pdos_agent',"
                "'cehub_ai.preproject_confirmations','INSERT')"
            )
        ).scalar_one()


def test_category_candidate_without_research_is_unavailable_and_cannot_be_adopted(candidate):
    c = candidate
    conversation = c.create("personal")
    msg = message(c, conversation, "category")
    result, _ = answer(
        c, conversation, msg, dict(answer="未经搜索的候选", preproject=category_candidate())
    )
    assert result["status"] == "unavailable" and result["error_code"] == "PREPROJECT_OUTPUT_INVALID"
    assert "preproject" not in result and count(c, tables.preproject_confirmations) == 0


def test_customer_proposal_is_private_ai_draft_and_new_round_blocks_old_candidate(
    candidate,
):
    c = candidate
    conversation = c.create("market_space")
    output = dict(
        answer="已起草，需你确认保存。",
        preproject=dict(
            goal="proposal",
            stage="ready",
            proposal=dict(
                title="客户专属提案",
                entry_kind="odm",
                document=dict(
                    narrative="客户X要便携续航30分钟",
                    specifications=[
                        dict(
                            id="battery",
                            label="续航",
                            value="30",
                            unit="min",
                            state="ai_draft",
                            source_ids=["brief"],
                        )
                    ],
                    questions=["目标价格？"],
                    risks=["续航待实测"],
                ),
            ),
        ),
    )
    msg = message(c, conversation, "proposal", "客户X要便携续航30分钟")
    result, gateway = answer(c, conversation, msg, output)
    assert (
        result["status"] == "answered"
        and gateway.calls[0].context["preproject"]["category"]["category_id"] == c.space_id
    )
    saved = confirm(c, conversation, msg, result)
    assert saved.status_code == 201, saved.text
    assert confirm(c, conversation, msg, result).json() == saved.json()
    p = c.client.get(
        f"/api/product-work/spaces/{c.space_id}/proposals/{saved.json()['proposal_id']}",
        headers=c.headers,
    ).json()
    assert p["state"] == "draft" and p["document"]["specifications"][0]["state"] == "ai_draft"
    assert p["history"][0]["origin"] == "ai_assisted"
    bundle = c.client.get(
        f"/api/product-work/categories/{c.space_id}/shared", headers=c.headers
    ).json()
    assert "客户X" not in str(bundle) and bundle["research_drafts"] == []
    _, other = colleague(c)
    assert (
        c.client.get(
            f"/api/product-work/spaces/{c.space_id}/proposals/{saved.json()['proposal_id']}",
            headers=other,
        ).status_code
        == 403
    )
    newer = message(c, conversation, "proposal", "另一个未确认的提案")
    pending, _ = answer(c, conversation, newer, output)
    message(c, conversation, "proposal", "续航改成45分钟")
    assert confirm(c, conversation, newer, pending).status_code == 409
    assert count(c, tables.product_proposals) == 1


def test_ai_confirmed_specs_are_rejected_before_human_write(candidate):
    c = candidate
    conversation = c.create("market_space")
    msg = message(c, conversation, "proposal")
    result, _ = answer(
        c,
        conversation,
        msg,
        dict(
            answer="错误确认",
            preproject=dict(
                goal="proposal",
                stage="ready",
                proposal=dict(
                    title="候选",
                    entry_kind="odm",
                    document=dict(
                        specifications=[
                            dict(id="s", label="规格", state="confirmed", source_ids=["brief"])
                        ]
                    ),
                ),
            ),
        ),
    )
    assert (
        result["error_code"] == "PREPROJECT_OUTPUT_INVALID"
        and count(c, tables.product_proposals) == 0
    )


@pytest.mark.parametrize("source_changed", [False, True])
@pytest.mark.parametrize("candidate_age_minutes", [0, 31, 1440])
def test_public_read_is_adopted_or_rejected_when_changed(
    candidate, factory_setup, monkeypatch, tmp_path, source_changed, candidate_age_minutes
):
    from datetime import UTC, datetime, timedelta

    from app.ai import conversation_research
    from app.ai.reach import ReachResponse
    from app.domain import preproject_dialogue
    from tests import test_application_budget_factory as factory
    from tests.test_model_budget_controller import response

    c = candidate
    environment, _ = model(
        factory_setup,
        monkeypatch,
        tmp_path,
        choice=dict(action="read", target="https://example.com/spec"),
        answer={},
    )

    class Transport:
        def __init__(self, **kwargs):
            pass

        def get(self, url):
            body = "<title>公开充气泵规格</title><article>码头充气，压力120kPa。</article>"
            return ReachResponse(200, body, "text/html", len(body.encode()))

    monkeypatch.setattr(conversation_research, "PublicReachTransport", Transport)

    def reply():
        with c.scope.engine.connect() as conn:
            snap = conn.execute(
                select(tables.evidence_snapshots.c.id).where(
                    tables.evidence_snapshots.c.tenant_id == c.scope.tenant_id
                )
            ).scalar_one_or_none()
        if snap is None:
            return response(
                json.dumps(
                    dict(answer="", research=dict(action="read", target="https://example.com/spec"))
                )
            )
        prepared = category_candidate()
        prepared["category"]["notes"][1].update(
            body="码头充气", state="ai_draft", citation_ids=[f"snapshot:{snap}"]
        )
        return response(
            json.dumps(
                dict(answer="已读取原文，资料待复核。", preproject=prepared), ensure_ascii=False
            )
        )

    monkeypatch.setattr(factory, "response", reply)
    conversation = c.create("personal")
    msg = message(c, conversation, "category")
    result = run(c, environment, conversation, msg)
    assert result["status"] == "answered", result
    assert result["citations"][0]["href"] == "https://example.com/spec"
    if source_changed:
        from app.domain.evidence import EvidenceService

        evidence = EvidenceService(c.scope.engine)
        replacement = evidence.capture(
            tenant_id=c.scope.tenant_id, actor_user_id=c.scope.owner_id, content="更新后的公开原文"
        )
        evidence.supersede(
            tenant_id=c.scope.tenant_id,
            actor_user_id=c.scope.owner_id,
            snapshot_id=UUID(result["citations"][0]["reference_id"].split(":")[1]),
            superseded_by_id=replacement.id,
        )
    before = count(c, tables.market_spaces)

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz or UTC) + timedelta(minutes=candidate_age_minutes)

    monkeypatch.setattr(preproject_dialogue, "datetime", Later)
    saved = confirm(c, conversation, msg, result)
    assert saved.status_code == (409 if source_changed else 201), saved.text
    assert count(c, tables.market_spaces) == before + (0 if source_changed else 1)
    assert count(c, tables.preproject_confirmations) == (0 if source_changed else 1)
    if not source_changed:
        bundle = c.client.get(
            f"/api/product-work/categories/{saved.json()['category_id']}/shared", headers=c.headers
        ).json()
        assert (
            bundle["research_drafts"][0]["public_data"]["citations"][0]["href"]
            == "https://example.com/spec"
        )


def test_category_search_reads_two_pages_from_one_registered_origin(
    candidate, factory_setup, monkeypatch, tmp_path
):
    import json
    from types import SimpleNamespace

    from app.ai import conversation_research
    from app.ai.reach import ReachResponse
    from app.ai.research_search import SearchResult
    from tests import test_application_budget_factory as factory
    from tests.test_model_budget_controller import response

    c = candidate
    urls = ["https://example.com/spec-a", "https://example.com/spec-b"]
    environment, calls = model(
        factory_setup,
        monkeypatch,
        tmp_path,
        choice=dict(action="search", target="公开充气泵规格"),
        answer={},
    )
    monkeypatch.setattr(
        conversation_research,
        "resolve_search_provider",
        lambda *a, **kw: SimpleNamespace(
            key="synthetic",
            search=lambda *a, **kw: SearchResult(
                status="completed",
                hits=[dict(url=url) for url in urls],
                warnings=[],
                response_digest="a" * 64,
                rejected_count=0,
            ),
        ),
    )

    class Transport:
        def __init__(self, **kwargs):
            pass

        def get(self, url):
            body = f"<title>充气泵</title><article>{url} 最大压力20PSI。</article>"
            return ReachResponse(200, body, "text/html", len(body.encode()))

    monkeypatch.setattr(conversation_research, "PublicReachTransport", Transport)

    def reply():
        with c.scope.engine.connect() as conn:
            snaps = list(
                conn.execute(
                    select(tables.evidence_snapshots.c.id).where(
                        tables.evidence_snapshots.c.tenant_id == c.scope.tenant_id
                    )
                ).scalars()
            )
        if not snaps:
            return response(
                json.dumps(dict(answer="", research=dict(action="search", target="公开充气泵规格")))
            )
        assert len(snaps) == 2
        prepared = category_candidate()
        prepared["category"]["notes"][0].update(
            body="已读取两页公开参数。",
            state="ai_draft",
            citation_ids=[f"snapshot:{snap}" for snap in snaps],
        )
        return response(json.dumps(dict(answer="已核对两页原文。", preproject=prepared)))

    monkeypatch.setattr(factory, "response", reply)
    conversation = c.create("personal")
    msg = message(c, conversation, "category")
    result = run(c, environment, conversation, msg)
    assert result["status"] == "answered", result
    assert len(calls) == 2
    assert {item["href"] for item in result["citations"]} == set(urls)
    with c.scope.engine.connect() as conn:
        sources = list(
            conn.execute(
                select(tables.evidence_snapshots.c.source_id).where(
                    tables.evidence_snapshots.c.tenant_id == c.scope.tenant_id
                )
            ).scalars()
        )
    assert len(set(sources)) == 1
    assert count(c, tables.research_sources) == 1
    assert count(c, tables.preproject_confirmations) == 0


@pytest.mark.parametrize("race", [False, True])
def test_public_source_registration_reuses_matching_source_without_rewriting(
    candidate, monkeypatch, race
):
    from app.ai.conversation_research import ConversationResearch
    from app.domain.evidence import EvidenceService

    c = candidate
    ctx = AuthRepository(c.scope.engine).find_user_context(c.scope.owner_id)
    evidence = EvidenceService(c.scope.engine)
    original = evidence.create_source
    if race:

        def competing_create(**kwargs):
            original(**kwargs)
            return original(**kwargs)

        monkeypatch.setattr(evidence, "create_source", competing_create)
    research = ConversationResearch(c.scope.engine, None)
    source_id = research._public_source(evidence, ctx, "example.com", "https://example.com")
    with c.scope.engine.connect() as conn:
        before = dict(
            conn.execute(
                select(tables.research_sources).where(tables.research_sources.c.id == source_id)
            )
            .mappings()
            .one()
        )
    assert research._public_source(evidence, ctx, "example.com", "https://example.com") == source_id
    with c.scope.engine.connect() as conn:
        after = dict(
            conn.execute(
                select(tables.research_sources).where(tables.research_sources.c.id == source_id)
            )
            .mappings()
            .one()
        )
    assert after == before
    assert count(c, tables.research_sources) == 1


@pytest.mark.parametrize("change", [{"status": "disabled"}, {"base_url": "https://other.example"}])
def test_public_source_registration_refuses_revoked_or_mismatched_source(candidate, change):
    from app.ai.conversation_research import ConversationResearch
    from app.domain.evidence import EvidenceService, EvidenceValidationError

    c = candidate
    ctx = AuthRepository(c.scope.engine).find_user_context(c.scope.owner_id)
    research = ConversationResearch(c.scope.engine, None)
    evidence = EvidenceService(c.scope.engine)
    source_id = research._public_source(evidence, ctx, "example.com", "https://example.com")
    with c.scope.engine.begin() as conn:
        conn.execute(
            tables.research_sources.update()
            .where(tables.research_sources.c.id == source_id)
            .values(**change)
        )
    with pytest.raises(EvidenceValidationError):
        research._public_source(evidence, ctx, "example.com", "https://example.com")
    assert count(c, tables.research_sources) == 1


def test_atomic_failure_and_history_downgrade_refusal(
    candidate, factory_setup, monkeypatch, tmp_path
):
    import os
    import subprocess

    c = candidate
    code = c.client.get(f"/api/product-work/spaces/{c.space_id}", headers=c.headers).json()[
        "space"
    ]["code"]
    environment, _ = model(
        factory_setup,
        monkeypatch,
        tmp_path,
        choice=dict(action="search", target="桨板充气泵"),
        answer=dict(answer="搜索不可用，候选保留未知。", preproject=category_candidate(code)),
    )
    conversation = c.create("personal")
    msg = message(c, conversation, "category")
    result = run(c, environment, conversation, msg)
    assert result["status"] == "answered", result
    before = count(c, tables.market_spaces)
    assert confirm(c, conversation, msg, result).status_code == 409
    assert (
        count(c, tables.market_spaces) == before and count(c, tables.preproject_confirmations) == 0
    )
    with c.scope.engine.connect() as conn:
        original_head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    rejected = subprocess.run(
        [".venv/bin/alembic", "downgrade", "0427_category_reference_aliases"],
        env={**os.environ, "DATABASE_URL": os.environ["TEST_DATABASE_URL"]},
        capture_output=True,
        text=True,
    )
    assert (
        rejected.returncode != 0
        and "Multi-round research history must be preserved" in rejected.stderr
    )
    with c.scope.engine.connect() as conn:
        assert (
            conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == original_head
        )
