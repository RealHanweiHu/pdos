"""Research source and evidence snapshot tests (vNext V2-7, C8)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Table, create_engine, select, text
from sqlalchemy.exc import DBAPIError

from app.auth.passwords import PasswordService
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.main import app
from app.settings import get_settings
from tests.db_cleanup import clear_test_tenants

SERVER_ROOT = Path(__file__).resolve().parents[1]
TEST_JWT_SECRET = "test-only-jwt-secret-that-is-at-least-32-bytes"
PASSWORD = "correct horse battery staple"
SETUP_PAYLOAD = {
    "tenant_slug": "beepump",
    "tenant_name": "Beehive Technology",
    "username": "owner",
    "password": PASSWORD,
    "display_name": "Initial Owner",
}


@pytest.fixture(autouse=True)
def isolated_evidence_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    test_url = configured_test_database_url()
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("JWT_ISSUER", "pdos-test")
    monkeypatch.setenv("JWT_AUDIENCE", "pdos-test-client")
    get_settings.cache_clear()
    get_engine.cache_clear()
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            clear_test_tenants(connection)
        yield test_url
    finally:
        engine.dispose()
        get_engine().dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def bearer_headers(client: TestClient, *, username: str = "owner") -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class Scope:
    def __init__(self, client: TestClient, database_url: str) -> None:
        setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
        self.tenant_id = UUID(setup["tenant"]["id"])
        self.owner_id = UUID(setup["user"]["id"])
        self.engine = create_engine(psycopg_database_url(database_url))
        self.password_hash = PasswordService().hash(PASSWORD)

    def dispose(self) -> None:
        self.engine.dispose()

    def user(self, username: str, role: str) -> UUID:
        values: dict[str, Any] = {
            "id": uuid4(),
            "tenant_id": self.tenant_id,
            "username": username,
            "display_name": username.title(),
            "role": role,
            "password_hash": self.password_hash,
        }
        table: Table = tables.users
        with self.engine.begin() as connection:
            connection.execute(table.insert(), values)
        user_id: UUID = values["id"]
        return user_id


@pytest.fixture
def scope(client: TestClient, isolated_evidence_database: str) -> Iterator[Scope]:
    built = Scope(client, isolated_evidence_database)
    try:
        yield built
    finally:
        built.dispose()


def create_source(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "竞品官网",
        "source_type": "web",
        "allowed_use": "internal_analysis",
        "collection_frequency": "weekly",
        "trust_tier": "public",
        "base_url": "https://example.com/products",
        "license_note": "公开页面，仅内部分析",
    }
    body.update(overrides)
    response = client.post("/api/evidence/sources", json=body, headers=headers)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def capture(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"content": "额定气压 8 bar，噪声 62 dB。"}
    body.update(overrides)
    response = client.post("/api/evidence/snapshots", json=body, headers=headers)
    assert response.status_code == 201, response.text
    captured: dict[str, Any] = response.json()
    return captured


def test_a_source_records_licence_use_frequency_and_retention(
    client: TestClient, scope: Scope
) -> None:
    headers = bearer_headers(client)
    source = create_source(client, headers)

    assert source["allowed_use"] == "internal_analysis"
    assert source["collection_frequency"] == "weekly"
    assert source["retention_policy"] == "standard"
    assert source["license_note"] == "公开页面，仅内部分析"
    assert source["owner_user_id"] == str(scope.owner_id)

    with scope.engine.connect() as connection:
        actions = [
            row.action
            for row in connection.execute(
                select(tables.audit_log.c.action).where(
                    tables.audit_log.c.tenant_id == scope.tenant_id
                )
            ).all()
        ]
    assert "research_source.created" in actions


def test_a_remote_source_without_a_base_url_is_refused(client: TestClient, scope: Scope) -> None:
    """Without a base URL the licence scope cannot be audited later."""
    headers = bearer_headers(client)
    response = client.post(
        "/api/evidence/sources",
        json={
            "name": "无址来源",
            "source_type": "web",
            "allowed_use": "internal_analysis",
            "collection_frequency": "weekly",
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "EVIDENCE_INVALID"


def test_web_material_is_born_untrusted_and_cannot_be_captured_verified(
    client: TestClient, scope: Scope
) -> None:
    """D25: external content is labelled, not blocked — and never self-declared clean."""
    headers = bearer_headers(client)
    source = create_source(client, headers)

    snapshot = capture(client, headers, source_id=source["id"])
    assert snapshot["taint"] == "untrusted_external"
    assert snapshot["trust_tier"] == "public"

    refused = client.post(
        "/api/evidence/snapshots",
        json={
            "content": "自称可信的外部内容",
            "source_id": source["id"],
            "taint": "verified",
        },
        headers=headers,
    )
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "EVIDENCE_INVALID"


def test_an_internal_upload_with_no_source_is_internal(client: TestClient, scope: Scope) -> None:
    headers = bearer_headers(client)
    snapshot = capture(client, headers, content="内部访谈纪要")
    assert snapshot["source_id"] is None
    assert snapshot["taint"] == "internal"
    assert snapshot["trust_tier"] == "unknown"


def test_recapturing_identical_bytes_returns_the_same_snapshot(
    client: TestClient, scope: Scope
) -> None:
    headers = bearer_headers(client)
    source = create_source(client, headers)

    first = capture(client, headers, source_id=source["id"], source_version="2026-08")
    second = capture(client, headers, source_id=source["id"], source_version="2026-08")

    assert first["reused_existing"] is False
    assert second["reused_existing"] is True
    assert second["id"] == first["id"]

    listed = client.get("/api/evidence/snapshots", headers=headers).json()["items"]
    assert len(listed) == 1


def test_a_new_source_version_is_a_separate_observation(client: TestClient, scope: Scope) -> None:
    """Same bytes at a different source version is a re-confirmation, not a duplicate."""
    headers = bearer_headers(client)
    source = create_source(client, headers)

    august = capture(client, headers, source_id=source["id"], source_version="2026-08")
    september = capture(client, headers, source_id=source["id"], source_version="2026-09")

    assert september["id"] != august["id"]
    assert september["reused_existing"] is False


def test_a_snapshot_is_superseded_rather_than_rewritten(client: TestClient, scope: Scope) -> None:
    headers = bearer_headers(client)
    source = create_source(client, headers)
    old = capture(client, headers, source_id=source["id"], source_version="2026-08")
    new = capture(
        client,
        headers,
        source_id=source["id"],
        source_version="2026-09",
        content="额定气压 9 bar，噪声 60 dB。",
    )

    superseded = client.post(
        f"/api/evidence/snapshots/{old['id']}/supersede",
        json={"superseded_by_id": new["id"]},
        headers=headers,
    )
    assert superseded.status_code == 200
    assert superseded.json()["superseded_by_id"] == new["id"]
    # A superseded snapshot is stale by definition, regardless of freshness.
    assert superseded.json()["is_stale"] is True

    twice = client.post(
        f"/api/evidence/snapshots/{old['id']}/supersede",
        json={"superseded_by_id": new["id"]},
        headers=headers,
    )
    assert twice.status_code == 409
    assert twice.json()["detail"]["code"] == "EVIDENCE_SNAPSHOT_IMMUTABLE"

    current = client.get(
        "/api/evidence/snapshots?include_superseded=false", headers=headers
    ).json()["items"]
    assert [item["id"] for item in current] == [new["id"]]


def test_the_database_itself_refuses_to_rewrite_a_captured_snapshot(
    client: TestClient, scope: Scope
) -> None:
    """快照不可静默覆盖 must hold against a direct SQL write, not just the service."""
    headers = bearer_headers(client)
    snapshot = capture(client, headers)

    with scope.engine.begin() as connection, pytest.raises(DBAPIError) as rewrite:
        connection.execute(
            text(
                "UPDATE cehub_evidence.evidence_snapshots "
                "SET content_digest = repeat('a', 64) WHERE id = :id"
            ),
            {"id": snapshot["id"]},
        )
    assert "immutable" in str(rewrite.value)

    with scope.engine.begin() as connection, pytest.raises(DBAPIError) as retime:
        connection.execute(
            text("UPDATE cehub_evidence.evidence_snapshots SET captured_at = now() WHERE id = :id"),
            {"id": snapshot["id"]},
        )
    assert "immutable" in str(retime.value)


def test_a_conflict_is_recorded_with_the_disagreement_stated(
    client: TestClient, scope: Scope
) -> None:
    headers = bearer_headers(client)
    official = create_source(client, headers, name="官方规格", trust_tier="official")
    forum = create_source(
        client,
        headers,
        name="用户论坛",
        trust_tier="community",
        base_url="https://forum.example.com",
    )
    a = capture(client, headers, source_id=official["id"], content="额定气压 8 bar")
    b = capture(client, headers, source_id=forum["id"], content="实测气压 6.5 bar")

    recorded = client.post(
        f"/api/evidence/snapshots/{a['id']}/conflict",
        json={"conflicts_with_id": b["id"], "note": "官方标称与用户实测相差 1.5 bar"},
        headers=headers,
    )
    assert recorded.status_code == 200
    assert recorded.json()["conflicts_with_id"] == b["id"]
    assert "1.5 bar" in recorded.json()["conflict_note"]

    blank = client.post(
        f"/api/evidence/snapshots/{b['id']}/conflict",
        json={"conflicts_with_id": a["id"], "note": "   "},
        headers=headers,
    )
    assert blank.status_code == 400


def test_freshness_expiry_marks_a_snapshot_stale(client: TestClient, scope: Scope) -> None:
    headers = bearer_headers(client)
    expired_at = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    fresh_at = (datetime.now(UTC) + timedelta(days=30)).isoformat()

    stale = capture(client, headers, content="去年的价格表", freshness_expires_at=expired_at)
    current = capture(client, headers, content="本月的价格表", freshness_expires_at=fresh_at)

    assert stale["is_stale"] is True
    assert current["is_stale"] is False


def test_engineers_capture_but_cannot_define_sources(client: TestClient, scope: Scope) -> None:
    owner_headers = bearer_headers(client)
    scope.user("engineer", "engineer")
    engineer_headers = bearer_headers(client, username="engineer")
    create_source(client, owner_headers)

    assert client.get("/api/evidence/sources", headers=engineer_headers).status_code == 200
    assert (
        client.post(
            "/api/evidence/snapshots",
            json={"content": "工程师上传的测量记录"},
            headers=engineer_headers,
        ).status_code
        == 201
    )
    denied = client.post(
        "/api/evidence/sources",
        json={
            "name": "工程师自建来源",
            "source_type": "file",
            "allowed_use": "internal_analysis",
            "collection_frequency": "on_demand",
        },
        headers=engineer_headers,
    )
    assert denied.status_code == 403


def test_suppliers_cannot_reach_the_evidence_base(client: TestClient, scope: Scope) -> None:
    scope.user("vendor", "supplier")
    supplier_headers = bearer_headers(client, username="vendor")

    assert client.get("/api/evidence/sources", headers=supplier_headers).status_code == 403
    assert client.get("/api/evidence/snapshots", headers=supplier_headers).status_code == 403


def test_snapshots_are_tenant_bound(client: TestClient, scope: Scope) -> None:
    headers = bearer_headers(client)
    capture(client, headers)

    unknown = client.get(f"/api/evidence/snapshots/{uuid4()}", headers=headers)
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "EVIDENCE_SNAPSHOT_NOT_FOUND"
