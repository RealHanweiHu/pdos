"""Fixed-host Firecrawl API; public text only, without actions or LLM extraction."""

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from app.ai.reach import (
    ReachDeniedError,
    ReachFetchError,
    ReachPolicy,
    ReachResponse,
    ReachSearchUnavailableError,
)
from app.ai.reach_transport import PublicReachTransport
from app.ai.research_search import TavilyHttpTransport


class FirecrawlHttpTransport(TavilyHttpTransport):
    host = "api.firecrawl.dev"

    def post(
        self, path: str, headers: dict[str, str], payload: dict[str, object]
    ) -> tuple[int, str]:
        if path not in {"/v2/search", "/v2/scrape"}:
            raise ReachFetchError("Firecrawl请求路径无效")
        try:
            return super().post(path, headers, payload)
        except ReachDeniedError:
            raise
        except Exception as error:
            # Provider errors can include request headers; keep them out of receipts.
            raise ReachFetchError("Firecrawl连接失败或超时") from error


def response_body(status: int, body: str) -> dict[str, Any]:
    if status in {401, 403}:
        raise ReachFetchError("Firecrawl密钥无效或无权限，请管理员核对配置")
    if status == 402:
        raise ReachFetchError("Firecrawl额度不足")
    if status == 429:
        raise ReachFetchError("Firecrawl限流，可稍后重试")
    if status != 200:
        raise ReachFetchError(f"Firecrawl暂不可用（HTTP {status}）")
    try:
        value = json.loads(body)
    except (ValueError, TypeError) as error:
        raise ReachFetchError("Firecrawl未返回有效JSON") from error
    if not isinstance(value, dict) or value.get("success") is not True:
        raise ReachFetchError("Firecrawl未完成请求")
    return value


class FirecrawlReachTransport:
    """A remote public-page read, falling back to the existing pinned GET transport.

    Target and reported source/final URL are checked with the existing policy.
    A remote redirect is rejected: without a hop trace it cannot become evidence.
    The pinned GET fallback retains per-hop validation through ReachService.
    """

    def __init__(
        self, api_key: str, *, before_read: Callable[[], None], total_timeout: float = 20
    ) -> None:
        self.api_key = api_key
        self.before_read = before_read
        self.total_timeout = total_timeout

    def get(self, url: str) -> ReachResponse:
        policy = ReachPolicy()
        policy.assert_url_allowed(url)
        self.before_read()
        try:
            return self._scrape(url, policy)
        except (ReachFetchError, ReachSearchUnavailableError):
            self.before_read()
            return PublicReachTransport(total_timeout=self.total_timeout).get(url)

    def _scrape(self, url: str, policy: ReachPolicy) -> ReachResponse:
        status, body = FirecrawlHttpTransport().post(
            "/v2/scrape",
            {"Authorization": f"Bearer {self.api_key}"},
            {
                "url": url,
                "formats": ["html"],
                "onlyMainContent": True,
                "onlyCleanContent": False,
                "skipTlsVerification": False,
                "timeout": 15000,
                "maxAge": 0,
                "parsers": [],
            },
        )
        self.before_read()
        value = response_body(status, body)
        data = value.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("metadata"), dict):
            raise ReachFetchError("Firecrawl正文缺少来源信息")
        metadata = data["metadata"]
        source = metadata.get("sourceURL")
        final = metadata.get("url")
        if not isinstance(source, str) or not isinstance(final, str):
            raise ReachFetchError("Firecrawl未确认原页面及最终地址")
        policy.assert_url_allowed(source)
        policy.assert_url_allowed(final)

        def identity(value: str) -> tuple[str, str, str, str]:
            parsed = urlsplit(value)
            return parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query

        if identity(source) != identity(url) or identity(final) != identity(url):
            raise ReachFetchError("Firecrawl页面地址已变化，改用逐跳核对的公开读取")
        page_status = metadata.get("statusCode")
        if not isinstance(page_status, int) or not 200 <= page_status < 300:
            raise ReachFetchError("Firecrawl目标页面未成功返回")
        content = data.get("html")
        if not isinstance(content, str) or not content.strip():
            raise ReachFetchError("Firecrawl没有可读取的页面正文")
        response = ReachResponse(
            page_status,
            content,
            str(metadata.get("contentType") or "text/html"),
            len(content.encode("utf-8")),
            source_version="firecrawl-scrape-v2",
            content_language=str(metadata.get("language") or "und")[:16],
        )
        policy.assert_response_allowed(response)
        return response
