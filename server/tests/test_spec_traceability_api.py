"""Requirement/spec verification traceability tests (vNext V1-B1)."""

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
from sqlalchemy import Table, create_engine

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
NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated_traceability_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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


def bearer_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": "owner", "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class Scope:
    def __init__(self, client: TestClient, database_url: str) -> None:
        setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
        self.tenant_id = UUID(setup["tenant"]["id"])
        self.owner_id = UUID(setup["user"]["id"])
        self.engine = create_engine(psycopg_database_url(database_url))

    def dispose(self) -> None:
        self.engine.dispose()

    def _insert(self, table: Table, values: dict[str, Any]) -> UUID:
        row_id: UUID = values.setdefault("id", uuid4())
        values.setdefault("tenant_id", self.tenant_id)
        with self.engine.begin() as connection:
            connection.execute(table.insert(), values)
        return row_id

    def requirement(self, code: str, *, tier: str = "customer", parent: UUID | None = None) -> UUID:
        return self._insert(
            tables.requirements,
            {
                "created_by_user_id": self.owner_id,
                "code": code,
                "title": f"Requirement {code}",
                "tier": tier,
                "parent_requirement_id": parent,
                "status": "approved",
            },
        )

    def project_with_case(self, requirement_id: UUID) -> UUID:
        case_id = self._insert(
            tables.development_cases,
            {
                "requirement_id": requirement_id,
                "code": "CASE-1",
                "title": "Pump case",
                "status": "converted",
            },
        )
        workflow_id = self._insert(tables.workflows, {"code": "WF-TRACE", "name": "Workflow"})
        self.workflow_id = workflow_id
        self.stage_id = self._insert(
            tables.stages,
            {"workflow_id": workflow_id, "code": "evt", "name": "EVT", "sequence": 1},
        )
        project_id = self._insert(
            tables.projects,
            {
                "development_case_id": case_id,
                "workflow_id": workflow_id,
                "owner_user_id": self.owner_id,
                "code": "PRJ-TRACE",
                "name": "Traceability project",
                "status": "active",
            },
        )
        self._insert(
            tables.project_members,
            {"project_id": project_id, "user_id": self.owner_id, "added_by_user_id": self.owner_id},
        )
        return project_id

    def spec(
        self,
        project_id: UUID,
        code: str,
        *,
        requirement_id: UUID | None = None,
        criticality: str = "standard",
        verification_method: str | None = None,
        updated_at: datetime = NOW,
    ) -> UUID:
        return self._insert(
            tables.specifications,
            {
                "project_id": project_id,
                "created_by_user_id": self.owner_id,
                "code": code,
                "title": f"Spec {code}",
                "requirement_id": requirement_id,
                "criticality": criticality,
                "verification_method": verification_method,
                "created_at": NOW - timedelta(days=1),
                "updated_at": updated_at,
            },
        )

    def test_case(
        self,
        project_id: UUID,
        specification_id: UUID,
        *,
        status: str,
        executed_at: datetime | None,
    ) -> UUID:
        plan_id = getattr(self, "_plan_id", None)
        if plan_id is None:
            plan_id = self._insert(
                tables.test_plans,
                {
                    "project_id": project_id,
                    "workflow_id": self.workflow_id,
                    "stage_id": self.stage_id,
                    "created_by_user_id": self.owner_id,
                    "phase": "evt",
                    "title": "EVT plan",
                    "sample_size": 3,
                    "status": "active",
                },
            )
            self._plan_id = plan_id
        return self._insert(
            tables.test_cases,
            {
                "project_id": project_id,
                "plan_id": plan_id,
                "specification_id": specification_id,
                "created_by_user_id": self.owner_id,
                "title": f"Case {uuid4().hex[:6]}",
                "category": "performance",
                "acceptance_criteria": "Meets spec",
                "severity": "major",
                "status": status,
                "executed_by_user_id": self.owner_id if executed_at else None,
                "executed_at": executed_at,
            },
        )


def test_spec_create_carries_traceability_fields(
    client: TestClient, isolated_traceability_database: str
) -> None:
    scope = Scope(client, isolated_traceability_database)
    try:
        root = scope.requirement("REQ-ROOT")
        product_requirement = scope.requirement("REQ-PROD", tier="product", parent=root)
        project_id = scope.project_with_case(root)
        headers = bearer_headers(client)

        created = client.post(
            f"/api/projects/{project_id}/product-engineering/specifications",
            headers=headers,
            json={
                "code": "SPEC-42",
                "title": "Noise limit",
                "requirement_id": str(product_requirement),
                "owner_user_id": str(scope.owner_id),
                "verification_method": "Anechoic chamber test per QP-7",
                "acceptance_criteria": "<= 45 dB at 1m",
                "criticality": "key",
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["requirement_id"] == str(product_requirement)
        assert body["criticality"] == "key"
        assert body["verification_method"].startswith("Anechoic")
    finally:
        scope.dispose()


def test_coverage_buckets_are_deterministic(
    client: TestClient, isolated_traceability_database: str
) -> None:
    scope = Scope(client, isolated_traceability_database)
    try:
        root = scope.requirement("REQ-ROOT")
        scope.requirement("REQ-GAP", tier="product", parent=root)
        covered_child = scope.requirement("REQ-OK", tier="product", parent=root)
        project_id = scope.project_with_case(root)

        verified = scope.spec(
            project_id,
            "SPEC-VERIFIED",
            requirement_id=covered_child,
            criticality="key",
            verification_method="Bench test",
        )
        scope.test_case(project_id, verified, status="passed", executed_at=NOW)

        unverified = scope.spec(
            project_id, "SPEC-UNVERIFIED", criticality="key", verification_method=None
        )
        del unverified

        failed = scope.spec(
            project_id, "SPEC-FAILED", criticality="key", verification_method="Leak test"
        )
        scope.test_case(project_id, failed, status="failed", executed_at=NOW)

        stale = scope.spec(
            project_id,
            "SPEC-STALE",
            criticality="key",
            verification_method="Thermal test",
            updated_at=NOW + timedelta(days=2),
        )
        scope.test_case(project_id, stale, status="passed", executed_at=NOW)

        headers = bearer_headers(client)
        coverage = client.get(
            f"/api/projects/{project_id}/product-engineering/spec-coverage", headers=headers
        )
        assert coverage.status_code == 200
        body = coverage.json()

        without_spec = {item["code"] for item in body["requirements_without_spec"]}
        assert without_spec == {"REQ-ROOT", "REQ-GAP"}
        assert {item["code"] for item in body["key_specs_unverified"]} == {"SPEC-UNVERIFIED"}
        assert {item["code"] for item in body["failed_verification"]} == {"SPEC-FAILED"}
        assert {item["code"] for item in body["retest_needed"]} == {"SPEC-STALE"}
    finally:
        scope.dispose()
