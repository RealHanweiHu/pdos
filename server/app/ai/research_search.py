"""SearXNG GET/JSON provider plus the local crawl-index provider.

Search hits are leads, never captured evidence. Both providers return the same
SearchResult contract so observations stay replayable and honest.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import UUID

from sqlalchemy import Engine, select, text

from app.ai.reach import (
    ReachDeniedError,
    ReachFetchError,
    ReachPolicy,
    ReachResponse,
    ReachSearchUnavailableError,
)
from app.ai.reach_transport import PublicReachTransport
from app.domain.research_index import segment_text


@dataclass(frozen=True)
class SearchResult:
    status: str
    hits: list[dict[str, str]]
    warnings: list[str]
    response_digest: str
    rejected_count: int
    provider_key: str | None = None
    provider_protocol_version: str | None = None
    providers_tried: tuple[str, ...] = ()


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
        response = (
            _local_searx_response(url)
            if self.endpoint == "http://127.0.0.1:8888/search"
            else PublicReachTransport(total_timeout=20).get(url)
        )
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


def _local_searx_response(url: str) -> ReachResponse:
    """Only the operator-configured loopback search service; never a model-selected URL."""
    import httpx2

    parsed = urlsplit(url)
    if (parsed.scheme, parsed.netloc, parsed.path) != ("http", "127.0.0.1:8888", "/search"):
        raise ReachDeniedError("search_endpoint_invalid", "本地搜索端点无效")
    try:
        with (
            httpx2.Client(timeout=20, trust_env=False, follow_redirects=False) as client,
            client.stream("GET", url, headers={"Accept": "application/json"}) as response,
        ):
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 2_000_000:
                    raise ReachFetchError("本地搜索响应超过读取上限")
                chunks.append(chunk)
            return ReachResponse(
                response.status_code, b"".join(chunks).decode("utf-8"), "application/json", size
            )
    except (httpx2.HTTPError, UnicodeError) as error:
        raise ReachFetchError("本地SearXNG连接失败或响应无效") from error


class LocalIndexSearchProvider:
    """PostgreSQL full-text ranking over the tenant's own crawled snapshots.

    An empty index is *not configured*, never a zero-hit success: without
    crawled documents the honest outcome is the same fail-closed 503 as the
    missing SearXNG endpoint.
    """

    key = "local-index"
    protocol_version = "local-ts-rank-v2"
    endpoint = None

    def __init__(
        self,
        engine: Engine,
        *,
        tenant_id: UUID,
        space_id: UUID | None = None,
        line_id: UUID | None = None,
    ) -> None:
        self.engine = engine
        self.tenant_id = tenant_id
        self.space_id = space_id
        self.line_id = line_id

    @property
    def configured(self) -> bool:
        from app.db.schema import tables

        filters = [
            tables.research_index_documents.c.tenant_id == self.tenant_id,
            tables.evidence_snapshots.c.superseded_by_id.is_(None),
            tables.research_sources.c.status == "active",
        ]
        if self.space_id is not None:
            filters.append(tables.research_index_documents.c.market_space_id == self.space_id)
        if self.line_id is not None:
            # A line-scoped search still sees space-level documents.
            filters.append(
                (tables.research_index_documents.c.product_line_id.is_(None))
                | (tables.research_index_documents.c.product_line_id == self.line_id)
            )
        with self.engine.connect() as connection:
            return (
                connection.execute(
                    select(1)
                    .select_from(tables.research_index_documents)
                    .join(
                        tables.evidence_snapshots,
                        (
                            tables.evidence_snapshots.c.tenant_id
                            == tables.research_index_documents.c.tenant_id
                        )
                        & (
                            tables.evidence_snapshots.c.id
                            == tables.research_index_documents.c.snapshot_id
                        ),
                    )
                    .join(
                        tables.research_sources,
                        (
                            tables.research_sources.c.tenant_id
                            == tables.research_index_documents.c.tenant_id
                        )
                        & (
                            tables.research_sources.c.id
                            == tables.research_index_documents.c.source_id
                        ),
                    )
                    .where(*filters)
                    .limit(1)
                ).first()
                is not None
            )

    def search(
        self, query: str, *, language: str, time_range: str | None, limit: int
    ) -> SearchResult:
        if not self.configured:
            raise ReachSearchUnavailableError(
                "本地研究索引尚无已采集文档，可先采集页面或启用爬虫建立索引"
            )

        segmented = segment_text(query)
        if not segmented:
            raise ReachFetchError("查询未包含可检索的词条")
        clauses = ["d.tenant_id = :tenant_id", "d.doc_tsv @@ plainto_tsquery('simple', :segmented)"]
        parameters: dict[str, object] = {
            "tenant_id": self.tenant_id,
            "segmented": segmented,
            "limit": min(limit * 4, 40),
        }
        if self.space_id is not None:
            clauses.append("d.market_space_id = :space_id")
            parameters["space_id"] = self.space_id
        if self.line_id is not None:
            clauses.append("(d.product_line_id IS NULL OR d.product_line_id = :line_id)")
            parameters["line_id"] = self.line_id
        if language != "auto":
            clauses.append("split_part(d.lang, '-', 1) = split_part(:language, '-', 1)")
            parameters["language"] = language
        if time_range:
            spans = {
                "day": timedelta(days=1),
                "month": timedelta(days=31),
                "year": timedelta(days=365),
            }
            span = spans[time_range]
            clauses.append("s.captured_at >= :since")
            parameters["since"] = datetime.now(UTC) - span
        statement = text(
            "SELECT d.url, d.title, d.extracted_text, s.id AS snapshot_id, s.captured_at "
            "FROM cehub_product.research_index_documents d "
            "JOIN cehub_evidence.evidence_snapshots s "
            "ON s.tenant_id = d.tenant_id AND s.id = d.snapshot_id "
            "JOIN cehub_evidence.research_sources rs "
            "ON rs.tenant_id = d.tenant_id AND rs.id = d.source_id AND rs.status = 'active' "
            "WHERE "
            + " AND ".join(clauses)
            + (" AND s.superseded_by_id IS NULL")
            + " ORDER BY ts_rank(d.doc_tsv, plainto_tsquery('simple', :segmented)) DESC,"
            " s.captured_at DESC, d.snapshot_id LIMIT :limit"
        )
        tokens = [part for part in segmented.split() if len(part) >= 2]
        hits: list[dict[str, str]] = []
        warnings: list[str] = []
        rejected = 0
        seen: set[str] = set()
        policy = ReachPolicy()
        with self.engine.connect() as connection:
            rows = connection.execute(statement, parameters).mappings()
            for row in rows:
                url = row["url"]
                if url in seen:
                    continue
                seen.add(url)
                try:
                    policy.assert_url_allowed(url)
                except ReachDeniedError:
                    rejected += 1
                    continue
                hits.append(
                    {
                        "title": (row["title"] or url)[:512],
                        "url": url,
                        "snippet": _snippet(row["extracted_text"], tokens),
                        "snapshot_id": str(row["snapshot_id"]),
                    }
                )
                if len(hits) >= limit:
                    break
        if rejected:
            warnings.append(f"{rejected}条候选因地址不可采集而未展示")
        digest_payload = json.dumps(hits, ensure_ascii=False, sort_keys=True)
        return SearchResult(
            ("unavailable" if rejected else "no_results")
            if not hits
            else ("partial" if warnings else "completed"),
            hits,
            warnings,
            hashlib.sha256(digest_payload.encode("utf-8")).hexdigest(),
            rejected,
        )


def _snippet(body: str, tokens: list[str], *, window: int = 96) -> str:
    for token in tokens:
        index = body.find(token)
        if index >= 0:
            start = max(0, index - window // 2)
            end = min(len(body), index + len(token) + window)
            prefix = "…" if start > 0 else ""
            suffix = "…" if end < len(body) else ""
            return f"{prefix}{body[start:end].strip()}{suffix}"[:2048]
    return body[:2048]


class TavilyHttpTransport:
    """Fixed-host POST to api.tavily.com; the key travels in a header, never the URL."""

    host = "api.tavily.com"
    timeout = 20.0
    max_body_chars = 2_000_000

    def post(
        self, path: str, headers: dict[str, str], payload: dict[str, object]
    ) -> tuple[int, str]:
        import httpx2

        try:
            with (
                httpx2.Client(timeout=self.timeout, follow_redirects=False) as client,
                client.stream(
                    "POST", f"https://{self.host}{path}", headers=headers, json=payload
                ) as response,
            ):
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > self.max_body_chars:
                        raise ReachFetchError("搜索服务响应超过读取上限")
                    chunks.append(chunk)
                return response.status_code, b"".join(chunks).decode("utf-8")
        except (httpx2.HTTPError, UnicodeError) as error:
            raise ReachFetchError(f"{self.host}连接失败或响应无效") from error


class TavilySearchProvider:
    """Tavily web search; results are leads and each URL is re-vetted by reach policy."""

    key = "tavily"
    protocol_version = "search-tavily-v1"
    endpoint = "https://api.tavily.com/search"

    def __init__(self, api_key: str | None) -> None:
        self.api_key = api_key

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def search(
        self, query: str, *, language: str, time_range: str | None, limit: int
    ) -> SearchResult:
        if not self.configured:
            raise ReachSearchUnavailableError("Tavily 搜索密钥尚未配置")
        payload: dict[str, object] = {
            "query": query,
            "max_results": min(max(limit * 4, 10), 20),
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
        }
        if time_range:
            payload["time_range"] = time_range
        status, body = TavilyHttpTransport().post(
            "/search",
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            payload,
        )
        if status in {401, 403}:
            raise ReachFetchError("Tavily 密钥无效或无权限，请管理员核对配置")
        if status == 429:
            raise ReachFetchError("Tavily 搜索限流，可稍后重试")
        if status != 200:
            raise ReachFetchError(f"Tavily 搜索暂不可用（HTTP {status}）")
        try:
            parsed = json.loads(body)
        except (ValueError, TypeError) as error:
            raise ReachFetchError("Tavily 搜索未返回有效JSON结果") from error
        raw_results = parsed.get("results") if isinstance(parsed, dict) else None
        if not isinstance(raw_results, list):
            raise ReachFetchError("Tavily 搜索结果缺少有效结果列表")
        hits: list[dict[str, str]] = []
        warnings: list[str] = []
        rejected = 0
        seen: set[str] = set()
        policy = ReachPolicy()
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
        return SearchResult(
            ("unavailable" if rejected else "no_results")
            if not hits
            else ("partial" if warnings else "completed"),
            hits,
            warnings,
            hashlib.sha256(body.encode("utf-8")).hexdigest(),
            rejected,
        )


class FirecrawlSearchProvider:
    key = "firecrawl"
    protocol_version = "search-firecrawl-v2"
    endpoint = "https://api.firecrawl.dev/v2/search"

    def __init__(self, api_key: str | None) -> None:
        self.api_key = api_key

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def search(
        self, query: str, *, language: str, time_range: str | None, limit: int
    ) -> SearchResult:
        from app.ai.firecrawl import FirecrawlHttpTransport, response_body

        if not self.api_key:
            raise ReachSearchUnavailableError("Firecrawl搜索密钥尚未配置")
        payload: dict[str, object] = {
            "query": query,
            "limit": min(max(limit * 4, 10), 20),
            "sources": ["web"],
            "timeout": 15000,
        }
        if time_range:
            payload["tbs"] = {"day": "qdr:d", "month": "qdr:m", "year": "qdr:y"}[time_range]
        status, body = FirecrawlHttpTransport().post(
            "/v2/search", {"Authorization": f"Bearer {self.api_key}"}, payload
        )
        parsed = response_body(status, body)
        data = parsed.get("data")
        results = data.get("web") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise ReachFetchError("Firecrawl搜索结果缺少有效网页列表")
        policy, seen = ReachPolicy(), set()
        hits: list[dict[str, str]] = []
        rejected = 0
        for item in results[:40]:
            if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                rejected += 1
                continue
            url = item["url"]
            if url in seen:
                continue
            seen.add(url)
            try:
                if len(url) > 1024:
                    raise ReachDeniedError("url_too_long", "页面地址过长")
                policy.assert_url_allowed(url)
            except ReachDeniedError:
                rejected += 1
                continue
            hits.append(
                {
                    "title": str(item.get("title") or url)[:512],
                    "url": url,
                    "snippet": str(item.get("description") or "")[:2048],
                }
            )
            if len(hits) >= limit:
                break
        warnings = [f"{rejected}条候选因地址不可采集或格式不完整而未展示"] if rejected else []
        return SearchResult(
            ("unavailable" if rejected else "no_results")
            if not hits
            else ("partial" if warnings else "completed"),
            hits,
            warnings,
            hashlib.sha256(body.encode("utf-8")).hexdigest(),
            rejected,
        )


SearchBackend = (
    LocalIndexSearchProvider | TavilySearchProvider | FirecrawlSearchProvider | SearxSearchProvider
)


class FallbackSearchProvider:
    """Bounded ordered search; a policy refusal never authorizes another dispatch."""

    def __init__(
        self, providers: tuple[SearchBackend, ...], before_attempt: Callable[[], None] | None = None
    ) -> None:
        self.providers = providers
        self.before_attempt = before_attempt
        self.key = providers[0].key
        self.protocol_version = "search-fallback-v1"
        self.endpoint = providers[0].endpoint

    @property
    def configured(self) -> bool:
        return bool(self.providers)

    def search(
        self, query: str, *, language: str, time_range: str | None, limit: int
    ) -> SearchResult:
        warnings: list[str] = []
        tried: list[str] = []
        last: SearchResult | None = None
        failed = False
        for provider in self.providers:
            if self.before_attempt:
                self.before_attempt()
            tried.append(provider.key)
            try:
                result = provider.search(
                    query, language=language, time_range=time_range, limit=limit
                )
            except (ReachFetchError, ReachSearchUnavailableError):
                failed = True
                warnings.append(f"{provider.key}暂不可用，已尝试备用搜索")
                continue
            last = replace(
                result,
                provider_key=provider.key,
                provider_protocol_version=provider.protocol_version,
                providers_tried=tuple(tried),
            )
            if result.hits:
                return replace(
                    last,
                    status="partial" if warnings or result.warnings else result.status,
                    warnings=[*warnings, *result.warnings],
                )
            failed = failed or result.status not in {"completed", "no_results"}
            warnings.extend(result.warnings)
        if last is None:
            raise ReachFetchError("已配置的搜索服务均暂不可用，请稍后重试")
        return replace(
            last,
            status="unavailable" if failed else "no_results",
            warnings=warnings,
            providers_tried=tuple(tried),
        )
