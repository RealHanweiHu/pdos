"""SearXNG GET/JSON provider. Search hits are leads, never captured evidence.

Protocol: https://docs.searxng.org/dev/search_api.html
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit, urlunsplit

from app.ai.reach import ReachDeniedError, ReachFetchError, ReachPolicy, ReachSearchUnavailableError
from app.ai.reach_transport import PublicReachTransport


@dataclass(frozen=True)
class SearchResult:
    status: str
    hits: list[dict[str, str]]
    warnings: list[str]
    response_digest: str
    rejected_count: int


class SearxSearchProvider:
    key = "searxng"
    protocol_version = "search-json-v1"

    def __init__(self, endpoint: str | None) -> None:
        self.endpoint = endpoint

    @property
    def configured(self) -> bool:
        return bool(self.endpoint)

    def search(
        self, query: str, *, language: str, time_range: str | None, limit: int
    ) -> SearchResult:
        if not self.endpoint:
            raise ReachSearchUnavailableError("尚未配置研究搜索服务；可直接采集已知公开页面")
        parsed = urlsplit(self.endpoint)
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ReachSearchUnavailableError("研究搜索服务配置无效，请管理员检查端点")
        query_params = {"q": query, "format": "json", "categories": "general", "pageno": "1"}
        if language != "auto":
            query_params["language"] = language
        if time_range:
            query_params["time_range"] = time_range
        url = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path or "/search", urlencode(query_params), "")
        )
        response = PublicReachTransport(total_timeout=20).get(url)
        if response.status_code == 403:
            raise ReachSearchUnavailableError("搜索服务拒绝JSON输出，请管理员检查SearXNG格式配置")
        if response.status_code != 200:
            raise ReachFetchError(f"研究搜索服务暂不可用（HTTP {response.status_code}）")
        try:
            payload = json.loads(response.content)
        except (ValueError, TypeError) as error:
            raise ReachFetchError("研究搜索服务未返回有效JSON结果") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise ReachFetchError("研究搜索结果缺少有效结果列表")
        raw_results = payload["results"]
        warnings: list[str] = []
        if payload.get("unresponsive_engines"):
            warnings.append("部分上游搜索引擎未响应，本次覆盖不完整")
        policy = ReachPolicy()
        hits: list[dict[str, str]] = []
        rejected = 0
        seen: set[str] = set()
        # Bound candidate validation independently of what the provider returns.
        for item in raw_results[:40]:
            if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                rejected += 1
                continue
            url = item["url"]
            if url in seen:
                continue
            seen.add(url)
            if len(url) > 1024:
                rejected += 1
                continue
            try:
                policy.assert_url_allowed(url)
            except ReachDeniedError:
                rejected += 1
                continue
            hits.append(
                {
                    "title": str(item.get("title") or url)[:512],
                    "url": url,
                    "snippet": str(item.get("content") or "")[:2048],
                }
            )
            if len(hits) >= limit:
                break
        if rejected:
            warnings.append(f"{rejected}条候选因地址不可采集或格式不完整而未展示")
        if not hits:
            status = "unavailable" if warnings else "no_results"
        else:
            status = "partial" if warnings else "completed"
        return SearchResult(
            status,
            hits,
            warnings,
            hashlib.sha256(response.content.encode("utf-8")).hexdigest(),
            rejected,
        )
