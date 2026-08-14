from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Connection, create_engine, select, text

from app.ai.chat import ChatEvidenceRepository
from app.ai.embeddings import EmbeddingError, EmbeddingResult
from app.api.memories import get_embedding_gateway
from app.auth.passwords import PasswordService
from app.auth.roles import Role
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.main import app
from app.settings import get_settings

SERVER_ROOT = Path(__file__).resolve().parents[1]
TEST_JWT_SECRET = "test-only-jwt-secret-that-is-at-least-32-bytes"
PASSWORD = "correct horse battery staple"
SETUP_PAYLOAD = {
    "tenant_slug": "memory",
    "tenant_name": "Memory Tenant",
    "username": "owner",
    "password": PASSWORD,
    "display_name": "Memory Owner",
}


class FakeEmbeddingGateway:
    provider = "test-provider"
    model = "test-embedding-v1"
    dimensions = 3

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.inputs: list[str] = []

    def embed(self, value: str) -> EmbeddingResult:
        self.inputs.append(value)
        if self.fail:
            raise EmbeddingError("EMBEDDING_TRANSPORT_ERROR", "failed")
        normalized = value.lower()
        if "connector" in normalized:
            values = (1.0, 0.0, 0.0)
        elif "thermal" in normalized:
            values = (0.8, 0.2, 0.0)
        else:
            values = (0.0, 1.0, 0.0)
        return EmbeddingResult(provider=self.provider, model=self.model, values=values)


@pytest.fixture(autouse=True)
def isolated_memory_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
        yield test_url
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
        get_engine().dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "memory", "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed_user(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    owner_id: UUID,
    username: str,
    role: Role,
) -> UUID:
    user_id = uuid4()
    connection.execute(
        tables.users.insert(),
        {
            "id": user_id,
            "tenant_id": tenant_id,
            "username": username,
            "display_name": username.title(),
            "role": role.value,
            "password_hash": PasswordService().hash(PASSWORD),
        },
    )
    connection.execute(
        tables.project_members.insert(),
        {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "project_id": project_id,
            "user_id": user_id,
            "added_by_user_id": owner_id,
        },
    )
    return user_id


def seed_project_and_roles(
    database_url: str,
    tenant_id: UUID,
    owner_id: UUID,
) -> tuple[UUID, dict[str, UUID]]:
    requirement_id, case_id, workflow_id, stage_id, project_id = (uuid4() for _ in range(5))
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.requirements.insert(),
                {
                    "id": requirement_id,
                    "tenant_id": tenant_id,
                    "created_by_user_id": owner_id,
                    "code": "REQ-MEM",
                    "title": "Memory",
                    "status": "converted",
                },
            )
            connection.execute(
                tables.development_cases.insert(),
                {
                    "id": case_id,
                    "tenant_id": tenant_id,
                    "requirement_id": requirement_id,
                    "created_by_user_id": owner_id,
                    "code": "CASE-MEM",
                    "title": "Memory",
                    "status": "converted",
                },
            )
            connection.execute(
                tables.workflows.insert(),
                {"id": workflow_id, "tenant_id": tenant_id, "code": "memory", "name": "Memory"},
            )
            connection.execute(
                tables.stages.insert(),
                {
                    "id": stage_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "code": "mp",
                    "name": "MP",
                    "sequence": 1,
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": project_id,
                    "tenant_id": tenant_id,
                    "development_case_id": case_id,
                    "workflow_id": workflow_id,
                    "current_stage_id": stage_id,
                    "owner_user_id": owner_id,
                    "code": "PRJ-MEM",
                    "name": "Memory Project",
                    "status": "active",
                },
            )
            connection.execute(
                tables.project_members.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "user_id": owner_id,
                    "added_by_user_id": owner_id,
                },
            )
            users = {
                username: seed_user(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    owner_id=owner_id,
                    username=username,
                    role=role,
                )
                for username, role in (
                    ("engineer", Role.ENGINEER),
                    ("quality", Role.QUALITY),
                    ("reviewer", Role.QUALITY),
                    ("supplier", Role.SUPPLIER),
                )
            }
    finally:
        engine.dispose()
    return project_id, users


def draft_payload(title: str = "Thermal connector lesson") -> dict[str, object]:
    return {
        "title": title,
        "content": "Connector retention must be checked after thermal cycling.",
        "applicability": "Products using the C4 connector family.",
        "tags": ["connector", "thermal"],
    }


def test_verified_only_search_four_eyes_archive_and_event_audit_chain(
    client: TestClient,
    isolated_memory_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id, owner_id = UUID(setup["tenant"]["id"]), UUID(setup["user"]["id"])
    project_id, users = seed_project_and_roles(
        isolated_memory_database,
        tenant_id,
        owner_id,
    )
    gateway = FakeEmbeddingGateway()
    app.dependency_overrides[get_embedding_gateway] = lambda: gateway

    created = client.post(
        f"/api/projects/{project_id}/memories",
        headers=login(client, "engineer"),
        json=draft_payload(),
    )
    assert created.status_code == 201
    memory_id = created.json()["id"]
    assert created.json()["status"] == "draft"

    before = client.post(
        "/api/knowledge/search",
        headers=login(client, "engineer"),
        json={"project_id": str(project_id), "query": "connector"},
    )
    assert before.status_code == 200
    assert before.json() == {"source_status": "ready", "items": []}
    assert (
        client.post(
            f"/api/projects/{project_id}/memories/{memory_id}/verify",
            headers=login(client, "engineer"),
        ).status_code
        == 403
    )

    verified = client.post(
        f"/api/projects/{project_id}/memories/{memory_id}/verify",
        headers=login(client, "quality"),
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "verified"
    assert verified.json()["verified_by_user_id"] == str(users["quality"])
    assert "embedding" not in verified.json()

    search = client.post(
        "/api/knowledge/search",
        headers=login(client, "engineer"),
        json={"project_id": str(project_id), "query": "connector", "limit": 5},
    )
    assert search.status_code == 200
    assert [item["memory"]["id"] for item in search.json()["items"]] == [memory_id]
    assert search.json()["items"][0]["similarity"] == pytest.approx(1.0)
    assert search.json()["items"][0]["embedding_model"] == "test-embedding-v1"
    assert "embedding" not in search.json()["items"][0]["memory"]

    archived = client.post(
        f"/api/projects/{project_id}/memories/{memory_id}/archive",
        headers=login(client, "reviewer"),
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    after = client.post(
        "/api/knowledge/search",
        headers=login(client, "engineer"),
        json={"project_id": str(project_id), "query": "connector"},
    )
    assert after.status_code == 200
    assert after.json()["items"] == []
    assert (
        client.get(
            f"/api/projects/{project_id}/memories",
            headers=login(client, "supplier"),
        ).status_code
        == 403
    )

    engine = create_engine(psycopg_database_url(isolated_memory_database))
    try:
        with engine.connect() as connection:
            pairs = list(
                connection.execute(
                    select(tables.events.c.event_type, tables.audit_log.c.action)
                    .join(
                        tables.audit_log,
                        tables.audit_log.c.event_id == tables.events.c.event_id,
                    )
                    .where(
                        tables.events.c.tenant_id == tenant_id,
                        tables.events.c.entity_id == UUID(memory_id),
                    )
                    .order_by(tables.events.c.id)
                )
            )
    finally:
        engine.dispose()
    assert pairs == [
        ("MEMORY_DRAFT_CREATED", "memory.create"),
        ("MEMORY_VERIFIED", "memory.verify"),
        ("MEMORY_EMBEDDED", "memory.embed"),
        ("MEMORY_ARCHIVED", "memory.archive"),
    ]


def test_self_verification_and_embedding_failure_leave_draft_untrusted(
    client: TestClient,
    isolated_memory_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id, owner_id = UUID(setup["tenant"]["id"]), UUID(setup["user"]["id"])
    project_id, _ = seed_project_and_roles(isolated_memory_database, tenant_id, owner_id)
    gateway = FakeEmbeddingGateway()
    app.dependency_overrides[get_embedding_gateway] = lambda: gateway
    created = client.post(
        f"/api/projects/{project_id}/memories",
        headers=login(client, "quality"),
        json=draft_payload("Quality-created draft"),
    ).json()

    self_verify = client.post(
        f"/api/projects/{project_id}/memories/{created['id']}/verify",
        headers=login(client, "quality"),
    )
    assert self_verify.status_code == 409
    assert self_verify.json()["detail"]["code"] == "MEMORY_FOUR_EYES_REQUIRED"
    assert gateway.inputs == []

    failing = FakeEmbeddingGateway(fail=True)
    app.dependency_overrides[get_embedding_gateway] = lambda: failing
    failed = client.post(
        f"/api/projects/{project_id}/memories/{created['id']}/verify",
        headers=login(client, "reviewer"),
    )
    assert failed.status_code == 503
    assert failed.json()["detail"]["code"] == "EMBEDDING_TRANSPORT_ERROR"

    listed = client.get(
        f"/api/projects/{project_id}/memories?status=draft",
        headers=login(client, "reviewer"),
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [created["id"]]
    engine = create_engine(psycopg_database_url(isolated_memory_database))
    try:
        with engine.connect() as connection:
            assert connection.execute(select(tables.memory_embeddings.c.id)).all() == []
    finally:
        engine.dispose()


def test_closed_ncr_can_seed_one_project_bound_memory_draft(
    client: TestClient,
    isolated_memory_database: str,
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant_id, owner_id = UUID(setup["tenant"]["id"]), UUID(setup["user"]["id"])
    project_id, users = seed_project_and_roles(isolated_memory_database, tenant_id, owner_id)
    complaint_id, ncr_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    engine = create_engine(psycopg_database_url(isolated_memory_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.complaints.insert(),
                {
                    "id": complaint_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "reported_by_user_id": users["engineer"],
                    "owner_user_id": users["engineer"],
                    "closed_by_user_id": users["quality"],
                    "code": "CMP-MEM",
                    "title": "Connector",
                    "description": "Connector failure",
                    "source": "field",
                    "severity": "high",
                    "status": "closed",
                    "occurred_at": now,
                    "reported_at": now,
                    "resolution_summary": "CAPA effective",
                    "closed_at": now,
                },
            )
            connection.execute(
                tables.nonconformance_reports.insert(),
                {
                    "id": ncr_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "complaint_id": complaint_id,
                    "owner_user_id": users["quality"],
                    "created_by_user_id": users["quality"],
                    "closed_by_user_id": users["quality"],
                    "code": "NCR-MEM",
                    "nonconformity": "Connector retention",
                    "requirement_reference": "SPEC-1",
                    "severity": "high",
                    "status": "closed",
                    "target_date": now.date(),
                    "closed_at": now,
                },
            )
    finally:
        engine.dispose()

    created = client.post(
        f"/api/projects/{project_id}/memories/from-ncr/{ncr_id}",
        headers=login(client, "engineer"),
        json=draft_payload("Closed CAPA lesson"),
    )
    assert created.status_code == 201
    assert created.json()["source_ncr_id"] == str(ncr_id)
    assert created.json()["source_refs"] == [{"kind": "ncr", "reference": str(ncr_id)}]
    duplicate = client.post(
        f"/api/projects/{project_id}/memories/from-ncr/{ncr_id}",
        headers=login(client, "engineer"),
        json=draft_payload("Duplicate"),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "MEMORY_SOURCE_INVALID"

    gateway = FakeEmbeddingGateway()
    app.dependency_overrides[get_embedding_gateway] = lambda: gateway
    verified = client.post(
        f"/api/projects/{project_id}/memories/{created.json()['id']}/verify",
        headers=login(client, "quality"),
    )
    assert verified.status_code == 200
    engine = create_engine(psycopg_database_url(isolated_memory_database))
    try:
        evidence = ChatEvidenceRepository(engine, embedding_gateway=gateway).collect(
            tenant_id=tenant_id,
            project_id=project_id,
            question="What connector CAPA lesson was verified?",
        )
    finally:
        engine.dispose()
    memory_evidence = [item for item in evidence if item.entity == "memory"]
    assert [item.reference_id for item in memory_evidence] == [f"memory:{created.json()['id']}"]
    assert memory_evidence[0].href == (
        f"/knowledge?project={project_id}&memory={created.json()['id']}"
    )
