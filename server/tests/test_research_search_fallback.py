"""Provider failures, local misses, cancellation and Firecrawl source validation."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.ai import firecrawl, research_search
from app.ai.reach import ReachDeniedError, ReachFetchError, ReachPolicy, ReachResponse
from app.ai.research_search import FallbackSearchProvider, SearchResult

URL = "https://example.com/spec"


def backend(key, outcome, calls):
    def search(*args, **kwargs):
        calls.append(key)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return SimpleNamespace(key=key, protocol_version="test-v1", endpoint=None, search=search)


def hit():
    return SearchResult(
        "completed", [{"url": URL, "title": "公开规格", "snippet": "线索"}], [], "a" * 64, 0
    )


def empty():
    return SearchResult("no_results", [], [], "b" * 64, 0)


@pytest.mark.parametrize("failure", [ReachFetchError("超时"), empty()])
def test_local_miss_and_tavily_failure_use_firecrawl_before_searx(failure):
    calls = []
    provider = FallbackSearchProvider(
        tuple(
            backend(key, outcome, calls)
            for key, outcome in [
                ("local-index", empty()),
                ("tavily", failure),
                ("firecrawl", hit()),
                ("searxng", hit()),
            ]
        )
    )
    value = provider.search("气泵参数", language="auto", time_range=None, limit=2)
    assert calls == ["local-index", "tavily", "firecrawl"]
    assert value.provider_key == "firecrawl" and value.providers_tried == tuple(calls)


def test_searx_is_last_resort_and_failed_coverage_is_visible():
    calls = []
    provider = FallbackSearchProvider(
        tuple(
            backend(key, outcome, calls)
            for key, outcome in [
                ("tavily", ReachFetchError("限流")),
                ("firecrawl", ReachFetchError("额度不足")),
                ("searxng", hit()),
            ]
        )
    )
    value = provider.search("规格", language="auto", time_range=None, limit=2)
    assert calls == ["tavily", "firecrawl", "searxng"]
    assert value.provider_key == "searxng" and value.status == "partial" and value.warnings


def test_failed_provider_plus_no_hits_is_unavailable_not_evidence_of_absence():
    calls = []
    provider = FallbackSearchProvider(
        (backend("tavily", ReachFetchError("失败"), calls), backend("firecrawl", empty(), calls))
    )
    assert (
        provider.search("规格", language="auto", time_range=None, limit=2).status == "unavailable"
    )


def test_policy_refusal_does_not_dispatch_another_provider():
    calls = []
    provider = FallbackSearchProvider(
        (
            backend("tavily", ReachDeniedError("internal_address", "拒绝"), calls),
            backend("firecrawl", hit(), calls),
        )
    )
    with pytest.raises(ReachDeniedError):
        provider.search("规格", language="auto", time_range=None, limit=2)
    assert calls == ["tavily"]


def test_stop_before_fallback_dispatch_keeps_second_provider_unused():
    calls = []

    def check():
        if calls:
            raise PermissionError("已停止")

    provider = FallbackSearchProvider(
        (backend("tavily", empty(), calls), backend("firecrawl", hit(), calls)), check
    )
    with pytest.raises(PermissionError, match="已停止"):
        provider.search("规格", language="auto", time_range=None, limit=2)
    assert calls == ["tavily"]


def public_policy(monkeypatch):
    def policy():
        return ReachPolicy(resolver=lambda _: ["93.184.216.34"])

    monkeypatch.setattr(firecrawl, "ReachPolicy", policy)
    monkeypatch.setattr(research_search, "ReachPolicy", policy)


def test_firecrawl_search_uses_web_leads_without_auto_scraping(monkeypatch):
    public_policy(monkeypatch)
    calls = []

    def post(self, path, headers, payload):
        calls.append((path, headers, payload))
        return 200, json.dumps(
            {
                "success": True,
                "data": {
                    "web": [
                        {"url": "http://127.0.0.1/admin"},
                        {"url": URL, "title": "规格", "description": "摘要"},
                    ]
                },
            }
        )

    monkeypatch.setattr(firecrawl.FirecrawlHttpTransport, "post", post)
    value = research_search.FirecrawlSearchProvider("test-only").search(
        "气泵", language="auto", time_range="month", limit=2
    )
    path, headers, payload = calls[0]
    assert path == "/v2/search" and headers["Authorization"] == "Bearer test-only"
    assert payload["tbs"] == "qdr:m" and "scrapeOptions" not in payload
    assert value.hits == [{"url": URL, "title": "规格", "snippet": "摘要"}]
    assert value.rejected_count == 1 and value.status == "partial"


def scrape_body(final=URL, **metadata):
    return json.dumps(
        {
            "success": True,
            "data": {
                "html": "<article>规格正文</article>",
                "metadata": {
                    "sourceURL": URL,
                    "url": final,
                    "statusCode": 200,
                    "contentType": "text/html",
                    **metadata,
                },
            },
        }
    )


def test_firecrawl_read_keeps_public_source_and_no_actions_or_llm_cleaning(monkeypatch):
    public_policy(monkeypatch)
    calls = []

    def post(self, path, headers, payload):
        calls.append((path, headers, payload))
        return 200, scrape_body()

    monkeypatch.setattr(firecrawl.FirecrawlHttpTransport, "post", post)
    check = Mock()
    result = firecrawl.FirecrawlReachTransport("test-only", before_read=check).get(URL)
    assert result.source_version == "firecrawl-scrape-v2" and "规格正文" in result.content
    assert calls[0][2]["onlyCleanContent"] is False
    assert calls[0][2]["skipTlsVerification"] is False and "actions" not in calls[0][2]
    assert check.call_count == 2


def test_firecrawl_root_trailing_slash_is_the_same_source(monkeypatch):
    public_policy(monkeypatch)
    monkeypatch.setattr(
        firecrawl.FirecrawlHttpTransport,
        "post",
        lambda *a: (200, scrape_body("https://example.com/", sourceURL="https://example.com")),
    )
    fallback = Mock()
    monkeypatch.setattr(firecrawl, "PublicReachTransport", fallback)
    assert (
        firecrawl.FirecrawlReachTransport("test-only", before_read=lambda: None)
        .get("https://example.com")
        .source_version
        == "firecrawl-scrape-v2"
    )
    fallback.assert_not_called()


def test_firecrawl_redirect_to_private_is_denied_without_direct_fallback(monkeypatch):
    public_policy(monkeypatch)
    monkeypatch.setattr(
        firecrawl.FirecrawlHttpTransport,
        "post",
        lambda *a: (200, scrape_body("http://127.0.0.1/admin")),
    )
    fallback = Mock()
    monkeypatch.setattr(firecrawl, "PublicReachTransport", fallback)
    with pytest.raises(ReachDeniedError):
        firecrawl.FirecrawlReachTransport("test-only", before_read=lambda: None).get(URL)
    fallback.assert_not_called()


@pytest.mark.parametrize(
    "outcome", [(402, "{}"), (200, scrape_body("https://example.com/other")), (200, "not-json")]
)
def test_unavailable_or_changed_firecrawl_source_uses_pinned_get(monkeypatch, outcome):
    public_policy(monkeypatch)
    monkeypatch.setattr(firecrawl.FirecrawlHttpTransport, "post", lambda *a: outcome)
    response = ReachResponse(200, "direct body", "text/plain", 11)
    fallback = Mock(return_value=SimpleNamespace(get=lambda url: response))
    monkeypatch.setattr(firecrawl, "PublicReachTransport", fallback)
    assert (
        firecrawl.FirecrawlReachTransport("test-only", before_read=lambda: None).get(URL)
        == response
    )
    fallback.assert_called_once()
