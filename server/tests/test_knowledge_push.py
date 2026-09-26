"""Proactive knowledge push tests (vNext V1-B9, axis 10)."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import RowMapping, Table, create_engine, select

from app.ai.embeddings import EmbeddingResult
from app.api.memories import get_embedding_gateway
from app.auth.passwords import PasswordService
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.memories import MemoryDraft, MemoryService, memory_review_digest
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


class KeywordEmbeddingGateway:
    """Deterministic 3-d embedding: axis 0 = bearing talk, axis 1 = packaging."""

    provider = "test-provider"
    model = "test-embedding-v1"
    dimensions = 3

    def embed(self, value: str) -> EmbeddingResult:
        text_value = value.lower()
        bearing = any(word in text_value for word in ("轴承", "bearing", "振动"))
        packaging = any(word in text_value for word in ("包装", "packaging", "纸箱"))
        if bearing and not packaging:
            values = (1.0, 0.0, 0.0)
        elif packaging and not bearing:
            values = (0.0, 1.0, 0.0)
        else:
            values = (0.0, 0.0, 1.0)
        return EmbeddingResult(provider=self.provider, model=self.model, values=values)


@pytest.fixture(autouse=True)
def isolated_push_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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
    app.dependency_overrides[get_embedding_gateway] = KeywordEmbeddingGateway
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


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
        self.gateway = KeywordEmbeddingGateway()

    def dispose(self) -> None:
        self.engine.dispose()

    def _insert(self, table: Table, values: dict[str, Any]) -> UUID:
        row_id: UUID = values.setdefault("id", uuid4())
        values.setdefault("tenant_id", self.tenant_id)
        with self.engine.begin() as connection:
            connection.execute(table.insert(), values)
        return row_id

    def user(self, username: str, role: str) -> UUID:
        return self._insert(
            tables.users,
            {
                "username": username,
                "display_name": username.title(),
                "role": role,
                "password_hash": self.password_hash,
            },
        )

    def project(self, code: str, *, name: str, member_ids: tuple[UUID, ...] = ()) -> UUID:
        workflow_id = self._insert(tables.workflows, {"code": f"WF-{code}", "name": "Workflow"})
        project_id = self._insert(
            tables.projects,
            {
                "workflow_id": workflow_id,
                "owner_user_id": self.owner_id,
                "code": code,
                "name": name,
                "description": name,
                "status": "active",
            },
        )
        for member_id in member_ids:
            self._insert(
                tables.project_members,
                {
                    "project_id": project_id,
                    "user_id": member_id,
                    "added_by_user_id": self.owner_id,
                },
            )
        return project_id

    def verified_memory(self, project_id: UUID, *, title: str, content: str) -> UUID:
        """Publish classified synthetic guidance through independent review."""
        verifier_id = self.user(f"verifier-{uuid4().hex[:6]}", "quality")
        service = MemoryService(self.engine)
        candidate = service.create(
            tenant_id=self.tenant_id,
            project_id=project_id,
            actor_user_id=self.owner_id,
            draft=MemoryDraft(title=title, content=content, knowledge_kind="design_rule"),
        )
        verified = service.verify(
            tenant_id=self.tenant_id,
            project_id=project_id,
            actor_user_id=verifier_id,
            memory_id=candidate.id,
            gateway=self.gateway,
            expected_review_digest=memory_review_digest(candidate),
        )
        assert verified.status == "verified"
        return verified.id

    def draft_memory(self, project_id: UUID, *, title: str, content: str) -> UUID:
        content_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        memory_id = self._insert(
            tables.memories,
            {
                "project_id": project_id,
                "created_by_user_id": self.owner_id,
                "title": title,
                "content": content,
                "tags": [],
                "source_refs": [],
                "content_sha256": content_sha,
                "status": "draft",
            },
        )
        embedding = self.gateway.embed(f"{title} {content}")
        self._insert(
            tables.memory_embeddings,
            {
                "project_id": project_id,
                "memory_id": memory_id,
                "created_by_user_id": self.owner_id,
                "provider": embedding.provider,
                "model": embedding.model,
                "dimensions": len(embedding.values),
                "content_sha256": content_sha,
                "embedding": list(embedding.values),
            },
        )
        return memory_id

    def pushes(self) -> list[RowMapping]:
        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    select(tables.knowledge_pushes).where(
                        tables.knowledge_pushes.c.tenant_id == self.tenant_id
                    )
                )
                .mappings()
                .all()
            )


def push(
    client: TestClient, headers: dict[str, str], project_id: UUID, *, kind: str, entity_id: UUID
) -> httpx2.Response:
    return client.get(
        f"/api/projects/{project_id}/knowledge-push"
        f"?context_kind={kind}&context_entity_id={entity_id}",
        headers=headers,
    )


def test_kickoff_pulls_relevant_lessons_from_other_projects(
    client: TestClient, isolated_push_database: str
) -> None:
    scope = Scope(client, isolated_push_database)
    try:
        headers = bearer_headers(client)
        past = scope.project("PRJ-PAST", name="上一代气泵")
        relevant = scope.verified_memory(
            past, title="轴承预紧力经验", content="轴承预紧不足会引起高频振动"
        )
        scope.verified_memory(past, title="包装经验", content="纸箱堆码高度限制")
        new_project = scope.project("PRJ-NEW", name="新一代气泵轴承振动改善")

        response = push(client, headers, new_project, kind="project_kickoff", entity_id=new_project)
        assert response.status_code == 200
        body = response.json()
        ids = [item["memory"]["id"] for item in body["items"]]
        assert ids == [str(relevant)], "only the bearing lesson is close enough"
        item = body["items"][0]
        # The value is that it came from a *different* project.
        assert item["source_project_id"] == str(past)
        assert item["already_seen"] is False
        assert item["rank"] == 1
        assert item["href"] == f"/knowledge?project={past}&memory={relevant}"
        assert len(scope.pushes()) == 1
    finally:
        scope.dispose()


def test_drafts_are_never_pushed(client: TestClient, isolated_push_database: str) -> None:
    scope = Scope(client, isolated_push_database)
    try:
        headers = bearer_headers(client)
        past = scope.project("PRJ-PAST", name="上一代气泵")
        scope.draft_memory(past, title="轴承草稿", content="轴承预紧不足会引起高频振动")
        new_project = scope.project("PRJ-NEW", name="新一代气泵轴承振动改善")

        response = push(client, headers, new_project, kind="project_kickoff", entity_id=new_project)
        assert response.status_code == 200
        assert response.json()["items"] == [], "unreviewed notes must not be presented as knowledge"
        assert scope.pushes() == []
    finally:
        scope.dispose()


def test_repeat_retrieval_marks_already_seen_without_duplicating_the_ledger(
    client: TestClient, isolated_push_database: str
) -> None:
    scope = Scope(client, isolated_push_database)
    try:
        headers = bearer_headers(client)
        past = scope.project("PRJ-PAST", name="上一代气泵")
        scope.verified_memory(past, title="轴承经验", content="轴承预紧不足引起振动")
        new_project = scope.project("PRJ-NEW", name="新一代气泵轴承振动改善")

        first = push(client, headers, new_project, kind="project_kickoff", entity_id=new_project)
        assert [item["already_seen"] for item in first.json()["items"]] == [False]

        second = push(client, headers, new_project, kind="project_kickoff", entity_id=new_project)
        assert [item["already_seen"] for item in second.json()["items"]] == [True]
        assert len(scope.pushes()) == 1, "re-running retrieval must not inflate the ledger"
        assert first.json()["items"][0]["push_id"] == second.json()["items"][0]["push_id"]
    finally:
        scope.dispose()


def test_engagement_drives_the_hit_rate_and_counts_once(
    client: TestClient, isolated_push_database: str
) -> None:
    scope = Scope(client, isolated_push_database)
    try:
        headers = bearer_headers(client)
        past = scope.project("PRJ-PAST", name="上一代气泵")
        scope.verified_memory(past, title="轴承经验", content="轴承预紧不足引起振动")
        new_project = scope.project("PRJ-NEW", name="新一代气泵轴承振动改善")
        pushed = push(
            client, headers, new_project, kind="project_kickoff", entity_id=new_project
        ).json()["items"][0]

        before = client.get("/api/knowledge/push-metrics", headers=headers).json()
        assert before["pushed_count"] == 1
        assert before["engaged_count"] == 0
        assert before["hit_rate_basis_points"] == 0

        engaged = client.post(f"/api/knowledge/pushes/{pushed['push_id']}/engage", headers=headers)
        assert engaged.status_code == 204
        # Re-opening the same suggestion must not inflate the citation count.
        assert (
            client.post(
                f"/api/knowledge/pushes/{pushed['push_id']}/engage", headers=headers
            ).status_code
            == 204
        )

        after = client.get("/api/knowledge/push-metrics", headers=headers).json()
        assert after["engaged_count"] == 1
        assert after["hit_rate_basis_points"] == 10_000
        assert after["by_context"]["project_kickoff"] == {"pushed": 1, "engaged": 1}

        missing = client.post(f"/api/knowledge/pushes/{uuid4()}/engage", headers=headers)
        assert missing.status_code == 404
    finally:
        scope.dispose()


def test_a_non_admin_only_sees_memories_from_projects_they_belong_to(
    client: TestClient, isolated_push_database: str
) -> None:
    scope = Scope(client, isolated_push_database)
    try:
        engineer = scope.user("engineer", "engineer")
        stranger_project = scope.project("PRJ-OTHER", name="别人的气泵")
        scope.verified_memory(stranger_project, title="轴承经验", content="轴承预紧不足引起振动")
        new_project = scope.project(
            "PRJ-NEW", name="新一代气泵轴承振动改善", member_ids=(engineer,)
        )
        engineer_headers = bearer_headers(client, username="engineer")

        blocked = push(
            client, engineer_headers, new_project, kind="project_kickoff", entity_id=new_project
        )
        assert blocked.status_code == 200
        assert blocked.json()["items"] == []

        # The owner, who can see every project, gets the same lesson.
        owner_view = push(
            client,
            bearer_headers(client),
            new_project,
            kind="project_kickoff",
            entity_id=new_project,
        )
        assert len(owner_view.json()["items"]) == 1
    finally:
        scope.dispose()


def test_unknown_context_and_missing_trigger_fail_closed(
    client: TestClient, isolated_push_database: str
) -> None:
    scope = Scope(client, isolated_push_database)
    try:
        headers = bearer_headers(client)
        project_id = scope.project("PRJ-NEW", name="新一代气泵")

        unknown = push(client, headers, project_id, kind="whatever", entity_id=project_id)
        assert unknown.status_code == 422
        assert unknown.json()["detail"]["code"] == "KNOWLEDGE_CONTEXT_UNKNOWN"

        missing = push(client, headers, project_id, kind="change_request", entity_id=uuid4())
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "KNOWLEDGE_CONTEXT_NOT_FOUND"
        assert scope.pushes() == []
    finally:
        scope.dispose()
