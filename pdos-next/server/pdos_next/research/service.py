"""Search/read isolation, server-bound egress and deterministic research ledgers."""

import asyncio
import hashlib
import inspect
import re
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from pydantic import ValidationError

from pdos_next.agent_kernel.types import RunScope
from pdos_next.errors import DomainError

from .pdf import ContainerPDFAdapter
from .types import (
    Coverage,
    FanoutResult,
    LedgerDraft,
    LedgerRow,
    ParsedDocument,
    ReadPage,
    ReadTrace,
    ResearchFailure,
    ResearchTask,
    SearchHit,
    SearchTrace,
    Snapshot,
    SnapshotReference,
    UnreadLocation,
)
from .web import (
    SHARED_HOST_LIMITER,
    HostRateLimiter,
    PinnedHTTPTransport,
    ResearchError,
    ResourceLimits,
    canonical_url,
    extract_markdown,
    public_ip,
    resolve_public,
)


async def _invoke(callback, *args):
    result = callback(*args)
    return await result if inspect.isawaitable(result) else result


def safe_error(value: str) -> str:
    """Retain original service wording while removing credential-shaped fields."""
    value = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [redacted]", str(value))
    value = re.sub(
        r"(?i)\b(api[_-]?key|token|password|secret|authorization)\b"
        r"[\"']?\s*[=:]\s*[\"']?[^\s,;\"'}]+",
        r"\1=[redacted]",
        value,
    )
    value = re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1[redacted]@", value)
    return re.sub(r"[\x00-\x08\x0b-\x1f]", "", value)[:1000]


def _scope_key(scope):
    return scope.tenant_id, scope.requester_id, scope.session_id, scope.run_id


def _failure(task, stage, exc, *, url=None, provider=None):
    if isinstance(exc, DomainError):
        if exc.code == "CANCELLED_RUN":
            raise exc
        return ResearchFailure(task, stage, exc.code, safe_error(exc.message), url, provider)
    if isinstance(exc, ResearchError):
        return ResearchFailure(
            task,
            stage,
            exc.reason,
            safe_error(exc.message),
            url,
            exc.provider or provider,
            exc.http_status,
            exc.service_code,
            exc.request_id,
            exc.retry_after,
        )
    return ResearchFailure(task, stage, "researcher_failed", "Research child failed", url, provider)


class ResearchService:
    """Ports are injected by the trusted host; no environment search key is loaded here."""

    def __init__(
        self,
        search_adapter,
        *,
        egress: Callable,
        transport=None,
        resolver=resolve_public,
        snapshot_sink=None,
        credibility=None,
        pdf_parser=None,
        limits=None,
        rate_limiter: HostRateLimiter = SHARED_HOST_LIMITER,
    ):
        if not egress or not getattr(search_adapter, "provider", None):
            raise ValueError("Trusted egress policy and named search adapter are required")
        self.search_adapter, self.egress = search_adapter, egress
        self.transport, self.resolver = transport or PinnedHTTPTransport(), resolver
        self.snapshot_sink, self.credibility = snapshot_sink, credibility
        self.limits, self.rate_limiter = limits or ResourceLimits(), rate_limiter
        self.pdf_parser = pdf_parser or ContainerPDFAdapter(limits=self.limits)
        self._allowlists, self._snapshots, self._inflight = {}, {}, {}
        self._lock = threading.RLock()

    def register_user_message(self, scope: RunScope, message: str):
        """Only the host calls this on the actual user message, never model arguments."""
        urls = set()
        for found in re.findall(r"https?://[^\s<>\"']+", message):
            try:
                urls.add(canonical_url(found.rstrip(".,;!。；，！")))
            except ResearchError:
                continue
        with self._lock:
            self._allowlists.setdefault(_scope_key(scope), set()).update(urls)
        return tuple(sorted(urls))

    def forget(self, scope: RunScope):
        """End a round's URL grants and in-memory text cache; persisted snapshots belong to host."""
        key = _scope_key(scope)
        with self._lock:
            self._allowlists.pop(key, None)
            for cached in tuple(self._snapshots):
                if cached[0] == key:
                    del self._snapshots[cached]

    async def _egress(self, scope, provider, text):
        # Data categories and identity bindings are immutable Run facts, not tool parameters.
        result = await _invoke(self.egress, scope, provider, scope.data_categories, text)
        if result is False:
            raise DomainError(
                "FORBIDDEN_SCOPE",
                "出站政策拒绝该查询。",
                detail={"reason_key": "provider_data_agreement"},
            )

    async def search(self, scope: RunScope, query: str) -> tuple[SearchHit, ...]:
        if scope.isolation not in {"main", "research"}:
            raise DomainError("FORBIDDEN_SCOPE", "该隔离任务没有公开研究工具。")
        if not isinstance(query, str) or not query.strip():
            raise DomainError("VALIDATION_FAILED", "研究查询不能为空。")
        provider = self.search_adapter.provider
        await self._egress(scope, provider, query)
        try:
            hits = await asyncio.wait_for(
                _invoke(self.search_adapter.search, query), self.limits.timeout_seconds
            )
        except TimeoutError as exc:
            raise ResearchError(
                "search_timeout", "Search exceeded its time budget", provider=provider
            ) from exc
        except ResearchError as exc:
            # Adapter errors remain original safe errors for both main and child callers.
            exc.message = safe_error(exc.message)
            exc.args = (exc.message,)
            raise
        accepted = []
        for hit in hits:
            if not isinstance(hit, SearchHit):
                raise ResearchError(
                    "invalid_search_result", "Search adapter returned invalid metadata"
                )
            try:
                url = canonical_url(hit.url)
            except ResearchError:
                continue
            accepted.append(replace(hit, url=url, provider=provider))
        with self._lock:
            self._allowlists.setdefault(_scope_key(scope), set()).update(h.url for h in accepted)
        return tuple(accepted)

    async def read(self, scope: RunScope, url: str, *, cursor=0) -> ReadPage:
        if scope.isolation != "research":
            raise DomainError(
                "FORBIDDEN_SCOPE",
                "网页原文只能在隔离研究子任务读取。",
                detail={"reason_key": "isolated_subtask_only"},
            )
        url = canonical_url(url)
        key = _scope_key(scope)
        with self._lock:
            if url not in self._allowlists.get(key, set()):
                raise DomainError(
                    "FORBIDDEN_SCOPE",
                    "网址须来自本轮搜索或用户消息。",
                    detail={"reason_key": "url_not_observed"},
                )
            snapshot = self._snapshots.get((key, url))
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise DomainError("VALIDATION_FAILED", "读取游标无效。")
        if snapshot is None:
            cache_key = key, url
            with self._lock:
                snapshot = self._snapshots.get(cache_key)
                if snapshot is not None:
                    future, owner = Future(), False
                    future.set_result(snapshot)
                else:
                    future = self._inflight.get(cache_key)
                    owner = future is None
                    if owner:
                        future = self._inflight[cache_key] = Future()
            if owner:
                try:
                    try:
                        snapshot = await asyncio.wait_for(
                            self._fetch(scope, url), timeout=self.limits.timeout_seconds
                        )
                    except TimeoutError as exc:
                        raise ResearchError(
                            "read_timeout", "Public read exceeded its time budget"
                        ) from exc
                    with self._lock:
                        snapshot = self._snapshots.setdefault(cache_key, snapshot)
                    future.set_result(snapshot)
                except BaseException as exc:
                    future.set_exception(exc)
                    raise
                finally:
                    with self._lock:
                        self._inflight.pop(cache_key, None)
            else:
                # Each waiter has its own event loop; cancelling it must not cancel the shared read.
                snapshot = await asyncio.shield(asyncio.wrap_future(future))
        if cursor > len(snapshot.markdown):
            raise DomainError("VALIDATION_FAILED", "读取游标超出快照正文。")
        end = min(cursor + self.limits.page_chars, len(snapshot.markdown))
        return ReadPage(
            snapshot,
            f"chars:{cursor}:{end}",
            snapshot.markdown[cursor:end],
            end if end < len(snapshot.markdown) else None,
        )

    async def _fetch(self, scope, requested_url):
        current = requested_url
        for hop in range(self.limits.redirects + 1):
            current = canonical_url(current)
            host = urlsplit(current).hostname
            provider = f"public-web:{host}"
            # Even DNS is a network disclosure; policy must precede it.
            await self._egress(scope, provider, current)
            addresses = await _invoke(self.resolver, host)
            addresses = tuple(dict.fromkeys(public_ip(value) for value in addresses))
            if not addresses:
                raise ResearchError(
                    "dns_failed", "Public hostname resolution returned no addresses"
                )
            await self.rate_limiter.wait(host, self.limits.timeout_seconds)
            response = await _invoke(self.transport.request, current, addresses[0], self.limits)
            if 300 <= response.status < 400:
                location = response.header("Location")
                if not location:
                    raise ResearchError(
                        "redirect_missing_location", "Public redirect has no destination"
                    )
                if hop == self.limits.redirects:
                    raise ResearchError("redirect_limit", "Public read exceeds its redirect budget")
                current = urljoin(current, location)
                continue
            if response.status in {429, 503}:
                self.rate_limiter.defer(host, response.header("Retry-After"))
            if not 200 <= response.status < 300:
                message = response.service_error or (
                    response.body.decode("utf-8", errors="replace").strip()
                    or f"Public read returned HTTP {response.status}"
                )
                raise ResearchError(
                    "http_error",
                    safe_error(message),
                    provider=provider,
                    http_status=response.status,
                    service_code=response.service_code,
                    request_id=safe_error(response.header("X-Request-ID") or "") or None,
                    retry_after=response.header("Retry-After"),
                )
            is_pdf = (
                response.body.startswith(b"%PDF-")
                or "application/pdf" in (response.header("Content-Type") or "").lower()
            )
            status = "ok"
            if is_pdf and self.pdf_parser:
                if len(response.body) > self.limits.max_body_bytes:
                    raise ResearchError("body_limit", "Public response exceeds the byte budget")
                document = await _invoke(self.pdf_parser, scope, response.body, current)
                if not isinstance(document, ParsedDocument) or (
                    not document.markdown and document.status != "partial"
                ):
                    raise ResearchError(
                        "invalid_parser_result", "Isolated PDF parser returned no text"
                    )
                if len(document.markdown) > self.limits.max_markdown_chars:
                    raise ResearchError("markdown_limit", "Parsed PDF exceeds the character budget")
                title, markdown, status = document.title, document.markdown, document.status
            else:
                title, markdown = extract_markdown(response, self.limits)
            credibility = (
                await _invoke(self.credibility, current)
                if self.credibility
                else "unverified_public_page"
            )
            snapshot = Snapshot(
                uuid4(),
                requested_url,
                current,
                title,
                markdown[:280],
                datetime.now(UTC),
                markdown,
                hashlib.sha256(markdown.encode()).hexdigest(),
                provider,
                credibility,
                status,
            )
            if self.snapshot_sink:
                await _invoke(self.snapshot_sink, scope, snapshot)
            return snapshot
        raise AssertionError("Redirect loop must return or fail")

    async def fanout(
        self, scope: RunScope, tasks: Sequence[ResearchTask], researcher, *, job_id=None
    ) -> FanoutResult:
        if scope.isolation != "main":
            raise DomainError("FORBIDDEN_SCOPE", "隔离研究子任务不能再次派发子任务。")
        if not all(isinstance(task, ResearchTask) for task in tasks):
            raise DomainError("VALIDATION_FAILED", "研究任务须使用登记结构。")
        if len({task.key for task in tasks}) != len(tasks):
            raise DomainError("VALIDATION_FAILED", "研究任务键重复。")
        semaphore = asyncio.Semaphore(self.limits.concurrency)
        job_id = job_id or uuid4()

        async def run(task):
            async with semaphore:
                child = ResearchChild(self, scope.child("research"), task, job_id=job_id)
                rejected, rows = 0, []
                try:
                    drafts = await _invoke(researcher, task, child)
                    for raw in drafts:
                        try:
                            draft = LedgerDraft.model_validate(raw)
                            row = child.verify(draft)
                            rows.append(row)
                        except ValidationError:
                            rejected += 1
                            child.failures.append(
                                ResearchFailure(
                                    task.key,
                                    "citation",
                                    "invalid_ledger_row",
                                    "Extraction row failed its schema",
                                )
                            )
                        except ResearchError as exc:
                            rejected += 1
                            child.failures.append(_failure(task.key, "citation", exc))
                except Exception as exc:
                    failure = _failure(task.key, "child", exc)
                    if not any(
                        f.reason == failure.reason and f.message == failure.message
                        for f in child.failures
                    ):
                        child.failures.append(failure)
                if not child.pages:
                    child.failures.append(
                        ResearchFailure(
                            task.key,
                            "coverage",
                            "no_sources_read",
                            "No public source was successfully read",
                        )
                    )
                urls = {url for trace in child.searches for url in trace.urls}
                read_urls = {trace.url for trace in child.reads if trace.error is None}
                coverage = Coverage(
                    task.key,
                    tuple(child.searches),
                    tuple(child.reads),
                    tuple(sorted(urls - read_urls)),
                    child.unread_locations(),
                    len(rows),
                    rejected,
                )
                snapshots = {
                    page.snapshot.id: SnapshotReference(
                        page.snapshot.id,
                        page.snapshot.url,
                        page.snapshot.final_url,
                        page.snapshot.title,
                        page.snapshot.content_hash,
                        page.snapshot.retrieved_at,
                        page.snapshot.provider,
                        page.snapshot.status,
                    )
                    for page in child.pages.values()
                }
                return tuple(rows), coverage, tuple(child.failures), tuple(snapshots.values())

        results = await asyncio.gather(*(run(task) for task in tasks))
        rows = tuple(row for result in results for row in result[0])
        coverage = tuple(result[1] for result in results)
        failures = tuple(failure for result in results for failure in result[2])
        snapshots = {s.id: s for result in results for s in result[3]}
        incomplete = (
            failures
            or any(c.unread_urls or c.unread_locations for c in coverage)
            or any(row.status != "ok" for row in rows)
            or any(snapshot.status != "ok" for snapshot in snapshots.values())
        )
        status = "partial" if incomplete else "completed"
        if not rows:
            status = "unavailable"
        return FanoutResult(job_id, status, rows, coverage, failures, tuple(snapshots.values()))


class ResearchChild:
    """The child API has only search/read; raw source text never enters FanoutResult."""

    __slots__ = ("_service", "_scope", "task", "job_id", "searches", "reads", "pages", "failures")
    tool_names = frozenset({"research.search", "research.read"})

    def __init__(self, service, scope, task, *, job_id=None):
        self._service, self._scope, self.task = service, scope, task
        self.job_id = job_id
        self.searches, self.reads, self.pages, self.failures = [], [], {}, []

    async def search(self, query):
        provider = self._service.search_adapter.provider
        try:
            hits = await self._service.search(self._scope, query)
            self.searches.append(SearchTrace(query, provider, tuple(h.url for h in hits)))
            return hits
        except Exception as exc:
            failure = _failure(self.task.key, "search", exc, provider=provider)
            self.searches.append(SearchTrace(query, provider, (), failure))
            self.failures.append(failure)
            raise

    async def read(self, url, *, cursor=0):
        try:
            page = await self._service.read(self._scope, url, cursor=cursor)
            self.pages[(page.snapshot.id, page.locator)] = page
            self.reads.append(ReadTrace(page.snapshot.url, page.snapshot.id, page.locator))
            return page
        except Exception as exc:
            failure = _failure(self.task.key, "read", exc, url=url)
            self.reads.append(ReadTrace(url, None, None, failure))
            self.failures.append(failure)
            raise

    def verify(self, draft):
        page = self.pages.get((draft.snapshot_id, draft.locator))
        if page is None:
            raise ResearchError("snapshot_not_read", "Citation does not reference a read location")
        if draft.quote not in page.markdown:
            raise ResearchError("quote_not_in_snapshot", "Quote is not an exact source substring")
        if draft.parameter_id is not None and not any(
            binding.parameter_id == draft.parameter_id
            and binding.version == draft.parameter_version
            for binding in self.task.parameters
        ):
            raise ResearchError(
                "parameter_version_not_bound", "Parameter version was not server supplied"
            )
        complete = (
            bool(draft.brand or self.task.brand) and bool(draft.model) and draft.value is not None
        )
        return LedgerRow(
            uuid4(),
            self.task.key,
            draft.brand or self.task.brand,
            draft.model,
            draft.parameter_id,
            draft.parameter_version,
            draft.free_key,
            draft.value,
            draft.unit,
            draft.condition,
            draft.quote,
            draft.snapshot_id,
            page.snapshot.final_url,
            draft.locator,
            "ok" if complete else "partial",
            None if complete else "Observation is missing identifying or value fields",
        )

    def unread_locations(self):
        by_snapshot = {}
        for page in self.pages.values():
            _, start, end = page.locator.split(":")
            snapshot, ranges = by_snapshot.setdefault(page.snapshot.id, (page.snapshot, []))
            ranges.append((int(start), int(end)))
        unread = []
        for snapshot, ranges in by_snapshot.values():
            cursor = 0
            for start, end in sorted(ranges):
                if start > cursor:
                    unread.append(
                        UnreadLocation(snapshot.id, snapshot.final_url, f"chars:{cursor}:{start}")
                    )
                cursor = max(cursor, end)
            if cursor < len(snapshot.markdown):
                unread.append(
                    UnreadLocation(
                        snapshot.id, snapshot.final_url, f"chars:{cursor}:{len(snapshot.markdown)}"
                    )
                )
        return tuple(unread)
