"""Search-provider outcomes; no sockets, credentials, or real service qualification."""

import hashlib
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from app.ai import research_search as module
from app.ai.reach import (
    ReachDeniedError,
    ReachFetchError,
    ReachPolicy,
    ReachResponse,
    ReachSearchUnavailableError,
)


def provider(
    monkeypatch: pytest.MonkeyPatch, payload: Any, *, status: int = 200
) -> tuple[module.SearxSearchProvider, list[str]]:
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    calls: list[str] = []

    class Transport:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def get(self, url: str) -> ReachResponse:
            calls.append(url)
            return ReachResponse(status, body, "application/json", len(body.encode()))

    monkeypatch.setattr(module, "PublicReachTransport", Transport)
    monkeypatch.setattr(
        module, "ReachPolicy", lambda: ReachPolicy(resolver=lambda _: ["93.184.216.34"])
    )
    return module.SearxSearchProvider("https://search.example.com/search"), calls


def search(value: module.SearxSearchProvider) -> module.SearchResult:
    return value.search("公开气泵 + 规格", language="zh-CN", time_range="month", limit=2)


def test_missing_service_never_looks_like_a_zero_hit_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, calls = provider(monkeypatch, {"results": []})
    value.endpoint = None
    with pytest.raises(ReachSearchUnavailableError, match="尚未配置"):
        search(value)
    assert not calls


def test_successful_zero_hits_retains_query_protocol_and_response_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"results": []}
    value, calls = provider(monkeypatch, payload)
    result = search(value)
    assert result.status == "no_results" and result.hits == [] and result.warnings == []
    assert parse_qs(urlsplit(calls[0]).query) == {
        "q": ["公开气泵 + 规格"],
        "format": ["json"],
        "categories": ["general"],
        "pageno": ["1"],
        "language": ["zh-CN"],
        "time_range": ["month"],
    }
    assert result.response_digest == hashlib.sha256(json.dumps(payload).encode()).hexdigest()


@pytest.mark.parametrize(
    "hits,expected", [([], "unavailable"), ([{"url": "https://example.com/spec"}], "partial")]
)
def test_upstream_engine_failure_is_not_reported_as_complete_or_no_results(
    monkeypatch: pytest.MonkeyPatch, hits: list[dict[str, str]], expected: str
) -> None:
    value, _ = provider(
        monkeypatch, {"results": hits, "unresponsive_engines": [["engine", "timeout"]]}
    )
    result = search(value)
    assert result.status == expected and "覆盖不完整" in result.warnings[0]


def test_unsafe_and_malformed_candidates_are_excluded_without_becoming_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, _ = provider(
        monkeypatch,
        {
            "results": [
                {"url": "http://127.0.0.1/admin"},
                {"url": "https://example.com/login"},
                {"url": "https://example.com/install.sh"},
                {"title": "missing URL"},
                {
                    "url": "https://example.com/spec",
                    "title": "公开规格",
                    "content": "未经验证的摘要",
                },
                {"url": "https://example.com/spec", "title": "重复"},
            ]
        },
    )
    result = search(value)
    assert result.status == "partial" and result.rejected_count == 4
    assert result.hits == [
        {"url": "https://example.com/spec", "title": "公开规格", "snippet": "未经验证的摘要"}
    ]


@pytest.mark.parametrize("payload", ["not json", [], {"results": None}])
def test_invalid_response_fails_instead_of_fabricating_zero_hits(
    monkeypatch: pytest.MonkeyPatch, payload: Any
) -> None:
    value, _ = provider(monkeypatch, payload)
    with pytest.raises(ReachFetchError):
        search(value)


@pytest.mark.parametrize(
    "status,error",
    [(403, ReachSearchUnavailableError), (429, ReachFetchError), (503, ReachFetchError)],
)
def test_http_failures_remain_service_failures(
    monkeypatch: pytest.MonkeyPatch, status: int, error: type[Exception]
) -> None:
    value, _ = provider(monkeypatch, {}, status=status)
    with pytest.raises(error):
        search(value)


def test_policy_denial_is_not_swallowed_as_an_empty_search(monkeypatch: pytest.MonkeyPatch) -> None:
    value, _ = provider(monkeypatch, {})

    class DeniedTransport:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def get(self, url: str) -> ReachResponse:
            raise ReachDeniedError("internal_address", "地址不可访问")

    monkeypatch.setattr(module, "PublicReachTransport", DeniedTransport)
    with pytest.raises(ReachDeniedError, match="地址不可访问"):
        search(value)
