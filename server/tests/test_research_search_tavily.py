"""Tavily provider outcomes and chain resolution; no sockets, no real key use."""

import json
from typing import Any

import pytest

from app.ai import research_search as module
from app.ai.reach import (
    ReachDeniedError,
    ReachFetchError,
    ReachPolicy,
    ReachSearchUnavailableError,
)


def provider(
    monkeypatch: pytest.MonkeyPatch, payload: Any, *, status: int = 200
) -> tuple[module.TavilySearchProvider, list[tuple[str, dict[str, str], dict[str, Any]]]]:
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    calls: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    class Transport:
        def post(
            self, path: str, headers: dict[str, str], payload: dict[str, Any]
        ) -> tuple[int, str]:
            calls.append((path, headers, dict(payload)))
            return status, body

    monkeypatch.setattr(module, "TavilyHttpTransport", Transport)
    monkeypatch.setattr(
        module, "ReachPolicy", lambda: ReachPolicy(resolver=lambda _: ["93.184.216.34"])
    )
    return module.TavilySearchProvider("tvly-test-only"), calls


def search(value: module.TavilySearchProvider) -> module.SearchResult:
    return value.search("车载气泵 峰值压力", language="auto", time_range="month", limit=2)


def test_missing_key_never_looks_like_a_zero_hit_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, calls = provider(monkeypatch, {"results": []})
    value.api_key = None
    with pytest.raises(ReachSearchUnavailableError, match="尚未配置"):
        search(value)
    assert not calls


def test_successful_search_sends_bearer_key_and_keeps_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "results": [
            {
                "url": "https://example.com/spec",
                "title": "公开规格",
                "content": "未经验证的摘要",
            }
        ]
    }
    value, calls = provider(monkeypatch, payload)
    result = search(value)
    path, headers, sent = calls[0]
    assert path == "/search"
    assert headers["Authorization"] == "Bearer tvly-test-only"
    assert sent["query"] == "车载气泵 峰值压力"
    assert sent["time_range"] == "month"
    assert sent["include_answer"] is False
    assert result.status == "completed"
    assert result.hits == [
        {"url": "https://example.com/spec", "title": "公开规格", "snippet": "未经验证的摘要"}
    ]
    assert result.rejected_count == 0


def test_zero_hits_stay_an_honest_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    value, _ = provider(monkeypatch, {"results": []})
    result = search(value)
    assert result.status == "no_results" and result.hits == []


def test_unsafe_and_malformed_candidates_are_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    value, _ = provider(
        monkeypatch,
        {
            "results": [
                {"url": "http://127.0.0.1/admin"},
                {"url": "https://example.com/login"},
                {"title": "missing URL"},
                {"url": "https://example.com/spec", "title": "公开规格", "content": "摘要"},
                {"url": "https://example.com/spec", "title": "重复"},
            ]
        },
    )
    result = search(value)
    assert result.status == "partial" and result.rejected_count == 3
    assert [hit["url"] for hit in result.hits] == ["https://example.com/spec"]


@pytest.mark.parametrize("payload", ["not json", [], {"results": None}])
def test_invalid_response_fails_instead_of_fabricating_zero_hits(
    monkeypatch: pytest.MonkeyPatch, payload: Any
) -> None:
    value, _ = provider(monkeypatch, payload)
    with pytest.raises(ReachFetchError):
        search(value)


@pytest.mark.parametrize(
    "status,message",
    [(401, "密钥无效"), (403, "密钥无效"), (429, "限流"), (503, "暂不可用")],
)
def test_http_failures_stay_service_failures(
    monkeypatch: pytest.MonkeyPatch, status: int, message: str
) -> None:
    value, _ = provider(monkeypatch, {}, status=status)
    with pytest.raises(ReachFetchError, match=message):
        search(value)


def test_policy_denial_on_transport_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _ = provider(monkeypatch, {"results": []})

    class DeniedTransport:
        def post(
            self, path: str, headers: dict[str, str], payload: dict[str, Any]
        ) -> tuple[int, str]:
            raise ReachDeniedError("internal_address", "地址不可访问")

    monkeypatch.setattr(module, "TavilyHttpTransport", DeniedTransport)
    with pytest.raises(ReachDeniedError, match="地址不可访问"):
        search(value)


def test_resolver_prefers_local_then_tavily_then_searxng(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain import research_search as domain_module

    monkeypatch.setattr(
        domain_module.LocalIndexSearchProvider, "configured", property(lambda self: True)
    )
    resolved = domain_module.resolve_search_provider(
        None,
        endpoint="https://searx.example/search",
        tenant_id=None,  # type: ignore[arg-type]
    )
    assert isinstance(resolved, domain_module.FallbackSearchProvider)
    assert [item.key for item in resolved.providers] == ["local-index", "searxng"]

    monkeypatch.setattr(
        domain_module.LocalIndexSearchProvider, "configured", property(lambda self: False)
    )
    resolved = domain_module.resolve_search_provider(
        None,  # type: ignore[arg-type]
        endpoint="https://searx.example/search",
        tenant_id=None,
        tavily_api_key="tvly-test-only",
    )
    assert isinstance(resolved, domain_module.FallbackSearchProvider)
    assert [item.key for item in resolved.providers] == ["tavily", "searxng"]
    resolved = domain_module.resolve_search_provider(
        None,
        endpoint="https://searx.example/search",
        tenant_id=None,  # type: ignore[arg-type]
    )
    assert isinstance(resolved, domain_module.SearxSearchProvider)
