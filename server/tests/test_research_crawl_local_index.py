"""Crawler frontier, robots fencing, derived index and local search; synthetic fixture server."""

# ruff: noqa: F811

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.ai import reach
from app.ai.reach import ReachPolicy, ReachResponse
from app.db.schema import tables
from app.domain import research_collection, research_crawler
from app.domain.evidence import EvidenceService
from app.domain.research_crawler import ResearchCrawlerWorker
from tests.test_product_discovery_findings_api import seed_discovery
from tests.test_product_planning_findings_api import post
from tests.test_test_runs_api import Scope, client, isolated_test_run_database  # noqa: F401

ROBOTS = "User-agent: *\nDisallow: /private\nSitemap: https://example.com/sitemap.xml\n"
HOMEPAGE = """<html><head><title>示例气泵站</title></head><body><h1>首页</h1>
<p>欢迎来到示例站点，提供气泵资料。</p>
<a href="/docs">文档</a><script>fetch('/evil')</script></body></html>"""
DOCS = """<html><head><title>产品文档</title></head><body>
<a href="/spec">规格</a><a href="https://other.example.com/x">外站</a>
<a href="/login">登录</a><a href="/private">私密</a></body></html>"""
SPEC = """<html><head><title>无刷电机规格</title></head><body>
<p>本型号无刷电机峰值压力 120kPa，噪音低于 45dB，适合车载气泵。</p></body></html>"""
SITEMAP = "<urlset><url><loc>https://example.com/from-sitemap</loc></url></urlset>"
FROM_SITEMAP = (
    "<html><head><title>站点地图页</title></head><body><p>来自站点地图。</p></body></html>"
)


class Pages:
    """Deterministic in-process stand-in for the public source site."""

    def __init__(self) -> None:
        self.robots_reads = 0
        self.mode = "success"

    def transport(self) -> type:
        pages = self

        class Transport:
            def __init__(self, **kwargs: object) -> None:
                pass

            def get(self, url: str) -> ReachResponse:
                if url.endswith("/robots.txt"):
                    pages.robots_reads += 1
                    return ReachResponse(200, ROBOTS, "text/plain", len(ROBOTS.encode()))
                if pages.mode == "interrupt":
                    raise SystemExit("合成进程中断，保留原租约")
                body = {
                    "https://example.com/": HOMEPAGE,
                    "https://example.com/docs": DOCS,
                    "https://example.com/spec": SPEC,
                    "https://example.com/sitemap.xml": SITEMAP,
                    "https://example.com/from-sitemap": FROM_SITEMAP,
                }.get(url)
                if body is None:
                    return ReachResponse(404, "", "text/plain", 0)
                return ReachResponse(
                    200, body, "text/html", len(body.encode()), source_version="v1"
                )

        return Transport


def crawl_until_idle(worker: ResearchCrawlerWorker, *, bound: int = 15) -> list[str]:
    statuses: list[str] = []
    for _ in range(bound):
        result = worker.run_once()
        statuses.append(str(result["status"]))
        if result["status"] == "idle":
            break
    return statuses


def frontier_urls(scope: Scope) -> dict[str, str]:
    table = tables.research_crawl_frontier
    with scope.engine.connect() as connection:
        rows = connection.execute(
            select(table.c.url, table.c.status).where(table.c.tenant_id == scope.tenant_id)
        ).all()
    return {url: status for url, status in rows}


def patch_reach(monkeypatch: pytest.MonkeyPatch, pages: Pages) -> None:
    from app.ai import research_search as provider_module
    from app.domain import research_subscriptions

    def policy() -> ReachPolicy:
        return ReachPolicy(resolver=lambda hostname: ["93.184.216.34"])

    transport = pages.transport()
    monkeypatch.setattr(research_crawler, "ReachPolicy", policy)
    monkeypatch.setattr(research_crawler, "PublicReachTransport", transport)
    monkeypatch.setattr(research_collection, "PublicReachTransport", transport)
    monkeypatch.setattr(research_subscriptions, "ReachPolicy", policy)
    monkeypatch.setattr(reach, "ReachPolicy", policy)
    # The local provider re-vets every hit through reach policy too.
    monkeypatch.setattr(provider_module, "ReachPolicy", policy)


def setup_source_and_subscription(
    client: TestClient, scope: Scope, seed: dict, url: str
) -> None:
    source = EvidenceService(scope.engine).create_source(
        tenant_id=scope.tenant_id,
        actor_user_id=scope.owner_id,
        name=f"合成爬取源-{url}",
        source_type="web",
        base_url="https://example.com",
        allowed_use="internal_analysis",
        collection_frequency="daily",
        retention_policy="standard",
        trust_tier="unknown",
    )
    body = dict(
        request_id=str(uuid4()),
        source_id=str(source.id),
        product_line_id=seed["line"]["id"],
        url=url,
        frequency="daily",
        freshness_days=3,
    )
    created = post(client, seed["base"], seed["headers"], "/subscriptions", body, 201)
    assert created["id"]


def test_crawl_seeds_pages_index_and_local_search(
    client: TestClient, isolated_test_run_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        seed = seed_discovery(client, scope)
        pages = Pages()
        patch_reach(monkeypatch, pages)
        setup_source_and_subscription(client, scope, seed, "https://example.com/docs")
        worker = ResearchCrawlerWorker(scope.engine, enabled=True, max_frontier=50)
        assert ResearchCrawlerWorker(scope.engine).run_once() == {"status": "disabled"}
        statuses = crawl_until_idle(worker)
        assert "completed" in statuses
        state = frontier_urls(scope)
        for url in (
            "https://example.com/",
            "https://example.com/docs",
            "https://example.com/spec",
        ):
            assert state.get(url) == "done", (url, state)
        # Sitemap entries named by robots become crawlable seeds.
        assert state.get("https://example.com/from-sitemap") == "done"
        # Cross-origin links, policy-denied paths and robots-denied paths stay out.
        assert "https://other.example.com/x" not in state
        assert "https://example.com/login" not in state
        assert "https://example.com/private" not in state

        # The derived index backs the same durable search observation contract.
        response = client.post(
            seed["base"] + "/searches",
            headers=seed["headers"],
            json=dict(
                request_id=str(uuid4()),
                product_line_id=seed["line"]["id"],
                query="无刷电机 峰值压力",
                language="auto",
                result_limit=5,
            ),
        )
        assert response.status_code == 201, response.text
        value = response.json()
        assert value["status"] == "completed"
        assert value["provider_key"] == "local-index"
        assert [hit["url"] for hit in value["hits"]] == ["https://example.com/spec"]
        assert "无刷电机" in value["hits"][0]["snippet"]
        sources = client.get(seed["base"] + "/sources", headers=seed["headers"]).json()
        assert sources["search_available"] is True
        assert sources["search_provider"] == "local-index"

        # Superseded snapshots leave the searchable projection on the next query.
        table = tables.research_crawl_frontier
        with scope.engine.begin() as connection:
            spec_snapshot, docs_snapshot = connection.execute(
                select(table.c.last_snapshot_id)
                .where(
                    table.c.tenant_id == scope.tenant_id,
                    table.c.url.in_(("https://example.com/spec", "https://example.com/docs")),
                )
                .order_by(table.c.url.desc())
            ).scalars().all()
            connection.execute(
                update(tables.evidence_snapshots)
                .where(tables.evidence_snapshots.c.id == spec_snapshot)
                .values(superseded_by_id=docs_snapshot)
            )
        replay = client.post(
            seed["base"] + "/searches",
            headers=seed["headers"],
            json=dict(
                request_id=str(uuid4()),
                product_line_id=seed["line"]["id"],
                query="无刷电机 峰值压力",
                language="auto",
                result_limit=5,
            ),
        )
        assert replay.status_code == 201, replay.text
        assert replay.json()["status"] == "no_results"
    finally:
        scope.dispose()


def test_crawl_skips_robots_denied_paths_and_uses_cache(
    client: TestClient, isolated_test_run_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        seed = seed_discovery(client, scope)
        pages = Pages()
        patch_reach(monkeypatch, pages)
        setup_source_and_subscription(client, scope, seed, "https://example.com/private")
        worker = ResearchCrawlerWorker(scope.engine, enabled=True, max_frontier=50)
        for _ in range(10):
            if frontier_urls(scope).get("https://example.com/private") in {
                "skipped",
                "done",
                "failed",
            }:
                break
            worker.run_once()
        assert frontier_urls(scope)["https://example.com/private"] == "skipped"
        runs = tables.research_crawl_runs
        frontier = tables.research_crawl_frontier
        with scope.engine.connect() as connection:
            recorded = connection.execute(
                select(runs.c.status)
                .select_from(runs.join(frontier, frontier.c.id == runs.c.frontier_id))
                .where(
                    runs.c.tenant_id == scope.tenant_id,
                    frontier.c.url == "https://example.com/private",
                )
                .order_by(runs.c.started_at.desc())
                .limit(1)
            ).scalar_one()
        assert recorded == "skipped_robots"
        # Further cycles reuse the cached robots file instead of refetching.
        crawl_until_idle(worker)
        assert pages.robots_reads == 1
    finally:
        scope.dispose()


def test_crawl_recovers_expired_lease_and_completes(
    client: TestClient, isolated_test_run_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        seed = seed_discovery(client, scope)
        pages = Pages()
        patch_reach(monkeypatch, pages)
        setup_source_and_subscription(client, scope, seed, "https://example.com/docs")
        pages.mode = "interrupt"
        worker = ResearchCrawlerWorker(scope.engine, enabled=True, max_frontier=50)
        worker.seed()
        with pytest.raises(SystemExit):
            worker.run_once()
        state = frontier_urls(scope)
        # Whichever seed was claimed first stays leased mid-flight.
        assert "running" in state.values()
        pages.mode = "success"
        table = tables.research_crawl_frontier
        with scope.engine.begin() as connection:
            connection.execute(
                update(table)
                .where(table.c.tenant_id == scope.tenant_id, table.c.status == "running")
                .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        recovered = False
        for _ in range(10):
            result = worker.run_once()
            recovered = recovered or result["status"] == "recovered"
            with scope.engine.begin() as connection:
                connection.execute(
                    update(table)
                    .where(table.c.tenant_id == scope.tenant_id, table.c.status == "pending")
                    .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
                )
            if frontier_urls(scope).get("https://example.com/docs") == "done" and all(
                status in {"done", "skipped", "failed"}
                for status in frontier_urls(scope).values()
            ):
                break
        assert recovered
        assert frontier_urls(scope)["https://example.com/docs"] == "done"
    finally:
        scope.dispose()
