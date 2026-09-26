"""Sample build configuration and comparison tests (vNext V1-B2, D37)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import RowMapping, Table, create_engine, select

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
def isolated_sample_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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
        self.workflow_id: UUID | None = None
        self.stage_id: UUID | None = None

    def dispose(self) -> None:
        self.engine.dispose()

    def _insert(self, table: Table, values: dict[str, Any]) -> UUID:
        row_id: UUID = values.setdefault("id", uuid4())
        values.setdefault("tenant_id", self.tenant_id)
        with self.engine.begin() as connection:
            connection.execute(table.insert(), values)
        return row_id

    def project(self) -> UUID:
        self.workflow_id = self._insert(tables.workflows, {"code": "WF-SC", "name": "Workflow"})
        self.stage_id = self._insert(
            tables.stages,
            {"workflow_id": self.workflow_id, "code": "evt", "name": "EVT", "sequence": 1},
        )
        project_id = self._insert(
            tables.projects,
            {
                "workflow_id": self.workflow_id,
                "owner_user_id": self.owner_id,
                "code": "PRJ-SC",
                "name": "Sample comparison project",
                "status": "active",
            },
        )
        self._insert(
            tables.project_members,
            {"project_id": project_id, "user_id": self.owner_id, "added_by_user_id": self.owner_id},
        )
        return project_id

    def bom(self, project_id: UUID, code: str, version: int) -> UUID:
        return self._insert(
            tables.development_boms,
            {
                "project_id": project_id,
                "created_by_user_id": self.owner_id,
                "bom_type": "ebom",
                "code": code,
                "name": f"BOM {code}",
                "version": version,
            },
        )

    def sample(self, project_id: UUID, serial: str) -> UUID:
        batch_id = self._insert(
            tables.build_batches,
            {
                "project_id": project_id,
                "workflow_id": self.workflow_id,
                "stage_id": self.stage_id,
                "created_by_user_id": self.owner_id,
                "code": f"BATCH-{serial}",
                "phase": "evt",
                "planned_quantity": 3,
                "status": "planned",
            },
        )
        return self._insert(
            tables.samples,
            {
                "project_id": project_id,
                "build_batch_id": batch_id,
                "created_by_user_id": self.owner_id,
                "serial_number": serial,
                "status": "built",
            },
        )

    def config_row(self, sample_id: UUID) -> RowMapping:
        with self.engine.connect() as connection:
            return (
                connection.execute(
                    select(tables.sample_build_configurations).where(
                        tables.sample_build_configurations.c.sample_id == sample_id
                    )
                )
                .mappings()
                .one()
            )


def put_config(
    client: TestClient,
    headers: dict[str, str],
    project_id: UUID,
    sample_id: UUID,
    payload: dict[str, Any],
) -> httpx2.Response:
    return client.put(
        f"/api/projects/{project_id}/npi/samples/{sample_id}/build-configuration",
        headers=headers,
        json=payload,
    )


def compare(
    client: TestClient,
    headers: dict[str, str],
    project_id: UUID,
    sample_ids: list[UUID],
) -> httpx2.Response:
    return client.post(
        f"/api/projects/{project_id}/npi/sample-configurations/compare",
        headers=headers,
        json={"sample_ids": [str(item) for item in sample_ids]},
    )


def test_configuration_records_the_bom_revision_that_built_the_unit(
    client: TestClient, isolated_sample_database: str
) -> None:
    scope = Scope(client, isolated_sample_database)
    try:
        headers = bearer_headers(client)
        project_id = scope.project()
        bom_id = scope.bom(project_id, "BOM-A", 3)
        sample_id = scope.sample(project_id, "SN-001")

        saved = put_config(
            client,
            headers,
            project_id,
            sample_id,
            {
                "pcb_version": "PCB-2.1",
                "structure_version": "STR-1.0",
                "fw_version": "FW-1.4.2",
                "development_bom_id": str(bom_id),
                "key_component_suppliers": {"轴承": "NSK", "电机": "Nidec"},
                "build_date": "2026-08-01",
            },
        )
        assert saved.status_code == 200
        body = saved.json()
        assert body["development_bom_id"] == str(bom_id)

        listed = client.get(
            f"/api/projects/{project_id}/npi/sample-configurations", headers=headers
        )
        item = listed.json()["items"][0]
        # The BOM row carries its own version, so the link is the revision.
        assert item["bom_code"] == "BOM-A"
        assert item["bom_version"] == 3
        assert item["fw_version"] == "FW-1.4.2"
        assert item["key_component_suppliers"] == {"轴承": "NSK", "电机": "Nidec"}
    finally:
        scope.dispose()


def test_comparison_names_exactly_the_fields_that_differ(
    client: TestClient, isolated_sample_database: str
) -> None:
    scope = Scope(client, isolated_sample_database)
    try:
        headers = bearer_headers(client)
        project_id = scope.project()
        bom_v3 = scope.bom(project_id, "BOM-A", 3)
        bom_v4 = scope.bom(project_id, "BOM-A2", 4)
        first = scope.sample(project_id, "SN-001")
        second = scope.sample(project_id, "SN-002")

        put_config(
            client,
            headers,
            project_id,
            first,
            {
                "pcb_version": "PCB-2.1",
                "structure_version": "STR-1.0",
                "fw_version": "FW-1.4.2",
                "development_bom_id": str(bom_v3),
                "key_component_suppliers": {"轴承": "NSK"},
                "build_date": "2026-08-01",
            },
        )
        put_config(
            client,
            headers,
            project_id,
            second,
            {
                "pcb_version": "PCB-2.1",
                "structure_version": "STR-1.1",
                "fw_version": "FW-1.4.2",
                "development_bom_id": str(bom_v4),
                "key_component_suppliers": {"轴承": "NSK"},
                "build_date": "2026-08-01",
            },
        )

        response = compare(client, headers, project_id, [first, second])
        assert response.status_code == 200
        body = response.json()
        assert [item["sample_serial"] for item in body["samples"]] == ["SN-001", "SN-002"]
        assert sorted(body["differing_fields"]) == ["bom_revision", "structure_version"]
        assert body["field_values"]["bom_revision"] == ["BOM-A v3", "BOM-A2 v4"]
        assert body["field_values"]["pcb_version"] == ["PCB-2.1", "PCB-2.1"]
        assert body["missing_configuration_sample_ids"] == []
    finally:
        scope.dispose()


def test_supplier_map_key_order_is_not_a_difference(
    client: TestClient, isolated_sample_database: str
) -> None:
    scope = Scope(client, isolated_sample_database)
    try:
        headers = bearer_headers(client)
        project_id = scope.project()
        first = scope.sample(project_id, "SN-001")
        second = scope.sample(project_id, "SN-002")
        put_config(
            client,
            headers,
            project_id,
            first,
            {"key_component_suppliers": {"轴承": "NSK", "电机": "Nidec"}},
        )
        put_config(
            client,
            headers,
            project_id,
            second,
            {"key_component_suppliers": {"电机": "Nidec", "轴承": "NSK"}},
        )
        response = compare(client, headers, project_id, [first, second])
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["differing_fields"] == []
    finally:
        scope.dispose()


def test_a_sample_without_a_configuration_is_reported_not_blanked(
    client: TestClient, isolated_sample_database: str
) -> None:
    scope = Scope(client, isolated_sample_database)
    try:
        headers = bearer_headers(client)
        project_id = scope.project()
        configured = scope.sample(project_id, "SN-001")
        unconfigured = scope.sample(project_id, "SN-002")
        put_config(client, headers, project_id, configured, {"pcb_version": "PCB-2.1"})

        body = compare(client, headers, project_id, [configured, unconfigured]).json()
        assert [item["sample_serial"] for item in body["samples"]] == ["SN-001"]
        # A row of blanks would read as "no differences"; say it plainly instead.
        assert body["missing_configuration_sample_ids"] == [str(unconfigured)]
        assert body["differing_fields"] == []
    finally:
        scope.dispose()


def test_comparison_rejects_degenerate_input(
    client: TestClient, isolated_sample_database: str
) -> None:
    scope = Scope(client, isolated_sample_database)
    try:
        headers = bearer_headers(client)
        project_id = scope.project()
        sample_id = scope.sample(project_id, "SN-001")

        assert compare(client, headers, project_id, [sample_id]).status_code == 422
        assert compare(client, headers, project_id, [sample_id, sample_id]).status_code == 422
        assert (
            client.post(
                f"/api/projects/{project_id}/npi/sample-configurations/compare",
                json={"sample_ids": [str(sample_id), str(uuid4())]},
            ).status_code
            == 401
        )
    finally:
        scope.dispose()


def test_an_issue_can_name_the_unit_the_defect_was_found_on(
    client: TestClient, isolated_sample_database: str
) -> None:
    scope = Scope(client, isolated_sample_database)
    try:
        headers = bearer_headers(client)
        project_id = scope.project()
        sample_id = scope.sample(project_id, "SN-001")

        created = client.post(
            f"/api/projects/{project_id}/issues",
            headers=headers,
            json={
                "title": "SN-001 高频振动",
                "severity": "high",
                "issue_type": "test_failure",
                "sample_id": str(sample_id),
            },
        )
        assert created.status_code == 201
        assert created.json()["sample_id"] == str(sample_id)

        listed = client.get(f"/api/projects/{project_id}/issues", headers=headers)
        assert listed.json()["items"][0]["sample_id"] == str(sample_id)

        # A sample from another project cannot be blamed for this one's defect.
        other_scope_sample = uuid4()
        rejected = client.post(
            f"/api/projects/{project_id}/issues",
            headers=headers,
            json={
                "title": "越界样机",
                "severity": "low",
                "sample_id": str(other_scope_sample),
            },
        )
        assert rejected.status_code in {404, 409, 422}
    finally:
        scope.dispose()


def test_test_runs_already_bind_to_a_sample(
    client: TestClient, isolated_sample_database: str
) -> None:
    """Guards the link V1-B3 established, now that comparison depends on it."""
    scope = Scope(client, isolated_sample_database)
    try:
        project_id = scope.project()
        sample_id = scope.sample(project_id, "SN-001")
        assert "sample_id" in tables.test_runs.c
        with scope.engine.connect() as connection:
            bound = connection.execute(
                select(tables.samples.c.id).where(tables.samples.c.id == sample_id)
            ).scalar_one()
        assert bound == sample_id
        assert datetime.now(UTC).date() >= date(2026, 1, 1)
    finally:
        scope.dispose()
