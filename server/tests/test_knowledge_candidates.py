"""Issue closure → knowledge candidate tests (vNext V1-B7, I10)."""

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

from app.ai.embeddings import EmbeddingResult
from app.api.memories import get_embedding_gateway
from app.auth.passwords import PasswordService
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.knowledge_candidates import build_candidate_draft
from app.domain.knowledge_learning import KnowledgeLearningWorker
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
def isolated_candidate_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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


class FakeEmbeddingGateway:
    """Publishing a verified memory embeds it; the vector itself is not under test."""

    provider = "test-provider"
    model = "test-embedding-v1"
    dimensions = 3

    def embed(self, value: str) -> EmbeddingResult:
        return EmbeddingResult(provider=self.provider, model=self.model, values=(0.0, 1.0, 0.0))


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_embedding_gateway] = FakeEmbeddingGateway
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

    def project(self, *, member_ids: tuple[UUID, ...]) -> UUID:
        workflow_id = self._insert(tables.workflows, {"code": "WF-KC", "name": "Workflow"})
        project_id = self._insert(
            tables.projects,
            {
                "workflow_id": workflow_id,
                "owner_user_id": self.owner_id,
                "code": "PRJ-KC",
                "name": "Knowledge candidate project",
                "status": "active",
            },
        )
        for member_id in (self.owner_id, *member_ids):
            self._insert(
                tables.project_members,
                {
                    "project_id": project_id,
                    "user_id": member_id,
                    "added_by_user_id": self.owner_id,
                },
            )
        return project_id

    def issue(
        self,
        project_id: UUID,
        *,
        owner: UUID,
        verifier: UUID,
        root_cause: str | None = "轴承预紧力不足导致高频振动",
        resolution: str | None = "改用 P4 级轴承并把预紧力矩写入 SOP",
    ) -> UUID:
        return self._insert(
            tables.issues,
            {
                "project_id": project_id,
                "reported_by_user_id": self.owner_id,
                "owner_user_id": owner,
                "verifier_user_id": verifier,
                "title": "叶轮高频振动",
                "issue_type": "engineering",
                "status": "action",
                "severity": "high",
                "root_cause": root_cause,
                "resolution": resolution,
                "closure_criteria": "连续 3 台样机振动值低于 4.5 mm/s",
                "target_date": date(2026, 9, 30),
            },
        )

    def capture(self, project_id: UUID) -> dict[str, Any]:
        # Run the actual durable collector after the business transaction has
        # committed. It creates drafts deterministically without a model call.
        return KnowledgeLearningWorker(self.engine).run_once(
            tenant_id=self.tenant_id, project_id=project_id
        )

    def memories(self) -> list[RowMapping]:
        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    select(tables.memories).where(tables.memories.c.tenant_id == self.tenant_id)
                )
                .mappings()
                .all()
            )


def close_issue(
    client: TestClient, headers: dict[str, str], project_id: UUID, issue_id: UUID
) -> httpx2.Response:
    submitted = client.post(
        f"/api/projects/{project_id}/issues/{issue_id}/transitions",
        headers=headers,
        json={"to_status": "verification"},
    )
    assert submitted.status_code == 200, submitted.json()
    return submitted


def test_closing_an_issue_drafts_a_candidate_that_keeps_source_and_evidence(
    client: TestClient, isolated_candidate_database: str
) -> None:
    scope = Scope(client, isolated_candidate_database)
    try:
        owner = scope.user("owner_engineer", "engineer")
        verifier = scope.user("verifier_quality", "quality")
        project_id = scope.project(member_ids=(owner, verifier))
        issue_id = scope.issue(project_id, owner=owner, verifier=verifier)

        owner_headers = bearer_headers(client, username="owner_engineer")
        verifier_headers = bearer_headers(client, username="verifier_quality")
        close_issue(client, owner_headers, project_id, issue_id)
        closed = client.post(
            f"/api/projects/{project_id}/issues/{issue_id}/transitions",
            headers=verifier_headers,
            json={"to_status": "closed", "closure_evidence_ref": "doc://vibration-report-3"},
        )
        assert closed.status_code == 200

        assert scope.memories() == []
        assert scope.capture(project_id)["state"] == "created"
        candidates = scope.memories()
        assert len(candidates) == 1
        candidate = candidates[0]
        # Free zone: it lands as a draft and changes no truth on its own.
        assert candidate["status"] == "draft"
        assert candidate["source_issue_id"] == issue_id
        assert candidate["title"] == "经验：叶轮高频振动"
        assert "轴承预紧力不足" in candidate["content"]
        assert "P4 级轴承" in candidate["content"]
        refs = {(ref["kind"], ref["reference"]) for ref in candidate["source_refs"]}
        assert ("issue", str(issue_id)) in refs
        assert ("closure_evidence", "doc://vibration-report-3") in refs
    finally:
        scope.dispose()


def test_reopening_and_reclosing_does_not_mint_a_second_candidate(
    client: TestClient, isolated_candidate_database: str
) -> None:
    scope = Scope(client, isolated_candidate_database)
    try:
        owner = scope.user("owner_engineer", "engineer")
        verifier = scope.user("verifier_quality", "quality")
        project_id = scope.project(member_ids=(owner, verifier))
        issue_id = scope.issue(project_id, owner=owner, verifier=verifier)
        owner_headers = bearer_headers(client, username="owner_engineer")
        verifier_headers = bearer_headers(client, username="verifier_quality")

        close_issue(client, owner_headers, project_id, issue_id)
        client.post(
            f"/api/projects/{project_id}/issues/{issue_id}/transitions",
            headers=verifier_headers,
            json={"to_status": "closed", "closure_evidence_ref": "doc://report-1"},
        )
        assert scope.capture(project_id)["state"] == "created"
        assert len(scope.memories()) == 1

        reopened = client.post(
            f"/api/projects/{project_id}/issues/{issue_id}/transitions",
            headers=verifier_headers,
            json={"to_status": "action", "comment": "现场复现"},
        )
        assert reopened.status_code == 200
        close_issue(client, owner_headers, project_id, issue_id)
        client.post(
            f"/api/projects/{project_id}/issues/{issue_id}/transitions",
            headers=verifier_headers,
            json={"to_status": "closed", "closure_evidence_ref": "doc://report-2"},
        )
        assert scope.capture(project_id)["state"] == "duplicate"
        assert len(scope.memories()) == 1, "reclosing must not duplicate the candidate"
    finally:
        scope.dispose()


def test_a_closure_with_nothing_recorded_produces_no_candidate(
    client: TestClient, isolated_candidate_database: str
) -> None:
    scope = Scope(client, isolated_candidate_database)
    try:
        owner = scope.user("owner_engineer", "engineer")
        verifier = scope.user("verifier_quality", "quality")
        project_id = scope.project(member_ids=(owner, verifier))
        issue_id = scope.issue(
            project_id, owner=owner, verifier=verifier, root_cause=None, resolution=None
        )
        owner_headers = bearer_headers(client, username="owner_engineer")
        verifier_headers = bearer_headers(client, username="verifier_quality")

        close_issue(client, owner_headers, project_id, issue_id)
        closed = client.post(
            f"/api/projects/{project_id}/issues/{issue_id}/transitions",
            headers=verifier_headers,
            json={"to_status": "closed", "closure_evidence_ref": "doc://report-1"},
        )
        assert closed.status_code == 200
        result = scope.capture(project_id)
        assert result["state"] == "skipped"
        assert result["reason"] == "nothing_learned"
        assert scope.memories() == [], "an empty note is worse than none"
    finally:
        scope.dispose()


def test_publishing_the_candidate_still_needs_a_second_person(
    client: TestClient, isolated_candidate_database: str
) -> None:
    scope = Scope(client, isolated_candidate_database)
    try:
        owner = scope.user("owner_engineer", "engineer")
        verifier = scope.user("verifier_quality", "quality")
        project_id = scope.project(member_ids=(owner, verifier))
        issue_id = scope.issue(project_id, owner=owner, verifier=verifier)
        owner_headers = bearer_headers(client, username="owner_engineer")
        verifier_headers = bearer_headers(client, username="verifier_quality")

        close_issue(client, owner_headers, project_id, issue_id)
        client.post(
            f"/api/projects/{project_id}/issues/{issue_id}/transitions",
            headers=verifier_headers,
            json={"to_status": "closed", "closure_evidence_ref": "doc://report-1"},
        )
        assert scope.capture(project_id)["state"] == "created"
        candidate = client.get(
            f"/api/projects/{project_id}/memories", headers=verifier_headers
        ).json()["items"][0]
        memory_id = candidate["id"]
        classified = client.patch(
            f"/api/projects/{project_id}/memories/{memory_id}",
            headers=verifier_headers,
            json={
                "title": candidate["title"],
                "content": candidate["content"],
                "applicability": candidate["applicability"],
                "tags": candidate["tags"],
                "knowledge_kind": "design_rule",
                "expected_review_digest": candidate["review_digest"],
            },
        )
        assert classified.status_code == 200, classified.text
        review = {"expected_review_digest": classified.json()["review_digest"]}

        # The closer authored the candidate, so they cannot also publish it.
        self_publish = client.post(
            f"/api/projects/{project_id}/memories/{memory_id}/verify",
            headers=verifier_headers,
            json=review,
        )
        assert self_publish.status_code == 409

        # The tenant owner is a different person and holds memory.verify.
        published = client.post(
            f"/api/projects/{project_id}/memories/{memory_id}/verify",
            headers=bearer_headers(client),
            json=review,
        )
        assert published.status_code == 200, published.text
        assert published.json()["status"] == "verified"
    finally:
        scope.dispose()


def test_candidate_body_is_assembled_deterministically() -> None:
    draft = build_candidate_draft(
        title="叶轮高频振动",
        issue_type="engineering",
        severity="high",
        root_cause="  轴承预紧力不足  ",
        resolution=None,
        closure_criteria="振动值低于 4.5 mm/s",
    )
    assert draft is not None
    assert draft.content == "## 根因\n轴承预紧力不足\n\n## 关闭标准\n振动值低于 4.5 mm/s"
    assert draft.tags == ("issue_closure", "engineering", "high")

    # Closure criteria alone only restates the exit condition.
    assert (
        build_candidate_draft(
            title="t",
            issue_type="quality",
            severity="low",
            root_cause="   ",
            resolution=None,
            closure_criteria="随便写点",
        )
        is None
    )


def test_candidate_creation_never_blocks_the_closure(
    client: TestClient, isolated_candidate_database: str
) -> None:
    """The closure is the user's action; candidate capture is a side benefit."""
    scope = Scope(client, isolated_candidate_database)
    try:
        owner = scope.user("owner_engineer", "engineer")
        verifier = scope.user("verifier_quality", "quality")
        project_id = scope.project(member_ids=(owner, verifier))
        issue_id = scope.issue(project_id, owner=owner, verifier=verifier)
        owner_headers = bearer_headers(client, username="owner_engineer")
        verifier_headers = bearer_headers(client, username="verifier_quality")

        # Pre-seed a candidate so the automatic one collides on the unique key.
        with scope.engine.begin() as connection:
            connection.execute(
                tables.memories.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": scope.tenant_id,
                    "project_id": project_id,
                    "source_issue_id": issue_id,
                    "created_by_user_id": scope.owner_id,
                    "title": "手工先写的经验",
                    "content": "已有内容",
                    "tags": [],
                    "source_refs": [],
                    "content_sha256": "a" * 64,
                    "status": "draft",
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                },
            )

        close_issue(client, owner_headers, project_id, issue_id)
        closed = client.post(
            f"/api/projects/{project_id}/issues/{issue_id}/transitions",
            headers=verifier_headers,
            json={"to_status": "closed", "closure_evidence_ref": "doc://report-1"},
        )
        assert closed.status_code == 200
        assert closed.json()["status"] == "closed"
        assert len(scope.memories()) == 1
    finally:
        scope.dispose()
