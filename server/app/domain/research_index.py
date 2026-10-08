"""Deterministic page extraction, robots parsing and the derived research index.

Search over crawled snapshots is a projection, never a second copy of evidence:
`evidence_snapshots` stays immutable and this module rebuilds
`research_index_documents` from captured bodies whenever needed. Everything here
is stdlib-only and runs without model calls on every path.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import UUID

from sqlalchemy import Connection, Engine, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.ai.reach import ReachDeniedError, ReachPolicy
from app.db.schema import tables

MAX_EXTRACTED_CHARS = 200_000
MAX_LINKS_PER_PAGE = 200
ROBOTS_TTL_HOURS = 24
_WHITESPACE = re.compile(r"\s+")
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "iframe"})
_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_BLOCK_TAGS = frozenset(
    {"p", "div", "section", "article", "main", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "br"}
)
_BOILERPLATE = re.compile(
    r"(?:^|[\s_-])(?:cookie|consent|newsletter|popup|navigation|site-header|site-footer)(?:$|[\s_-])",
    re.I,
)
_OUR_AGENTS = ("*", "pdos-research")


def normalize_url(url: str) -> str:
    """Drop fragments and credentials; keep an explicit non-default port."""
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    default = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default
    netloc = host if port == default else f"{host}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, ""))


def url_origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
    return (parsed.scheme, host, parsed.port or (443 if parsed.scheme == "https" else 80))


def url_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PageExtract:
    title: str
    text: str
    links: tuple[str, ...]


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.main_parts: list[str] = []
        self.article_parts: list[str] = []
        self.heading_parts: list[str] = []
        self.meta_title = ""
        self.links: list[str] = []
        self._stack: list[tuple[str, bool]] = []
        self._capturing_title = False
        self._capturing_heading = False

    def _text(self, data: str) -> None:
        self.text_parts.append(data)
        tags = {tag for tag, _ in self._stack}
        if "main" in tags:
            self.main_parts.append(data)
        if "article" in tags:
            self.article_parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        parent_skipped = bool(self._stack and self._stack[-1][1])
        ancestors = {name for name, _ in self._stack}
        document_metadata = not parent_skipped and not (
            ancestors & {"body", "main", "article", "iframe"}
        )
        if tag == "title":
            self._capturing_title = document_metadata and not self.title_parts
        if tag == "h1":
            self._capturing_heading = not parent_skipped and not self.heading_parts
        # Keep discovery links independently of the readable article projection.
        if tag == "a" and not any(t in _SKIP_TAGS for t, _ in self._stack):
            href = values.get("href")
            if href and len(self.links) < MAX_LINKS_PER_PAGE:
                self.links.append(href)
        if (
            tag == "meta"
            and document_metadata
            and (values.get("property") or values.get("name")) in {"og:title", "twitter:title"}
        ):
            self.meta_title = values.get("content") or self.meta_title
        skipped = (
            parent_skipped
            or tag in _SKIP_TAGS
            or tag in {"nav", "footer", "aside"}
            or (
                "hidden" in values
                or values.get("aria-hidden") == "true"
                or values.get("role") in {"navigation", "banner", "complementary"}
                or bool(
                    re.search(
                        r"display\s*:\s*none|visibility\s*:\s*hidden",
                        values.get("style") or "",
                        re.I,
                    )
                )
                or bool(
                    _BOILERPLATE.search(f"{values.get('id') or ''} {values.get('class') or ''}")
                )
            )
        )
        if tag not in _VOID_TAGS:
            self._stack.append((tag, skipped))
        if tag in _BLOCK_TAGS and not skipped:
            self._text("\n")
        elif tag in {"td", "th"} and not skipped:
            self._text(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._capturing_title = False
        if tag == "h1":
            self._capturing_heading = False
        if tag in _BLOCK_TAGS and not (self._stack and self._stack[-1][1]):
            self._text("\n")
        elif tag in {"td", "th"} and not (self._stack and self._stack[-1][1]):
            self._text(" ")
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self._stack and self._stack[-1][1]:
            return
        tags = {tag for tag, _ in self._stack}
        if "title" in tags:
            if self._capturing_title:
                self.title_parts.append(data)
            return
        if "h1" in tags and self._capturing_heading:
            self.heading_parts.append(data)
        self._text(data)


def _parse_quietly(parser: HTMLParser, body: str) -> None:
    try:
        parser.feed(body)
        parser.close()
    except Exception:
        pass  # Malformed markup still yields whatever parsed cleanly.


def extract_page(body: str, *, base_url: str) -> PageExtract:
    parser = _PageParser()
    _parse_quietly(parser, body)
    title = _WHITESPACE.sub(
        " ", "".join(parser.title_parts) or parser.meta_title or " ".join(parser.heading_parts)
    ).strip()[:512]
    parts = (
        parser.main_parts
        if any(p.strip() for p in parser.main_parts)
        else parser.article_parts
        if any(p.strip() for p in parser.article_parts)
        else parser.text_parts
    )
    page = "\n".join(
        line for part in "".join(parts).splitlines() if (line := _WHITESPACE.sub(" ", part).strip())
    )[:MAX_EXTRACTED_CHARS]
    links: list[str] = []
    seen: set[str] = set()
    for href in parser.links:
        absolute = normalize_url(urljoin(base_url, href))
        if absolute and absolute not in seen:
            seen.add(absolute)
            links.append(absolute)
    return PageExtract(title=title, text=page, links=tuple(links))


def iter_feed_links(body: str, base_url: str) -> tuple[str, ...]:
    """Item links from RSS <link> text and Atom link href entries."""

    class _FeedParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.found: list[str] = []
            self._in_link = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            values = dict(attrs)
            if tag == "link":
                self._in_link = True
                href = values.get("href")
                if href and len(self.found) < MAX_LINKS_PER_PAGE:
                    self.found.append(href)

        def handle_endtag(self, tag: str) -> None:
            if tag == "link":
                self._in_link = False

        def handle_data(self, data: str) -> None:
            stripped = data.strip()
            if self._in_link and stripped and len(self.found) < MAX_LINKS_PER_PAGE:
                self.found.append(stripped)

    parser = _FeedParser()
    _parse_quietly(parser, body)
    result: list[str] = []
    for href in parser.found:
        absolute = normalize_url(urljoin(base_url, href))
        if absolute and absolute not in result:
            result.append(absolute)
    return tuple(result)


def iter_sitemap_locations(body: str) -> tuple[str, ...]:
    class _SitemapParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.found: list[str] = []
            self._in_loc = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag == "loc":
                self._in_loc = True

        def handle_endtag(self, tag: str) -> None:
            if tag == "loc":
                self._in_loc = False

        def handle_data(self, data: str) -> None:
            stripped = data.strip()
            if self._in_loc and stripped and len(self.found) < MAX_LINKS_PER_PAGE:
                self.found.append(stripped)

    parser = _SitemapParser()
    _parse_quietly(parser, body)
    return tuple(url for url in (normalize_url(item) for item in parser.found) if url)


@dataclass(frozen=True)
class RobotsRules:
    disallow_prefixes: tuple[str, ...] = ()
    allow_prefixes: tuple[str, ...] = ()
    crawl_delay_seconds: int | None = None
    sitemap_urls: tuple[str, ...] = ()
    allow_all: bool = False
    disallow_all: bool = False

    def permits(self, path: str) -> bool:
        if self.allow_all:
            return True
        if self.disallow_all:
            return False
        best_allow = max((len(p) for p in self.allow_prefixes if path.startswith(p)), default=-1)
        best_disallow = max(
            (len(p) for p in self.disallow_prefixes if path.startswith(p)), default=-1
        )
        return best_allow >= best_disallow


def parse_robots(body: str) -> RobotsRules:
    disallow: list[str] = []
    allow: list[str] = []
    sitemaps: list[str] = []
    delay: int | None = None
    agents: set[str] = set()
    applies = False
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        name, _, value = line.partition(":")
        name = name.strip().lower()
        value = value.strip()
        if name == "user-agent":
            applies = value.lower() in _OUR_AGENTS
            agents.add(value.lower())
            continue
        if not applies:
            continue
        if name == "disallow":
            if value:
                disallow.append(value)
            else:
                allow.append("")  # An empty Disallow rule allows the whole group.
        elif name == "allow" and value:
            allow.append(value)
        elif name == "crawl-delay" and value.isdigit():
            delay = min(int(value), 86400)
        elif name == "sitemap" and value:
            sitemaps.append(value)
    if not agents & {*_OUR_AGENTS}:
        return RobotsRules(allow_all=True, sitemap_urls=tuple(sitemaps))
    if any(prefix == "/" for prefix in disallow) and not allow:
        return RobotsRules(disallow_all=True, sitemap_urls=tuple(sitemaps))
    return RobotsRules(
        disallow_prefixes=tuple(disallow),
        allow_prefixes=tuple(allow),
        crawl_delay_seconds=delay,
        sitemap_urls=tuple(url for url in (normalize_url(s) for s in sitemaps) if url),
    )


def segment_text(value: str) -> str:
    """Offline jieba segmentation so PostgreSQL 'simple' tokens work for Chinese."""
    import jieba  # type: ignore[import-untyped]

    trimmed = value[:MAX_EXTRACTED_CHARS]
    return " ".join(part.strip() for part in jieba.cut_for_search(trimmed) if part.strip())


def policy_allowed(urls: list[str]) -> list[str]:
    guard = ReachPolicy()
    allowed: list[str] = []
    for url in urls:
        try:
            guard.assert_url_allowed(url)
        except ReachDeniedError:
            continue
        allowed.append(url)
    return allowed


class ResearchIndexService:
    """Builds and rebuilds the derived full-text projection over crawl snapshots."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def project(
        self,
        connection: Connection,
        *,
        tenant_id: UUID,
        space_id: UUID,
        line_id: UUID | None,
        source_id: UUID,
        snapshot_id: UUID,
        content_digest: str,
        url: str,
        lang: str,
        captured_at: datetime,
        body: str,
    ) -> None:
        extract = extract_page(body, base_url=url)
        segmented = segment_text(f"{extract.title} {extract.text}")
        statement = (
            pg_insert(tables.research_index_documents)
            .values(
                tenant_id=tenant_id,
                snapshot_id=snapshot_id,
                market_space_id=space_id,
                product_line_id=line_id,
                source_id=source_id,
                content_digest=content_digest,
                url=url[:1024],
                title=extract.title,
                lang=lang[:16],
                extracted_text=extract.text,
                doc_tsv=text("to_tsvector('simple', :segmented)"),
                captured_at=captured_at,
                indexed_at=datetime.now(UTC),
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "snapshot_id"],
                set_={
                    "title": extract.title,
                    "lang": lang[:16],
                    "extracted_text": extract.text,
                    "doc_tsv": text("to_tsvector('simple', :segmented)"),
                    "indexed_at": datetime.now(UTC),
                },
            )
        )
        connection.execute(statement, {"segmented": segmented})

    def rebuild(self) -> dict[str, int]:
        """Re-derive every crawl projection from immutable snapshot bodies."""
        frontier = tables.research_crawl_frontier
        snapshots = tables.evidence_snapshots
        contents = tables.evidence_contents
        projected = skipped = 0
        with self.engine.begin() as connection:
            connection.execute(tables.research_index_documents.delete())
        with self.engine.connect() as reader:
            rows = reader.execute(
                select(
                    frontier.c.tenant_id,
                    frontier.c.market_space_id,
                    frontier.c.product_line_id,
                    frontier.c.source_id,
                    frontier.c.last_snapshot_id,
                    snapshots.c.content_digest,
                    snapshots.c.url,
                    snapshots.c.content_language,
                    snapshots.c.captured_at,
                    snapshots.c.superseded_by_id,
                    contents.c.body,
                )
                .select_from(frontier)
                .join(
                    snapshots,
                    (snapshots.c.tenant_id == frontier.c.tenant_id)
                    & (snapshots.c.id == frontier.c.last_snapshot_id),
                )
                .join(
                    contents,
                    (contents.c.tenant_id == frontier.c.tenant_id)
                    & (contents.c.content_digest == snapshots.c.content_digest),
                )
                .where(frontier.c.last_snapshot_id.is_not(None))
            ).mappings()
            for row in rows:
                if row["superseded_by_id"] is not None:
                    skipped += 1
                    continue
                with self.engine.begin() as writer:
                    self.project(
                        writer,
                        tenant_id=row["tenant_id"],
                        space_id=row["market_space_id"],
                        line_id=row["product_line_id"],
                        source_id=row["source_id"],
                        snapshot_id=row["last_snapshot_id"],
                        content_digest=row["content_digest"],
                        url=row["url"] or "",
                        lang=row["content_language"],
                        captured_at=row["captured_at"],
                        body=row["body"],
                    )
                projected += 1
        return {"projected": projected, "skipped_superseded": skipped}
