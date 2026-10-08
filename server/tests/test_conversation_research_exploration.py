"""Iterative research through actual application authority and receipts; public I/O is synthetic."""

import json
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.exc import DBAPIError

from app.ai import conversation_research, provider_streaming
from app.ai.application_gateway import configured_application_gateway
from app.ai.budget_adoption import PROFILE_KEY
from app.ai.conversation_reply import ConversationReplies, read_reply
from app.ai.reach import ReachResponse
from app.ai.research_search import SearchResult
from app.auth.repository import AuthRepository
from app.db.schema import tables
from app.db.url import psycopg_database_url
from tests import test_application_budget_factory as factory
from tests.test_application_budget_factory import factory_setup as factory_setup
from tests.test_model_budget_controller import response
from tests.test_product_conversations_api import candidate as candidate
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database
from tests.test_xiaopai_conversation_reply_api import save
from tests.test_xiaopai_conversation_search import model, run


def test_shared_reference_window_keeps_every_identity_and_does_not_mutate_receipts():
    original = [dict(reference_id=f"snapshot:{i}", excerpt="原文依据" * 6000) for i in range(24)]
    receipt = dict(version=conversation_research.VERSION, references=original)
    visible = conversation_research.research_references(receipt)
    assert [ref["reference_id"] for ref in visible] == [ref["reference_id"] for ref in original]
    assert sum(len(ref["excerpt"]) for ref in visible) < 25_000
    assert all("截断" in ref["excerpt"] for ref in visible)
    assert len(original[0]["excerpt"]) == 24_000
    assert (
        conversation_research.research_context(dict(version="xiaopai-public-research-v1"))[
            "remaining"
        ]
        == 0
    )


def test_excerpts_retain_late_specifications_and_mark_omitted_passages():
    text = (
        "公开来源；taint=untrusted_external\nBrand A official product\n"
        + "A long introduction with no measured product claims.\n" * 150
        + "Model A: 20 PSI, 12 V, 74 Wh, $179.99; 123 reviews.\n"
        + "Another long unrelated introduction.\n" * 100
    )
    shown = conversation_research.evidence_excerpt(text, 900)
    assert "taint=untrusted_external" in shown
    assert "Model A: 20 PSI, 12 V, 74 Wh, $179.99; 123 reviews." in shown
    assert "省略" in shown and "截断" in shown
    # Every selected non-marker passage is still literal text from this source.
    passages = shown.split("\n[中间原文省略]\n")
    for passage in passages:
        assert passage.split("\n[原文片段截断")[0] in text


def test_research_can_discover_ten_candidates_read_ten_sources_and_skip_repeat_url(
    candidate, factory_setup, monkeypatch, tmp_path
):
    c = candidate
    environment, calls = model(
        factory_setup,
        monkeypatch,
        tmp_path,
        choice=dict(action="search", target="popular products"),
        answer=dict(answer="unused", citation_ids=[]),
        qualified_input_limit=16000,
        window_tokens=32768,
    )
    environment[PROFILE_KEY] = "research_discussion"
    outputs = iter(
        [
            dict(answer="", research=dict(action="search", target="popular products")),
            dict(
                answer="",
                research=dict(action="read", target="https://brand0.example/spec/#reviews"),
            ),
            dict(answer="", research=dict(action="search", target="official specifications")),
            dict(answer="", research=dict(action="search", target="independent reviews")),
            dict(answer="", research=dict(action="search", target="regional models")),
            dict(answer="已核对10份不同品牌的资料；热门依据不足的标为候选。", citation_ids=[]),
        ]
    )

    def response_with_progress():
        content = json.dumps(next(outputs), ensure_ascii=False)
        provider_streaming._thinking_observer.get()()
        provider_streaming._observer.get()(content)
        return response(content)

    monkeypatch.setattr(factory, "response", response_with_progress)
    queries, reads = [], []

    class Provider:
        key = "tavily"

        def search(self, query, **kwargs):
            assert kwargs["limit"] == 10
            queries.append(query)
            return SearchResult(
                "completed",
                [
                    dict(
                        url=f"https://brand{i}.example/spec/",
                        title=f"Brand {i}",
                        snippet="产品线索",
                    )
                    for i in range(10)
                ],
                [],
                "a" * 64,
                0,
            )

    class Transport:
        def __init__(self, **kwargs):
            pass

        def get(self, url):
            reads.append(url)
            body = (
                f"<html><title>{url}</title>"
                "<body>公开产品规格：20 PSI，12V供电，评论热度未知。</body></html>"
            )
            return ReachResponse(200, body, "text/html", len(body.encode()))

    monkeypatch.setattr(
        conversation_research, "resolve_search_provider", lambda *args, **kwargs: Provider()
    )
    monkeypatch.setattr(conversation_research, "PublicReachTransport", Transport)
    conversation = c.create("personal")
    message = save(c, conversation, "广泛研究热门产品和不同品牌的官方参数")
    context = AuthRepository(c.scope.engine).find_user_context(c.scope.owner_id)
    checked = []
    with configured_application_gateway(c.scope.engine, environment) as gateway:

        def check_immutable(event):
            if checked or event.get("message") != "正在核对覆盖缺口":
                return
            run_id = UUID(event["run_id"])
            with c.scope.engine.connect() as connection:
                original = connection.execute(
                    select(tables.agent_runs.c.run_context).where(tables.agent_runs.c.id == run_id)
                ).scalar_one()
            changed_history = deepcopy(original)
            changed_history["reply_research"]["observations"][0]["output"]["target"] = "changed"
            forged_append = deepcopy(original)
            forged_append["reply_research"]["rounds"].append(
                deepcopy(original["reply_research"]["rounds"][0])
            )
            forged_append["reply_research"]["observations"].append(
                dict(
                    id="00000000-0000-0000-0000-000000000001",
                    output=dict(tool="read", status="completed"),
                )
            )
            for value, reason in [
                (changed_history, "history is immutable"),
                (forged_append, "APPEND_INVALID"),
            ]:
                with pytest.raises(DBAPIError, match=reason), c.scope.engine.begin() as connection:
                    conversation_research.ConversationResearch(c.scope.engine, gateway)._authorize(
                        connection, context, run_id
                    )
                    connection.execute(
                        tables.agent_runs.update()
                        .where(tables.agent_runs.c.id == run_id)
                        .values(run_context=value)
                    )
            checked.append(True)

        result = ConversationReplies(c.scope.engine, gateway).answer(
            context, UUID(conversation["id"]), UUID(message["id"]), check_immutable
        )
    assert result["status"] == "answered", result
    assert checked == [True]
    assert len(calls) == 6 and len(queries) == 4
    assert len(reads) == len(set(reads)) == len(result["citations"]) == 10
    assert result["research"]["candidate_count"] == 10
    assert result["research"]["searches"] == 4
    assert result["process"]["earlier_steps_omitted"] > 0
    assert len(result["process"]["steps"]) == 16
    assert result["research"]["stop_reason"] == "model_completed"
    with c.scope.engine.connect() as connection:
        observations = list(connection.execute(select(tables.application_tool_observations)))
        assert len(observations) == 14
        run_context = connection.execute(
            select(tables.agent_runs.c.run_context).where(
                tables.agent_runs.c.id == UUID(result["run_id"])
            )
        ).scalar_one()
        assert run_context["reply_research"]["rounds"][1]["status"] == "duplicate"
    assert (
        read_reply(c.scope.engine, context, UUID(conversation["id"]), UUID(message["id"])) == result
    )
    assert run(c, environment, conversation, message) == result
    assert len(calls) == 6 and len(reads) == 10
    with pytest.raises(RuntimeError, match="history must be preserved"):
        command.downgrade(
            Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")),
            "0430_application_token_budget",
        )


def test_exploration_limits_stop_search_dispatch_then_allow_honest_final_answer(
    candidate, factory_setup, monkeypatch, tmp_path
):
    c = candidate
    environment, calls = model(
        factory_setup,
        monkeypatch,
        tmp_path,
        choice=dict(action="search", target="first"),
        answer=dict(answer="unused"),
    )
    environment[PROFILE_KEY] = "research_discussion"
    outputs = iter(
        [
            *[
                dict(answer="", research=dict(action="search", target=f"query {i}"))
                for i in range(7)
            ],
            dict(answer="本轮未取得公开资料，保留未知，不声称产品不存在。", citation_ids=[]),
        ]
    )
    monkeypatch.setattr(
        factory, "response", lambda: response(json.dumps(next(outputs), ensure_ascii=False))
    )
    queries = []

    class Provider:
        key = "tavily"

        def search(self, query, **kwargs):
            queries.append(query)
            return SearchResult("no_results", [], [], "a" * 64, 0)

    monkeypatch.setattr(
        conversation_research, "resolve_search_provider", lambda *args, **kwargs: Provider()
    )
    conversation = c.create("personal")
    result = run(c, environment, conversation, save(c, conversation, "继续查找直到资料足够"))
    assert result["status"] == "answered", result
    assert len(queries) == 6 and len(calls) == 8
    assert not result["citations"]
    assert result["research"]["search_remaining"] == 0
    assert result["research"]["remaining"] == 0
    with c.scope.engine.connect() as connection:
        assert len(list(connection.execute(select(tables.agent_tool_dispatches)))) == 6
        assert all(
            row[0] == "settled"
            for row in connection.execute(
                select(tables.budget_journal.c.reservation_status).where(
                    tables.budget_journal.c.revision == 3
                )
            )
        )


def test_empty_exploration_migration_round_trip(isolated_test_run_database):
    engine = create_engine(psycopg_database_url(isolated_test_run_database))
    with engine.connect() as connection:
        assert not connection.execute(select(tables.tenants.c.id)).first()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.downgrade(config, "0430_application_token_budget")
    command.upgrade(config, "head")
    engine.dispose()
