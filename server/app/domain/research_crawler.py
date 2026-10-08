"""Deterministic same-origin crawler feeding the local research index.

Every cycle claims one due frontier row with the same fencing discipline as the
subscription collector (space row lock, lease token, host budget, backoff and
terminal failure). Discovered pages are captured as ordinary untrusted evidence
snapshots and projected into `research_index_documents`; nothing here calls a
model or sends outbound messages, and robots.txt is honoured for our agent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.ai.reach import (
    ReachDeniedError,
    ReachFetchError,
    ReachPolicy,
    ReachRateLimitedError,
)
from app.ai.reach_transport import PublicReachTransport
from app.auth.repository import AuthContext, AuthRepository
from app.db.schema import tables
from app.domain.evidence import EvidenceSnapshotRecord, EvidenceValidationError
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, _emit
from app.domain.research_collection import authorize_collection, collect_page, source_origin
from app.domain.research_index import (
    ROBOTS_TTL_HOURS,
    ResearchIndexService,
    RobotsRules,
    extract_page,
    iter_feed_links,
    iter_sitemap_locations,
    normalize_url,
    parse_robots,
    url_key,
    url_origin,
)

HOST_RUNS_PER_HOUR = 12
LEASE_SECONDS = 90


class CrawlLeaseLost(RuntimeError):
    pass


def _origin_url(origin: tuple[str, str, int], path: str) -> str:
    scheme, host, port = origin
    default = 443 if scheme == "https" else 80
    netloc = host if port == default else f"{host}:{port}"
    return urlunsplit((scheme, netloc, path, "", ""))


def _looks_like_feed(body: str) -> bool:
    head = body.lstrip()[:512].lower()
    return head.startswith("<?xml") and ("<rss" in head or "<feed" in head or "<rdf" in head)


def _looks_like_sitemap(body: str) -> bool:
    head = body.lstrip()[:512].lower()
    return "<urlset" in head or "<sitemapindex" in head


class ResearchCrawlerWorker:
    """One fenced crawl per cycle, using the app service role, not pdos_agent."""

    def __init__(
        self,
        engine: Engine,
        *,
        enabled: bool = False,
        max_depth: int = 3,
        max_frontier: int = 500,
    ) -> None:
        self.engine = engine
        self.enabled = enabled
        self.max_depth = max_depth
        self.max_frontier = max_frontier
        self.index = ResearchIndexService(engine)

    # ------------------------------------------------------------------ seeds

    def seed(self) -> dict[str, Any]:
        """Active subscriptions and their source bases become frontier seeds."""
        added = 0
        now = datetime.now(UTC)
        subscription = tables.research_subscriptions
        source = tables.research_sources
        with self.engine.begin() as connection:
            rows = connection.execute(
                select(
                    subscription.c.tenant_id,
                    subscription.c.market_space_id,
                    subscription.c.product_line_id,
                    subscription.c.source_id,
                    subscription.c.owner_user_id,
                    subscription.c.url,
                    source.c.base_url,
                )
                .select_from(
                    subscription.join(
                        source,
                        (source.c.tenant_id == subscription.c.tenant_id)
                        & (source.c.id == subscription.c.source_id),
                    )
                )
                .where(
                    subscription.c.status == "active",
                    source.c.status == "active",
                    source.c.source_type == "web",
                )
            ).mappings()
            for row in rows:
                for raw in (row["base_url"], row["url"]):
                    added += self._enqueue(
                        connection,
                        tenant_id=row["tenant_id"],
                        space_id=row["market_space_id"],
                        line_id=row["product_line_id"],
                        source_id=row["source_id"],
                        owner_user_id=row["owner_user_id"],
                        url=normalize_url(raw or ""),
                        depth=0,
                        discovered_from="seed",
                        now=now,
                    )
        return {"status": "seeded", "added": added}

    def _frontier_size(self, connection: Connection, tenant_id: UUID, source_id: UUID) -> int:
        table = tables.research_crawl_frontier
        return int(
            connection.execute(
                select(func.count())
                .select_from(table)
                .where(table.c.tenant_id == tenant_id, table.c.source_id == source_id)
            ).scalar_one()
        )

    def _enqueue(
        self,
        connection: Connection,
        *,
        tenant_id: UUID,
        space_id: UUID,
        line_id: UUID | None,
        source_id: UUID,
        owner_user_id: UUID,
        url: str,
        depth: int,
        discovered_from: str,
        now: datetime,
        snapshot_id: UUID | None = None,
    ) -> int:
        if not url or len(url) > 1024 or depth > self.max_depth:
            return 0
        try:
            ReachPolicy().assert_url_allowed(url)
        except ReachDeniedError:
            return 0
        if self._frontier_size(connection, tenant_id, source_id) >= self.max_frontier:
            return 0
        statement = (
            pg_insert(tables.research_crawl_frontier)
            .values(
                id=uuid4(),
                tenant_id=tenant_id,
                market_space_id=space_id,
                product_line_id=line_id,
                source_id=source_id,
                owner_user_id=owner_user_id,
                url=url,
                url_key=url_key(url),
                hostname=url_origin(url)[1],
                depth=depth,
                discovered_from=discovered_from,
                discovered_from_snapshot_id=snapshot_id,
                status="pending",
                next_attempt_at=now,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "source_id", "url_key"])
            .returning(tables.research_crawl_frontier.c.id)
        )
        return len(connection.execute(statement).all())

    # ------------------------------------------------------------------ robots

    def _robots(self, context: AuthContext, origin: tuple[str, str, int]) -> RobotsRules:
        """Cached per tenant+host; the robots file itself passes reach policy."""
        table = tables.research_robots_cache
        now = datetime.now(UTC)
        with self.engine.connect() as connection:
            cached = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id, table.c.hostname == origin[1]
                    )
                )
                .mappings()
                .one_or_none()
            )
        if cached is not None and cached["expires_at"] > now:
            return RobotsRules(
                disallow_prefixes=tuple(cached["disallow_prefixes"]),
                allow_prefixes=tuple(cached["allow_prefixes"]),
                crawl_delay_seconds=cached["crawl_delay_seconds"],
                sitemap_urls=tuple(cached["sitemap_urls"]),
            )
        response = PublicReachTransport(required_origin=origin, total_timeout=20).get(
            _origin_url(origin, "/robots.txt")
        )
        if response.status_code == 404:
            rules = RobotsRules(allow_all=True)
            body = ""
        elif response.status_code in {401, 403}:
            rules = RobotsRules(disallow_all=True)
            body = ""
        elif response.status_code == 200:
            body = response.content
            rules = parse_robots(body)
        else:
            raise ReachFetchError(f"robots.txt 状态异常（HTTP {response.status_code}）")
        digest_value = sha256(body.encode("utf-8")).hexdigest()
        statement = (
            pg_insert(table)
            .values(
                id=uuid4(),
                tenant_id=context.tenant.id,
                hostname=origin[1],
                robots_digest=digest_value,
                disallow_prefixes=list(rules.disallow_prefixes),
                allow_prefixes=list(rules.allow_prefixes),
                crawl_delay_seconds=rules.crawl_delay_seconds,
                sitemap_urls=list(rules.sitemap_urls),
                fetched_at=now,
                expires_at=now + timedelta(hours=ROBOTS_TTL_HOURS),
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "hostname"],
                set_={
                    "robots_digest": digest_value,
                    "disallow_prefixes": list(rules.disallow_prefixes),
                    "allow_prefixes": list(rules.allow_prefixes),
                    "crawl_delay_seconds": rules.crawl_delay_seconds,
                    "sitemap_urls": list(rules.sitemap_urls),
                    "fetched_at": now,
                    "expires_at": now + timedelta(hours=ROBOTS_TTL_HOURS),
                },
            )
        )
        with self.engine.begin() as connection:
            connection.execute(statement)
        return rules

    # ------------------------------------------------------------------ claims

    def _fail(
        self,
        connection: Connection,
        context: AuthContext,
        row: Any,
        code: str,
        message: str,
        *,
        permanent: bool = False,
        run_status: str = "failed",
    ) -> str:
        now = datetime.now(UTC)
        failures = row["consecutive_failures"] + 1
        terminal = permanent or failures >= 5
        runs = tables.research_crawl_runs
        if row["lease_token"] is not None:
            connection.execute(
                runs.update()
                .where(runs.c.id == row["lease_token"], runs.c.status == "running")
                .values(status=run_status, finished_at=now, error_code=code, error_message=message)
            )
        table = tables.research_crawl_frontier
        after = (
            connection.execute(
                table.update()
                .where(table.c.id == row["id"])
                .values(
                    status="failed" if terminal else "pending",
                    next_attempt_at=None
                    if terminal
                    else now + timedelta(minutes=min(5 * 2 ** (failures - 1), 1440)),
                    consecutive_failures=failures,
                    lease_token=None,
                    lease_expires_at=None,
                    last_error_code=code,
                    last_error_message=message,
                    version=row["version"] + 1,
                    updated_at=now,
                )
                .returning(table)
            )
            .mappings()
            .one()
        )
        _emit(
            connection,
            context,
            row["market_space_id"],
            "research_crawl_frontier",
            "failed" if terminal else "retry_scheduled",
            after,
            before=row,
        )
        return "failed" if terminal else "retry_scheduled"

    def _enqueue_links(
        self,
        connection: Connection,
        *,
        row: Any,
        extract_urls: list[str],
        rules: RobotsRules,
        origin: tuple[str, str, int],
        snapshot_id: UUID | None,
        discovered_from: str,
        depth: int,
    ) -> int:
        added = 0
        now = datetime.now(UTC)
        for url in extract_urls:
            if url_origin(url) != origin:
                continue
            if not rules.permits(urlsplit(url).path or "/"):
                continue
            added += self._enqueue(
                connection,
                tenant_id=row["tenant_id"],
                space_id=row["market_space_id"],
                line_id=row["product_line_id"],
                source_id=row["source_id"],
                owner_user_id=row["owner_user_id"],
                url=url,
                depth=depth,
                discovered_from=discovered_from,
                now=now,
                snapshot_id=snapshot_id,
            )
        return added

    def run_once(self) -> dict[str, Any]:
        if not self.enabled:
            return {"status": "disabled"}
        self.seed()
        table = tables.research_crawl_frontier
        runs = tables.research_crawl_runs
        now = datetime.now(UTC)
        with self.engine.connect() as connection:
            candidate = (
                connection.execute(
                    select(table)
                    .where(
                        (
                            (table.c.status == "pending")
                            & (table.c.next_attempt_at <= now)
                            & (
                                (table.c.lease_expires_at.is_(None))
                                | (table.c.lease_expires_at <= now)
                            )
                        )
                        | (
                            # A crashed claim keeps status 'running' until its
                            # expired lease is recovered by a later cycle.
                            (table.c.status == "running")
                            & (table.c.lease_expires_at.is_not(None))
                            & (table.c.lease_expires_at <= now)
                        )
                    )
                    .order_by(table.c.next_attempt_at, table.c.id)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if candidate is None:
            return {"status": "idle"}
        context = AuthRepository(self.engine).find_user_context(candidate["owner_user_id"])
        if context is None or context.tenant.id != candidate["tenant_id"]:
            raise RuntimeError("Crawl frontier owner identity is missing")
        with self.engine.begin() as connection:
            # All writers take the space lock before frontier or receipt locks.
            space_lock = connection.execute(
                select(tables.market_spaces.c.id)
                .where(
                    tables.market_spaces.c.id == candidate["market_space_id"],
                    tables.market_spaces.c.tenant_id == candidate["tenant_id"],
                )
                .with_for_update(skip_locked=True)
            ).first()
            if space_lock is None:
                return {"status": "busy"}
            row = (
                connection.execute(
                    select(table).where(table.c.id == candidate["id"]).with_for_update()
                )
                .mappings()
                .one()
            )
            current_now = datetime.now(UTC)
            if row["owner_user_id"] != context.user.id:
                return {"status": "busy"}
            if row["status"] == "running":
                if row["lease_expires_at"] is None or row["lease_expires_at"] > current_now:
                    return {"status": "busy"}
            elif (
                row["status"] != "pending"
                or row["next_attempt_at"] is None
                or row["next_attempt_at"] > current_now
                or (
                    row["lease_expires_at"] is not None and row["lease_expires_at"] > current_now
                )
            ):
                return {"status": "busy"}
            if row["lease_token"] is not None:
                self._fail(
                    connection,
                    context,
                    row,
                    "CRAWL_INTERRUPTED",
                    "爬取租约超时，将按退避策略处理",
                    run_status="timed_out",
                )
                return {"status": "recovered"}
            try:
                authorize_collection(
                    connection, context, row["market_space_id"], row["product_line_id"]
                )
                origin = source_origin(connection, row["tenant_id"], row["source_id"])
            except (ProductWorkAccessError, ProductWorkError) as error:
                self._fail(
                    connection,
                    context,
                    row,
                    "CRAWL_AUTHORIZATION_CHANGED",
                    str(error),
                    permanent=True,
                )
                return {"status": "failed"}
            if url_origin(row["url"]) != origin:
                self._fail(
                    connection,
                    context,
                    row,
                    "CRAWL_ORIGIN_CHANGED",
                    "来源基址已变化，页面不再属于所选来源",
                    permanent=True,
                )
                return {"status": "failed"}
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"research-host:{row['tenant_id']}:{row['hostname']}"},
            )
            used = connection.execute(
                select(func.count())
                .select_from(runs)
                .where(
                    runs.c.tenant_id == row["tenant_id"],
                    runs.c.hostname == row["hostname"],
                    runs.c.started_at > now - timedelta(hours=1),
                )
            ).scalar_one()
            if used >= HOST_RUNS_PER_HOUR:
                after = (
                    connection.execute(
                        table.update()
                        .where(table.c.id == row["id"])
                        .values(
                            next_attempt_at=now + timedelta(hours=1),
                            last_error_code="HOST_READ_LIMIT",
                            last_error_message="同租户来源每小时爬取上限已到，稍后继续",
                            version=row["version"] + 1,
                            updated_at=now,
                        )
                        .returning(table)
                    )
                    .mappings()
                    .one()
                )
                _emit(
                    connection,
                    context,
                    row["market_space_id"],
                    "research_crawl_frontier",
                    "deferred",
                    after,
                    before=row,
                )
                return {"status": "deferred"}
            token = uuid4()
            claimed = (
                connection.execute(
                    table.update()
                    .where(table.c.id == row["id"])
                    .values(
                        status="running",
                        next_attempt_at=None,
                        lease_token=token,
                        lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
                        last_attempt_at=now,
                        version=row["version"] + 1,
                        updated_at=now,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            connection.execute(
                runs.insert().values(
                    id=token,
                    tenant_id=row["tenant_id"],
                    frontier_id=row["id"],
                    frontier_version=claimed["version"],
                    hostname=row["hostname"],
                    status="running",
                    started_at=now,
                )
            )
            _emit(
                connection,
                context,
                row["market_space_id"],
                "research_crawl_frontier",
                "crawl_started",
                claimed,
                before=row,
            )

        def guard(connection: Connection) -> None:
            current = (
                connection.execute(
                    select(table).where(table.c.id == claimed["id"]).with_for_update()
                )
                .mappings()
                .one()
            )
            if (
                current["status"] != "running"
                or current["lease_token"] != token
                or current["lease_expires_at"] <= datetime.now(UTC)
            ):
                raise CrawlLeaseLost("爬取已超时或由新的执行接管")

        def saved(connection: Connection, snapshot: EvidenceSnapshotRecord) -> None:
            guard(connection)
            current = (
                connection.execute(select(table).where(table.c.id == claimed["id"]))
                .mappings()
                .one()
            )
            previous_digest = (
                connection.execute(
                    select(tables.evidence_snapshots.c.content_digest).where(
                        tables.evidence_snapshots.c.tenant_id == row["tenant_id"],
                        tables.evidence_snapshots.c.id == current["last_snapshot_id"],
                    )
                ).scalar_one_or_none()
                if current["last_snapshot_id"]
                else None
            )
            finished = datetime.now(UTC)
            connection.execute(
                runs.update()
                .where(runs.c.id == token, runs.c.status == "running")
                .values(
                    status="completed",
                    finished_at=finished,
                    snapshot_id=snapshot.id,
                    content_changed=previous_digest != snapshot.content_digest,
                )
            )
            after = (
                connection.execute(
                    table.update()
                    .where(table.c.id == claimed["id"])
                    .values(
                        status="done",
                        next_attempt_at=None,
                        last_snapshot_id=snapshot.id,
                        last_success_at=finished,
                        consecutive_failures=0,
                        last_error_code=None,
                        last_error_message=None,
                        lease_token=None,
                        lease_expires_at=None,
                        version=current["version"] + 1,
                        updated_at=finished,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _emit(
                connection,
                context,
                row["market_space_id"],
                "research_crawl_frontier",
                "crawled",
                after,
                before=current,
            )

        try:
            rules = self._robots(context, origin)
            if not rules.permits(urlsplit(row["url"]).path or "/"):
                with self.engine.begin() as connection:
                    connection.execute(
                        select(tables.market_spaces.c.id)
                        .where(tables.market_spaces.c.id == row["market_space_id"])
                        .with_for_update()
                    )
                    guard(connection)
                    finished = datetime.now(UTC)
                    connection.execute(
                        runs.update()
                        .where(runs.c.id == token, runs.c.status == "running")
                        .values(status="skipped_robots", finished_at=finished)
                    )
                    after = (
                        connection.execute(
                            table.update()
                            .where(table.c.id == row["id"])
                            .values(
                                status="skipped",
                                next_attempt_at=None,
                                lease_token=None,
                                lease_expires_at=None,
                                last_error_code="ROBOTS_DISALLOWED",
                                last_error_message="robots.txt 不允许抓取此路径",
                                version=claimed["version"] + 1,
                                updated_at=finished,
                            )
                            .returning(table)
                        )
                        .mappings()
                        .one()
                    )
                    _emit(
                        connection,
                        context,
                        row["market_space_id"],
                        "research_crawl_frontier",
                        "skipped",
                        after,
                        before=claimed,
                    )
                return {"status": "skipped_robots"}
            collected = collect_page(
                self.engine,
                context,
                space_id=claimed["market_space_id"],
                line_id=claimed["product_line_id"],
                source_id=claimed["source_id"],
                url=claimed["url"],
                freshness_days=None,
                guard=guard,
                on_capture=saved,
            )
            snapshot = collected.snapshot
            body = collected.read.content
            extract = extract_page(body, base_url=collected.read.final_url)
            discovered: list[str] = list(extract.links)
            if _looks_like_feed(body):
                discovered.extend(iter_feed_links(body, base_url=collected.read.final_url))
            if _looks_like_sitemap(body):
                discovered.extend(iter_sitemap_locations(body))
            sitemap_seeds = [url for url in rules.sitemap_urls if url_origin(url) == origin]
            with self.engine.begin() as connection:
                connection.execute(
                    select(tables.market_spaces.c.id)
                    .where(tables.market_spaces.c.id == row["market_space_id"])
                    .with_for_update()
                )
                self.index.project(
                    connection,
                    tenant_id=row["tenant_id"],
                    space_id=row["market_space_id"],
                    line_id=row["product_line_id"],
                    source_id=row["source_id"],
                    snapshot_id=snapshot.id,
                    content_digest=snapshot.content_digest,
                    url=claimed["url"],
                    lang=snapshot.content_language,
                    captured_at=snapshot.captured_at,
                    body=body,
                )
                links_added = self._enqueue_links(
                    connection,
                    row=claimed,
                    extract_urls=discovered,
                    rules=rules,
                    origin=origin,
                    snapshot_id=snapshot.id,
                    discovered_from="link",
                    depth=claimed["depth"] + 1,
                )
                sitemap_added = self._enqueue_links(
                    connection,
                    row=claimed,
                    extract_urls=sitemap_seeds,
                    rules=RobotsRules(),  # sitemap paths named by robots are intended.
                    origin=origin,
                    snapshot_id=None,
                    discovered_from="sitemap",
                    depth=1,
                )
                connection.execute(
                    runs.update()
                    .where(runs.c.id == token, runs.c.status == "completed")
                    .values(links_added=links_added + sitemap_added)
                )
            return {"status": "completed", "links_added": links_added + sitemap_added}
        except Exception as error:
            permanent = isinstance(
                error,
                (
                    ReachDeniedError,
                    ProductWorkAccessError,
                    ProductWorkError,
                    EvidenceValidationError,
                ),
            )
            code = (
                error.reason
                if isinstance(error, ReachDeniedError)
                else "CRAWL_STOPPED"
                if isinstance(error, CrawlLeaseLost)
                else "CRAWL_UNAVAILABLE"
            )
            message = (
                str(error)
                if isinstance(
                    error,
                    (
                        ReachDeniedError,
                        ReachFetchError,
                        ReachRateLimitedError,
                        ProductWorkAccessError,
                        ProductWorkError,
                        CrawlLeaseLost,
                    ),
                )
                else "页面爬取失败，已安排后续处置"
            )
            with self.engine.begin() as connection:
                connection.execute(
                    select(tables.market_spaces.c.id)
                    .where(tables.market_spaces.c.id == claimed["market_space_id"])
                    .with_for_update()
                )
                current = (
                    connection.execute(
                        select(table).where(table.c.id == claimed["id"]).with_for_update()
                    )
                    .mappings()
                    .one()
                )
                if current["lease_token"] != token:
                    recorded = connection.execute(
                        select(runs.c.status).where(runs.c.id == token)
                    ).scalar_one()
                    return {"status": "completed" if recorded == "completed" else "discarded"}
                outcome = self._fail(
                    connection,
                    context,
                    current,
                    code,
                    message,
                    permanent=permanent,
                    run_status="timed_out" if isinstance(error, CrawlLeaseLost) else "failed",
                )
            return {"status": outcome}
