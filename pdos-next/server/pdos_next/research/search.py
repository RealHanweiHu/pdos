"""Server-configured Searx adapter; no credentials or proxies inherited from the environment."""

import json
from urllib.parse import urlsplit

import httpx

from .types import SearchHit
from .web import ResearchError


class SearxSearchAdapter:
    def __init__(
        self,
        endpoint: str,
        *,
        provider: str,
        headers=None,
        transport=None,
        timeout=20,
        max_response_bytes=2 * 1024 * 1024,
    ):
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("Search endpoint must be configured by the server")
        if not provider or timeout <= 0 or max_response_bytes <= 0:
            raise ValueError("Search provider and resource budgets are required")
        self.endpoint, self.provider = endpoint, provider
        self._headers, self._transport = dict(headers or {}), transport
        self._headers.setdefault("Accept-Encoding", "identity")
        self.timeout, self.max_response_bytes = timeout, max_response_bytes

    async def search(self, query: str) -> tuple[SearchHit, ...]:
        async with httpx.AsyncClient(
            transport=self._transport,
            trust_env=False,
            follow_redirects=False,
            timeout=self.timeout,
            headers=self._headers,
        ) as client:
            try:
                async with client.stream(
                    "GET", self.endpoint, params={"q": query, "format": "json"}
                ) as response:
                    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                        raise ResearchError(
                            "search_encoding_unsupported",
                            "Search compressed response requires bounded decoding",
                            provider=self.provider,
                        )
                    chunks, size = [], 0

                    async def raw_chunks():
                        # A trusted in-process transport may return an already materialized body.
                        if response.is_stream_consumed:
                            yield response.content
                        else:
                            async for chunk in response.aiter_raw():
                                yield chunk

                    async for chunk in raw_chunks():
                        size += len(chunk)
                        if size > self.max_response_bytes:
                            raise ResearchError(
                                "search_body_limit",
                                "Search result exceeds its byte budget",
                                provider=self.provider,
                            )
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    if not 200 <= response.status_code < 300:
                        raise ResearchError(
                            "search_http_error",
                            content.decode("utf-8", errors="replace")
                            or f"Search returned HTTP {response.status_code}",
                            provider=self.provider,
                            http_status=response.status_code,
                            request_id=response.headers.get("X-Request-ID"),
                            retry_after=response.headers.get("Retry-After"),
                        )
            except httpx.HTTPError as exc:
                raise ResearchError(
                    "search_connection_failed",
                    "Search HTTP connection failed",
                    provider=self.provider,
                ) from exc
        try:
            decoded = json.loads(content)
            results = decoded["results"]
            if not isinstance(results, list):
                raise ValueError("results")
            hits = tuple(
                SearchHit(
                    result["url"], result.get("title", ""), result.get("content", ""), self.provider
                )
                for result in results
            )
            if any(
                not all(isinstance(value, str) for value in (hit.url, hit.title, hit.summary))
                for hit in hits
            ):
                raise ValueError("metadata")
            return hits
        except (ValueError, TypeError, KeyError) as exc:
            raise ResearchError(
                "invalid_search_result",
                "Search service returned invalid JSON metadata",
                provider=self.provider,
            ) from exc
