"""Ordinary chat research: real authority/budget/checkpoints, synthetic public I/O."""

import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.ai import conversation_research, provider_streaming
from app.ai.application_gateway import configured_application_gateway
from app.ai.budget_adoption import METER_DIGEST_KEY, METER_PATH_KEY
from app.ai.conversation_reply import ConversationReplies, read_reply
from app.ai.reach import ReachPolicy, ReachResponse
from app.ai.research_search import SearchResult
from app.auth.repository import AuthRepository
from app.db.schema import tables
from app.domain.evidence import EvidenceService
from app.domain.research_index import ResearchIndexService
from tests import test_application_budget_factory as factory
from tests.test_application_budget_factory import factory_setup as factory_setup
from tests.test_input_metering import publication
from tests.test_model_budget_controller import response
from tests.test_product_conversations_api import candidate as candidate
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database
from tests.test_xiaopai_conversation_reply_api import save

URL = "https://example.com/spec"
BODY = "<html><title>无刷电机规格</title><body>无刷电机峰值压力120kPa。</body></html>"


def indexed(c):
    evidence = EvidenceService(c.scope.engine)
    source = evidence.create_source(
        tenant_id=c.scope.tenant_id,
        actor_user_id=c.scope.owner_id,
        name="合成公开来源",
        source_type="web",
        base_url="https://example.com",
        allowed_use="internal_analysis",
        collection_frequency="daily",
        retention_policy="standard",
        trust_tier="unknown",
    )
    snap = evidence.capture(
        tenant_id=c.scope.tenant_id,
        actor_user_id=c.scope.owner_id,
        source_id=source.id,
        content=BODY,
        url=URL,
        content_language="zh",
        taint="untrusted_external",
    )
    with c.scope.engine.begin() as connection:
        ResearchIndexService(c.scope.engine).project(
            connection,
            tenant_id=c.scope.tenant_id,
            space_id=UUID(c.space_id),
            line_id=UUID(c.line["id"]),
            source_id=source.id,
            snapshot_id=snap.id,
            content_digest=snap.content_digest,
            url=URL,
            lang="zh",
            captured_at=snap.captured_at,
            body=BODY,
        )
    return snap


def model(
    factory_setup,
    monkeypatch,
    tmp_path,
    *,
    choice,
    answer,
    qualified_input_limit=4096,
    window_tokens=8192,
):
    monkeypatch.setattr(
        conversation_research,
        "get_settings",
        lambda: SimpleNamespace(
            research_search_endpoint=None,
            research_tavily_api_key=None,
            research_firecrawl_api_key=None,
        ),
    )
    environment, calls, _ = factory_setup
    directory = tmp_path / "search-meter"
    directory.mkdir()
    path, _, sha = publication(
        directory, qualified_input_limit=qualified_input_limit, window_tokens=window_tokens
    )
    environment = {**environment, METER_PATH_KEY: str(path), METER_DIGEST_KEY: sha}
    monkeypatch.setattr(provider_streaming, "enabled", lambda: False)
    outputs = iter([dict(answer="", citation_ids=[], research=choice), answer])
    monkeypatch.setattr(
        factory, "response", lambda: response(json.dumps(next(outputs), ensure_ascii=False))
    )
    monkeypatch.setattr(
        conversation_research,
        "ReachPolicy",
        lambda: ReachPolicy(resolver=lambda _: ["93.184.216.34"]),
    )
    from app.ai import research_search

    monkeypatch.setattr(
        research_search, "ReachPolicy", lambda: ReachPolicy(resolver=lambda _: ["93.184.216.34"])
    )
    return environment, calls


def run(c, environment, conversation, message, emit=lambda _: None):
    context = AuthRepository(c.scope.engine).find_user_context(c.scope.owner_id)
    with configured_application_gateway(c.scope.engine, environment) as gateway:
        return ConversationReplies(c.scope.engine, gateway).answer(
            context,
            UUID(conversation["id"]),
            UUID(message["id"]),
            emit,
        )


@pytest.mark.parametrize("goal", [None, "category"])
def test_legacy_model_search_returns_saved_configuration_failure_without_dispatch(
    candidate, factory_setup, monkeypatch, tmp_path, goal
):
    from app.api.ai import get_application_gateway

    c = candidate
    conversation = c.create("personal")
    message = c.save(
        conversation,
        c.message(
            conversation,
            "研究欧美市场的桨板充气泵",
            reply_only=True,
            **({"preproject_goal": goal} if goal else {}),
        ),
    )
    environment, calls = model(
        factory_setup,
        monkeypatch,
        tmp_path,
        choice=dict(action="search", target="paddle pump specifications"),
        answer=dict(answer="must never be called"),
    )
    legacy = {
        key: value for key, value in environment.items() if not key.startswith("PDOS_APPLICATION_")
    }
    monkeypatch.setattr(
        conversation_research,
        "resolve_search_provider",
        lambda *a, **kw: pytest.fail("unadmitted search must never reach a provider"),
    )
    with configured_application_gateway(c.scope.engine, legacy) as gateway:
        c.client.app.dependency_overrides[get_application_gateway] = lambda: gateway
        streamed = c.client.post(
            f"/api/conversations/{conversation['id']}/messages/{message['id']}/reply",
            headers=c.headers,
        )
        assert streamed.status_code == 200
        events = [
            json.loads(frame[6:])
            for frame in streamed.text.split("\n\n")
            if frame.startswith("data: ")
        ]
        result = next(event["reply"] for event in events if event["type"] == "result")
        assert events[-1] == {"type": "done"}
        assert not any(event["type"] == "error" for event in events)
        assert not any(event.get("message", "").startswith("正在搜索") for event in events)
        assert len(calls) == 1
        assert result["status"] == "unavailable"
        assert result["error_code"] == "APPLICATION_RESEARCH_BUDGET_REQUIRED"
        restored = c.client.get(
            f"/api/conversations/{conversation['id']}/messages/{message['id']}/reply",
            headers=c.headers,
        ).json()["reply"]
        assert restored == result
        replay = c.client.post(
            f"/api/conversations/{conversation['id']}/messages/{message['id']}/reply",
            headers=c.headers,
        )
        assert "APPLICATION_RESEARCH_BUDGET_REQUIRED" in replay.text and len(calls) == 1
    with c.scope.engine.connect() as connection:
        for name in [
            "application_authorizations",
            "application_run_leases",
            "application_result_checkpoints",
            "application_tool_observations",
            "agent_tool_intents",
            "agent_tool_dispatches",
        ]:
            table = getattr(tables, name)
            assert (
                connection.execute(
                    select(table.c.run_id).where(table.c.run_id == UUID(result["run_id"]))
                ).first()
                is None
            )


@pytest.mark.parametrize(
    "local_miss,tavily_failed,long_body",
    [
        (False, False, False),
        (False, True, False),
        (True, False, False),
        (True, True, False),
        (False, True, True),
    ],
)
def test_public_chat_uses_tavily_firecrawl_and_cites_captured_body(
    candidate, factory_setup, monkeypatch, tmp_path, local_miss, tavily_failed, long_body
):
    from app.ai import firecrawl, research_search

    c = candidate
    if local_miss:
        indexed(c)
    environment, _ = model(
        factory_setup,
        monkeypatch,
        tmp_path,
        choice=dict(action="search", target="电池寿命"),
        answer=dict(answer="已核对电池寿命。", citation_ids=[]),
    )
    monkeypatch.setattr(
        conversation_research,
        "get_settings",
        lambda: SimpleNamespace(
            research_search_endpoint=None,
            research_tavily_api_key=SecretStr("test-tavily"),
            research_firecrawl_api_key=SecretStr("test-firecrawl"),
        ),
    )
    monkeypatch.setattr(
        firecrawl, "ReachPolicy", lambda: ReachPolicy(resolver=lambda _: ["93.184.216.34"])
    )
    dispatched = []

    def tavily(self, path, headers, payload):
        dispatched.append(("tavily", path))
        assert headers["Authorization"] == "Bearer test-tavily"
        if tavily_failed:
            return 429, "{}"
        return 200, json.dumps({"results": [{"url": URL, "title": "电池寿命", "content": "线索"}]})

    def crawl(self, path, headers, payload):
        dispatched.append(("firecrawl", path))
        assert headers["Authorization"] == "Bearer test-firecrawl"
        if path == "/v2/search":
            return 200, json.dumps(
                {
                    "success": True,
                    "data": {"web": [{"url": URL, "title": "电池寿命", "description": "线索"}]},
                }
            )
        assert payload["url"] == URL
        return 200, json.dumps(
            {
                "success": True,
                "data": {
                    "html": "<title>电池寿命</title><article>电池寿命500次循环。"
                    + ("Public battery cycle specification. " * 200 if long_body else "")
                    + "</article>",
                    "metadata": {
                        "sourceURL": URL,
                        "url": URL,
                        "statusCode": 200,
                        "contentType": "text/html",
                    },
                },
            }
        )

    monkeypatch.setattr(research_search.TavilyHttpTransport, "post", tavily)
    monkeypatch.setattr(firecrawl.FirecrawlHttpTransport, "post", crawl)
    turn = 0

    def model_response(*args):
        nonlocal turn
        turn += 1
        if turn == 1:
            return response(
                json.dumps(
                    dict(
                        answer="",
                        citation_ids=[],
                        research=dict(action="search", target="电池寿命"),
                    ),
                    ensure_ascii=False,
                )
            )
        with c.scope.engine.connect() as connection:
            snap = connection.execute(
                select(tables.evidence_snapshots.c.id).where(
                    tables.evidence_snapshots.c.source_version == "firecrawl-scrape-v2"
                )
            ).scalar_one()
        return response(
            json.dumps(
                dict(
                    answer="电池寿命500次循环。", citation_ids=[f"snapshot:{snap}"], research=None
                ),
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(factory, "response", model_response)
    conversation = c.create("personal")
    message = save(c, conversation, "搜索电池寿命")
    result = run(c, environment, conversation, message)
    assert result["status"] == "answered" and result["citations"][0]["href"] == URL
    assert dispatched[0] == ("tavily", "/search")
    assert dispatched[-1] == ("firecrawl", "/v2/scrape")
    with c.scope.engine.connect() as connection:
        read_metadata = connection.execute(
            select(tables.application_tool_observations.c.metadata).where(
                tables.application_tool_observations.c.output_body["tool"].astext == "read"
            )
        ).scalar_one()
    assert read_metadata["truncated"] is long_body
    if long_body:
        assert read_metadata["continuation"] == result["citations"][0]["reference_id"]
    else:
        assert read_metadata["continuation"] is None
    if tavily_failed:
        assert dispatched[1] == ("firecrawl", "/v2/search")
    observed = result["research"]["observations"][0]
    assert observed["provider_key"] == ("firecrawl" if tavily_failed else "tavily")
    count = len(dispatched)
    assert run(c, environment, conversation, message)["status"] == "answered"
    assert len(dispatched) == count and turn == 2


def test_ordinary_personal_question_searches_keywords_reads_local_snapshot_and_cites(
    candidate,
    factory_setup,
    monkeypatch,
    tmp_path,
):
    c = candidate
    snap = indexed(c)
    environment, calls = model(
        factory_setup,
        monkeypatch,
        tmp_path,
        choice=dict(action="search", target="无刷电机 峰值压力"),
        answer=dict(answer="该规格注明峰值压力120kPa。", citation_ids=[f"snapshot:{snap.id}"]),
    )
    conversation = c.create("personal")
    message = save(c, conversation, "帮我搜索无刷电机的峰值压力")
    emitted = []
    result = run(c, environment, conversation, message, emitted.append)
    assert result["status"] == "answered", result
    assert len(calls) == 2
    assert result["citations"][0]["entity_id"] == str(snap.id)
    assert "120kPa" in result["citations"][0]["excerpt"]
    assert any(item.get("message") == "正在搜索：无刷电机 峰值压力" for item in emitted)
    assert any(item.get("message") == "正在读取：" + URL for item in emitted)
    assert result["research"]["remaining"] == 0
    with c.scope.engine.connect() as connection:
        assert len(list(connection.execute(select(tables.agent_tool_intents)))) == 2
        assert len(list(connection.execute(select(tables.agent_tool_dispatches)))) == 2
        assert len(list(connection.execute(select(tables.application_tool_observations)))) == 2
    context = AuthRepository(c.scope.engine).find_user_context(c.scope.owner_id)
    assert (
        read_reply(c.scope.engine, context, UUID(conversation["id"]), UUID(message["id"])) == result
    )
    assert run(c, environment, conversation, message) == result
    assert len(calls) == 2
    replacement = EvidenceService(c.scope.engine).capture(
        tenant_id=c.scope.tenant_id,
        actor_user_id=c.scope.owner_id,
        content="新版规格",
        url=URL,
        content_language="zh",
        taint="untrusted_external",
    )
    EvidenceService(c.scope.engine).supersede(
        tenant_id=c.scope.tenant_id,
        actor_user_id=c.scope.owner_id,
        snapshot_id=snap.id,
        superseded_by_id=replacement.id,
    )
    assert (
        read_reply(c.scope.engine, context, UUID(conversation["id"]), UUID(message["id"]))[
            "error_code"
        ]
        == "REPLY_SOURCE_CHANGED"
    )


@pytest.mark.parametrize(
    "action,target", [("read", "http://127.0.0.1/admin"), ("search", "未配置的搜索")]
)
def test_unavailable_search_or_denied_url_is_observed_then_answered_honestly(
    candidate,
    factory_setup,
    monkeypatch,
    tmp_path,
    action,
    target,
):
    c = candidate
    environment, calls = model(
        factory_setup,
        monkeypatch,
        tmp_path,
        choice=dict(action=action, target=target),
        answer=dict(answer="本次资料未能读取，暂不能确认。", citation_ids=[]),
    )
    conversation = c.create("personal")
    message = save(c, conversation, "请查一下")
    result = run(c, environment, conversation, message)
    assert result["status"] == "answered", result
    assert len(calls) == 2 and result["citations"] == []
    assert result["research"]["observations"][0]["status"] == "unavailable"


@pytest.mark.parametrize("action", ["search", "read"])
def test_public_search_hits_are_fetched_as_snapshots_before_answer_not_cited_as_snippets(
    candidate,
    factory_setup,
    monkeypatch,
    tmp_path,
    action,
):
    c = candidate
    reads = []

    class Provider:
        key = "searxng"

        def search(self, query, **kwargs):
            assert query == "公开气泵参数"
            return SearchResult(
                "completed",
                [dict(url=URL, title="线索", snippet="不可作为引用的摘要")],
                [],
                "a" * 64,
                0,
            )

    class Transport:
        def __init__(self, **kwargs):
            pass

        def get(self, url):
            reads.append(url)
            body = BODY.replace("</body>", f"<p>{url}</p></body>")
            return ReachResponse(200, body, "text/html", len(body.encode()))

    monkeypatch.setattr(
        conversation_research, "resolve_search_provider", lambda *args, **kwargs: Provider()
    )
    monkeypatch.setattr(conversation_research, "PublicReachTransport", Transport)
    environment, calls = model(
        factory_setup,
        monkeypatch,
        tmp_path,
        choice=dict(action=action, target="公开气泵参数" if action == "search" else URL),
        answer=dict(answer="已读取公开规格。", citation_ids=[]),
    )
    conversation = c.create("personal")
    result = run(c, environment, conversation, save(c, conversation, "搜索公开气泵参数"))
    assert result["status"] == "answered", result
    assert reads == [URL] and len(calls) == 2
    assert len(result["citations"]) == 1
    assert "120kPa" in calls[-1].content.decode()
    assert "不可作为引用的摘要" not in calls[-1].content.decode()
    with c.scope.engine.connect() as connection:
        snap = connection.execute(select(tables.evidence_snapshots)).mappings().one()
        assert snap["taint"] == "untrusted_external"


def test_stop_during_search_prevents_page_read_and_second_model_call(
    candidate,
    factory_setup,
    monkeypatch,
    tmp_path,
):
    c = candidate
    conversation = c.create("personal")
    message = save(c, conversation, "搜索后停止")

    class Provider:
        key = "searxng"

        def search(self, *args, **kwargs):
            stopped = c.client.post(
                f"/api/conversations/{conversation['id']}/messages/{message['id']}/reply/cancel",
                headers=c.headers,
            )
            assert stopped.status_code == 200
            return SearchResult(
                "completed", [dict(url=URL, title="规格", snippet="线索")], [], "a" * 64, 0
            )

    monkeypatch.setattr(
        conversation_research, "resolve_search_provider", lambda *args, **kwargs: Provider()
    )
    environment, calls = model(
        factory_setup,
        monkeypatch,
        tmp_path,
        choice=dict(action="search", target="气泵"),
        answer=dict(answer="不应调用", citation_ids=[]),
    )
    result = run(c, environment, conversation, message)
    assert result["error_code"] == "REPLY_CANCELLED" and len(calls) == 1
    with c.scope.engine.connect() as connection:
        assert connection.execute(select(tables.evidence_snapshots)).first() is None


def test_local_miss_falls_back_to_public_search_and_reads_three_pages(
    candidate,
    factory_setup,
    monkeypatch,
    tmp_path,
):
    from app.domain import research_search

    c = candidate
    indexed(c)
    reads, searches = [], []

    class PublicProvider:
        key = "searxng"
        protocol_version = "test-search-v1"

        def __init__(self, endpoint):
            assert endpoint == "https://synthetic-search.example/search"
            self.endpoint = endpoint

        @property
        def configured(self):
            return True

        def search(self, query, **kwargs):
            searches.append(query)
            return SearchResult(
                "completed",
                [
                    dict(url=f"https://example.com/battery{number}", title="电池", snippet="线索")
                    for number in range(3)
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
            body = BODY.replace("</body>", f"<p>{url}</p></body>")
            return ReachResponse(200, body, "text/html", len(body.encode()))

    environment, calls = model(
        factory_setup,
        monkeypatch,
        tmp_path,
        choice=dict(action="search", target="电池寿命"),
        answer=dict(answer="已读取三份公开资料。", citation_ids=[]),
    )
    monkeypatch.setattr(research_search, "SearxSearchProvider", PublicProvider)
    monkeypatch.setattr(conversation_research, "PublicReachTransport", Transport)
    monkeypatch.setattr(
        conversation_research,
        "get_settings",
        lambda: SimpleNamespace(
            research_search_endpoint="https://synthetic-search.example/search",
            research_tavily_api_key=None,
            research_firecrawl_api_key=None,
        ),
    )
    conversation = c.create("product_line")
    result = run(c, environment, conversation, save(c, conversation, "搜索电池寿命"))
    assert result["status"] == "answered", result
    assert searches == ["电池寿命"] and len(calls) == 2
    assert reads == [f"https://example.com/battery{number}" for number in range(3)]
    assert len(result["citations"]) == 3


def test_stop_during_preparation_prevents_any_model_or_tool_dispatch(
    candidate,
    factory_setup,
    monkeypatch,
    tmp_path,
):
    c = candidate
    conversation = c.create("personal")
    message = save(c, conversation, "准备搜索时停止")
    environment, calls = model(
        factory_setup,
        monkeypatch,
        tmp_path,
        choice=dict(action="search", target="气泵"),
        answer=dict(answer="不应生成", citation_ids=[]),
    )

    def stop(event):
        if event.get("run_id"):
            assert (
                c.client.post(
                    f"/api/conversations/{conversation['id']}/messages/{message['id']}/reply/cancel",
                    headers=c.headers,
                ).status_code
                == 200
            )

    result = run(c, environment, conversation, message, stop)
    assert result["error_code"] == "REPLY_CANCELLED" and calls == []
    with c.scope.engine.connect() as connection:
        assert connection.execute(select(tables.agent_tool_dispatches)).first() is None
        assert connection.execute(select(tables.budget_journal)).first() is None
