"""PM research routes with real persistence and controlled external transports.

Synthetic public text and test accounts prove local wiring, not live research,
external storage, model qualification or an actual professional/manual Exit.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.ai import reach, research_search
from app.ai.reach import ReachPolicy, ReachResponse
from app.api import product_research
from app.db.schema import tables
from app.domain import research_collection
from tests.product_master_reference_fixtures import (
    master_reference_database_guard as master_reference_database_guard,
)
from tests.test_product_conversations_api import Candidate, colleague
from tests.test_product_conversations_api import candidate as candidate
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database

SEARCH_ENDPOINT = "https://search.example.com/search"
SOURCE_ORIGIN = "https://evidence.example.com"
PAGE_URL = SOURCE_ORIGIN + "/pump-specification"
ORIGINAL_BODY = "合成原文：额定压力120 kPa，单位与原句保留。\n覆盖限制：未经实际业务验证。"


@dataclass
class Entry:
    candidate: Candidate
    settings: SimpleNamespace
    payload: dict[str, Any] = field(
        default_factory=lambda: {
            "results": [{"url": PAGE_URL, "title": "合成公开规格", "content": "仅作研究线索"}]
        }
    )
    search_status: int = 200
    search_calls: list[str] = field(default_factory=list)
    capture_calls: list[str] = field(default_factory=list)
    body: str = ORIGINAL_BODY
    after_capture_read: Callable[[], None] | None = None

    @property
    def base(self) -> str:
        return f"/api/product-work/spaces/{self.candidate.space_id}"

    def source_body(self) -> dict[str, Any]:
        return {
            "name": "合成PM公开来源",
            "base_url": SOURCE_ORIGIN,
            "allowed_use": "internal_citation",
            "license_note": "仅合成内部联验，不代表真实来源许可",
            "trust_tier": "public",
        }

    def source(self) -> dict[str, Any]:
        return self.candidate.post(self.base + "/sources", self.source_body(), 201)

    def query(self) -> dict[str, Any]:
        return {
            "request_id": str(uuid4()),
            "product_line_id": self.candidate.line["id"],
            "query": "合成气泵 公开规格",
            "language": "zh-CN",
            "time_range": "month",
            "result_limit": 2,
        }

    def capture(self, source: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_id": source["id"],
            "url": PAGE_URL,
            "product_line_id": self.candidate.line["id"],
            "freshness_days": 3,
        }

    def get(self, path: str, headers: dict[str, str]) -> dict[str, Any]:
        response = self.candidate.client.get(self.base + path, headers=headers)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        return dict(response.json())

    def state(self) -> dict[str, list[dict[str, Any]]]:
        # Membership/user changes in the test are deliberate; any business,
        # evidence, search, event or audit mutation from a denied route is not.
        checked = (
            tables.research_sources,
            tables.research_searches,
            tables.evidence_snapshots,
            tables.evidence_contents,
            tables.scoped_work_items,
            tables.research_tasks,
            tables.product_nodes,
            tables.market_segments,
            tables.opportunities,
            tables.experiments,
            tables.product_strategies,
            tables.product_definitions,
            tables.product_source_files,
            tables.agent_runs,
            tables.model_invocations,
            tables.findings,
            tables.events,
            tables.audit_log,
        )
        with self.candidate.scope.engine.connect() as c:
            return {
                table.name: [
                    dict(row)
                    for row in c.execute(
                        select(table)
                        .where(table.c.tenant_id == self.candidate.scope.tenant_id)
                        .order_by(*table.primary_key.columns)
                    ).mappings()
                ]
                for table in checked
            }


@pytest.fixture
def entry(candidate: Candidate, monkeypatch: pytest.MonkeyPatch) -> Entry:
    settings = SimpleNamespace(
        research_search_endpoint=SEARCH_ENDPOINT, research_subscriptions_enabled=False
    )
    value = Entry(candidate, settings)
    # Only this module's research settings are supplied. No business .env,
    # credentials, real search endpoint, live DNS or outbound client is loaded.
    monkeypatch.setattr(product_research, "get_settings", lambda: settings)

    def policy() -> ReachPolicy:
        return ReachPolicy(resolver=lambda _: ["93.184.216.34"])

    monkeypatch.setattr(product_research, "ReachPolicy", policy)
    monkeypatch.setattr(research_search, "ReachPolicy", policy)
    monkeypatch.setattr(reach, "ReachPolicy", policy)

    class SearchTransport:
        def __init__(self, *, total_timeout: int) -> None:
            assert total_timeout == 20

        def get(self, url: str) -> ReachResponse:
            parsed = urlsplit(url)
            assert (parsed.scheme, parsed.hostname, parsed.path) == (
                "https",
                "search.example.com",
                "/search",
            )
            value.search_calls.append(url)
            body = json.dumps(value.payload, ensure_ascii=False)
            return ReachResponse(value.search_status, body, "application/json", len(body.encode()))

    class CaptureTransport:
        def __init__(self, *, required_origin: tuple[str, str, int]) -> None:
            assert required_origin == ("https", "evidence.example.com", 443)

        def get(self, url: str) -> ReachResponse:
            assert url == PAGE_URL
            value.capture_calls.append(url)
            if value.after_capture_read is not None:
                value.after_capture_read()
            return ReachResponse(
                200,
                value.body,
                "text/plain",
                len(value.body.encode()),
                source_version="synthetic-v1",
                content_language="zh-CN",
            )

    monkeypatch.setattr(research_search, "PublicReachTransport", SearchTransport)
    monkeypatch.setattr(research_collection, "PublicReachTransport", CaptureTransport)
    return value


def test_pm_sources_search_capture_and_original_content_keep_actual_receipts(entry: Entry) -> None:
    candidate = entry.candidate
    user_id, headers = colleague(candidate)
    source = entry.source()
    assert source["owner_user_id"] == str(candidate.scope.owner_id)
    assert source["source_type"] == "web" and source["allowed_use"] == "internal_citation"
    sources = entry.get("/sources", headers)
    assert sources["search_available"] and not sources["subscription_available"]
    assert [row["id"] for row in sources["items"]] == [source["id"]]

    query = entry.query()
    observation = candidate.post(entry.base + "/searches", query, 201, headers)
    assert observation["status"] == "completed" and observation["hits"][0]["url"] == PAGE_URL
    assert observation["requested_by_user_id"] == str(user_id)
    assert observation["product_line_id"] == candidate.line["id"]
    assert (
        observation["response_digest"]
        == sha256(json.dumps(entry.payload, ensure_ascii=False).encode()).hexdigest()
    )
    assert parse_qs(urlsplit(entry.search_calls[0]).query) == {
        "q": [query["query"]],
        "format": ["json"],
        "categories": ["general"],
        "pageno": ["1"],
        "language": ["zh-CN"],
        "time_range": ["month"],
    }
    searched = entry.state()
    assert searched["evidence_snapshots"] == searched["evidence_contents"] == []
    assert candidate.post(entry.base + "/searches", query, 201, headers) == observation
    assert len(entry.search_calls) == 1 and entry.state() == searched
    assert entry.get("/searches", headers)["items"] == [observation]

    receipt = candidate.post(entry.base + "/capture", entry.capture(source), 201, headers)
    snapshot = receipt["snapshot"]
    expected = sha256(ORIGINAL_BODY.encode()).hexdigest()
    assert snapshot["source_id"] == source["id"] and snapshot["url"] == PAGE_URL
    assert snapshot["captured_by_user_id"] == str(user_id)
    assert snapshot["content_digest"] == expected and snapshot["taint"] == "untrusted_external"
    assert snapshot["source_version"] == "synthetic-v1"
    assert receipt["redirect_chain"] == [PAGE_URL] and not receipt["reused_existing"]
    content = entry.get(f"/evidence/{snapshot['id']}/content", headers)
    assert content["snapshot_id"] == snapshot["id"] and content["content_digest"] == expected
    assert content["content"] == ORIGINAL_BODY and content["byte_size"] == len(
        ORIGINAL_BODY.encode()
    )
    assert content["taint"] == "untrusted_external" and content["content_language"] == "zh-CN"
    captured = entry.state()
    assert len(captured["evidence_snapshots"]) == len(captured["evidence_contents"]) == 1
    repeated = candidate.post(entry.base + "/capture", entry.capture(source), 201, headers)
    assert repeated["reused_existing"] and repeated["snapshot"]["id"] == snapshot["id"]
    assert entry.state() == captured and len(entry.capture_calls) == 2
    assert captured["agent_runs"] == captured["model_invocations"] == []
    assert captured["findings"] == captured["product_source_files"] == []


@pytest.mark.parametrize("mode", ["not_configured", "unavailable", "no_results"])
def test_pm_search_unavailability_is_503_and_original_observation_replays_without_network(
    entry: Entry, mode: str
) -> None:
    candidate = entry.candidate
    entry.payload = {"results": []}
    if mode == "not_configured":
        entry.settings.research_search_endpoint = None
    elif mode == "unavailable":
        entry.search_status = 503
    sources = entry.get("/sources", candidate.headers)
    assert sources["search_available"] == (mode != "not_configured")
    query = entry.query()
    expected_code = "SEARCH_NOT_CONFIGURED" if mode == "not_configured" else "SEARCH_UNAVAILABLE"
    url = entry.base + "/searches"
    first = candidate.client.post(url, headers=candidate.headers, json=query)
    assert first.status_code == (201 if mode == "no_results" else 503), first.text
    assert first.headers["cache-control"] == "no-store"
    first_body = first.json()
    if mode != "no_results":
        detail = first_body["detail"]
        assert set(detail) == {"code", "message", "observation_id", "request_id"}
        assert detail["code"] == expected_code and detail["request_id"] == query["request_id"]
        assert "原查询" in detail["message"] and "新查询" in detail["message"]
    saved = entry.get("/searches", candidate.headers)["items"]
    (observation,) = saved
    assert observation["status"] == mode and observation["hits"] == []
    assert observation["request_id"] == query["request_id"]
    if mode != "no_results":
        assert observation["id"] == first_body["detail"]["observation_id"]
        assert observation["error_code"] == expected_code
    else:
        assert observation == first_body and observation["response_digest"]
    before_replay = entry.state()
    second = candidate.client.post(url, headers=candidate.headers, json=query)
    assert second.status_code == first.status_code and second.json() == first_body
    assert second.headers["cache-control"] == "no-store"
    assert entry.state() == before_replay
    assert len(entry.search_calls) == (0 if mode == "not_configured" else 1)
    assert not entry.capture_calls
    assert before_replay["evidence_snapshots"] == before_replay["evidence_contents"] == []
    assert before_replay["agent_runs"] == before_replay["model_invocations"] == []


def test_pm_current_line_revocation_hides_search_history_and_rejects_new_writes(
    entry: Entry,
) -> None:
    candidate = entry.candidate
    user_id, headers = colleague(candidate)
    source = entry.source()
    query = entry.query()
    candidate.post(entry.base + "/searches", query, 201, headers)
    with candidate.scope.engine.begin() as c:
        removed = c.execute(
            tables.product_line_members.delete().where(
                tables.product_line_members.c.tenant_id == candidate.scope.tenant_id,
                tables.product_line_members.c.product_line_id == UUID(candidate.line["id"]),
                tables.product_line_members.c.user_id == user_id,
            )
        )
        assert removed.rowcount == 1
    before = entry.state()
    assert entry.get("/searches", headers)["items"] == []
    for path, body in (("/searches", entry.query()), ("/capture", entry.capture(source))):
        denied = candidate.post(entry.base + path, body, 403, headers)
        assert denied["detail"] == {
            "code": "PRODUCT_WORK_FORBIDDEN",
            "message": "产品线不存在或无权访问",
        }
        assert entry.state() == before
    # Space access and shared source visibility remain legitimate; the engineer
    # still cannot manage a source merely by knowing its Space or original URL.
    assert entry.get("/sources", headers)["items"][0]["id"] == source["id"]
    candidate.post(
        entry.base + "/sources", {**entry.source_body(), "name": "越权新来源"}, 403, headers
    )
    assert entry.state() == before and len(entry.search_calls) == 1
    assert not entry.capture_calls


@pytest.mark.parametrize("revocation", ["line", "account"])
def test_pm_capture_rechecks_authority_after_transport_without_changing_saved_evidence(
    entry: Entry, revocation: str
) -> None:
    candidate = entry.candidate
    user_id, headers = colleague(candidate)
    source = entry.source()
    first = candidate.post(entry.base + "/capture", entry.capture(source), 201, headers)
    assert (
        entry.get(f"/evidence/{first['snapshot']['id']}/content", headers)["content"]
        == ORIGINAL_BODY
    )
    before = entry.state()
    entry.body = "不同合成新正文，不得在撤权后保存。"

    def revoke() -> None:
        with candidate.scope.engine.begin() as c:
            if revocation == "line":
                c.execute(
                    tables.product_line_members.delete().where(
                        tables.product_line_members.c.tenant_id == candidate.scope.tenant_id,
                        tables.product_line_members.c.product_line_id == UUID(candidate.line["id"]),
                        tables.product_line_members.c.user_id == user_id,
                    )
                )
            else:
                c.execute(
                    tables.users.update()
                    .where(
                        tables.users.c.tenant_id == candidate.scope.tenant_id,
                        tables.users.c.id == user_id,
                    )
                    .values(is_active=False)
                )

    entry.after_capture_read = revoke
    denied = candidate.post(entry.base + "/capture", entry.capture(source), 403, headers)
    assert denied["detail"]["code"] == "PRODUCT_WORK_FORBIDDEN"
    assert denied["detail"]["message"] == (
        "产品线不存在或无权访问"
        if revocation == "line"
        else "账号、租户或岗位授权已变化，采集已停止"
    )
    assert len(entry.capture_calls) == 2 and not entry.search_calls
    assert entry.state() == before
    assert before["agent_runs"] == before["model_invocations"] == before["findings"] == []
