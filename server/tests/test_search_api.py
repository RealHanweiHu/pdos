"""Unified search tests (vNext V2-10, G11)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Table, create_engine

from app.auth.passwords import PasswordService
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.search import SearchQueryError, parse_terms
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
def isolated_search_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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
        # Work items must carry the workflow and stage of their own project
        # (ck_issues_stage_pair_consistent), so each project's pair is kept here.
        self.flow: dict[UUID, tuple[UUID, UUID]] = {}

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

    def project(self, code: str, *, member_ids: tuple[UUID, ...] = ()) -> UUID:
        # uq_projects_tenant_workflow: a workflow instance belongs to exactly
        # one project, so each project gets its own.
        workflow_id = self._insert(
            tables.workflows, {"code": f"WF-{code}", "name": f"Workflow {code}"}
        )
        project_id = self._insert(
            tables.projects,
            {
                "workflow_id": workflow_id,
                "owner_user_id": self.owner_id,
                "code": code,
                "name": f"项目 {code}",
                "status": "active",
            },
        )
        stage_id = self._insert(
            tables.stages,
            {"workflow_id": workflow_id, "code": "evt", "name": "EVT", "sequence": 1},
        )
        self.flow[project_id] = (workflow_id, stage_id)
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

    def issue(self, project_id: UUID, title: str, description: str) -> UUID:
        workflow_id, stage_id = self.flow[project_id]
        return self._insert(
            tables.issues,
            {
                "project_id": project_id,
                "workflow_id": workflow_id,
                "stage_id": stage_id,
                "created_by_user_id": self.owner_id,
                "title": title,
                "description": description,
                "severity": "high",
                "status": "open",
            },
        )

    def document_with_text(self, project_id: UUID, filename: str, body: str) -> UUID:
        document_id = self._insert(
            tables.documents,
            {
                "project_id": project_id,
                "uploaded_by_user_id": self.owner_id,
                "object_key": f"docs/{uuid4()}",
                "filename": filename,
                "media_type": "application/pdf",
                "classification": "internal",
                "size_bytes": 1024,
                "sha256": "a" * 64,
                "extraction_status": "extracted",
                "fragment_count": 1,
            },
        )
        self._insert(
            tables.document_fragments,
            {
                "project_id": project_id,
                "document_id": document_id,
                "ordinal": 1,
                "locator": "p1",
                "text": body,
            },
        )
        return document_id


@pytest.fixture
def scope(client: TestClient, isolated_search_database: str) -> Iterator[Scope]:
    built = Scope(client, isolated_search_database)
    try:
        yield built
    finally:
        built.dispose()


def search(
    client: TestClient, headers: dict[str, str], query: str, **params: Any
) -> dict[str, Any]:
    response = client.get("/api/search", params={"q": query, **params}, headers=headers)
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


def test_search_spans_work_items_and_attachment_text(client: TestClient, scope: Scope) -> None:
    headers = bearer_headers(client)
    project_id = scope.project("PRJ-A")
    scope.issue(project_id, "密封面粗糙度超差", "EVT 阶段发现气压不达标")
    scope.document_with_text(
        project_id, "EVT测试报告.pdf", "测试记录显示密封面粗糙度 Ra1.6 不满足要求"
    )

    result = search(client, headers, "密封面粗糙度")
    kinds = {item["kind"] for item in result["items"]}

    assert "issue" in kinds
    # The answer is inside the attachment text, not its filename — that is the
    # whole point of indexing fragments.
    assert "document" in kinds


def test_all_terms_must_match_not_any(client: TestClient, scope: Scope) -> None:
    headers = bearer_headers(client)
    project_id = scope.project("PRJ-A")
    scope.issue(project_id, "密封面粗糙度超差", "结构件问题")
    scope.issue(project_id, "电机噪声偏大", "电机问题")

    both = search(client, headers, "密封面 结构件")
    assert [item["title"] for item in both["items"]] == ["密封面粗糙度超差"]

    # A term present in neither record narrows the result to nothing.
    neither = search(client, headers, "密封面 电机")
    assert neither["items"] == []


def test_title_matches_outrank_body_matches(client: TestClient, scope: Scope) -> None:
    headers = bearer_headers(client)
    project_id = scope.project("PRJ-A")
    scope.issue(project_id, "无关标题", "正文里提到了密封面")
    scope.issue(project_id, "密封面异常", "正文无关")

    result = search(client, headers, "密封面")
    titles = [item["title"] for item in result["items"]]

    assert titles[0] == "密封面异常"
    assert result["items"][0]["score"] > result["items"][1]["score"]


def test_the_excerpt_shows_why_the_record_matched(client: TestClient, scope: Scope) -> None:
    headers = bearer_headers(client)
    project_id = scope.project("PRJ-A")
    scope.issue(
        project_id,
        "EVT 复测",
        "前面有很多无关的铺垫内容" * 6 + "关键结论是密封面粗糙度不达标" + "后续内容" * 6,
    )

    result = search(client, headers, "密封面粗糙度")
    assert "密封面粗糙度" in result["items"][0]["excerpt"]


def test_a_member_never_sees_hits_from_projects_they_are_not_on(
    client: TestClient, scope: Scope
) -> None:
    """Reach is filtered in the query, so a count cannot leak other projects."""
    engineer_id = scope.user("engineer", "engineer")
    mine = scope.project("PRJ-MINE", member_ids=(engineer_id,))
    theirs = scope.project("PRJ-THEIRS")
    scope.issue(mine, "密封面 我的项目", "内容")
    scope.issue(theirs, "密封面 别人的项目", "内容")

    engineer_headers = bearer_headers(client, username="engineer")
    result = search(client, engineer_headers, "密封面")
    titles = [item["title"] for item in result["items"]]

    assert titles == ["密封面 我的项目"]
    assert all(item["project_id"] == str(mine) for item in result["items"])


def test_an_owner_reaches_the_whole_tenant(client: TestClient, scope: Scope) -> None:
    headers = bearer_headers(client)
    first = scope.project("PRJ-1")
    second = scope.project("PRJ-2")
    scope.issue(first, "密封面 一号", "内容")
    scope.issue(second, "密封面 二号", "内容")

    result = search(client, headers, "密封面")
    assert len(result["items"]) == 2


def test_a_user_on_no_project_gets_nothing_rather_than_everything(
    client: TestClient, scope: Scope
) -> None:
    scope.user("newcomer", "engineer")
    project_id = scope.project("PRJ-A")
    scope.issue(project_id, "密封面异常", "内容")

    headers = bearer_headers(client, username="newcomer")
    result = search(client, headers, "密封面")
    assert result["items"] == []


def test_search_can_be_narrowed_to_specific_kinds(client: TestClient, scope: Scope) -> None:
    headers = bearer_headers(client)
    project_id = scope.project("PRJ-A")
    scope.issue(project_id, "密封面异常", "内容")
    scope.document_with_text(project_id, "密封面报告.pdf", "密封面测量记录")

    only_documents = search(client, headers, "密封面", kinds="document")
    assert {item["kind"] for item in only_documents["items"]} == {"document"}

    unknown = client.get(
        "/api/search", params={"q": "密封面", "kinds": "spaceship"}, headers=headers
    )
    assert unknown.status_code == 400
    assert unknown.json()["detail"]["code"] == "SEARCH_QUERY_INVALID"


def test_results_are_capped_and_say_so(client: TestClient, scope: Scope) -> None:
    headers = bearer_headers(client)
    project_id = scope.project("PRJ-A")
    for index in range(6):
        scope.issue(project_id, f"密封面 {index}", "内容")

    result = search(client, headers, "密封面", limit=3)
    assert len(result["items"]) == 3
    assert result["truncated"] is True


def test_a_supplier_cannot_search(client: TestClient, scope: Scope) -> None:
    scope.user("vendor", "supplier")
    headers = bearer_headers(client, username="vendor")

    response = client.get("/api/search", params={"q": "密封面"}, headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SEARCH_FORBIDDEN"


def test_search_requires_authentication(client: TestClient, scope: Scope) -> None:
    assert client.get("/api/search", params={"q": "密封面"}).status_code == 401


def test_a_blank_query_is_refused_by_validation(client: TestClient, scope: Scope) -> None:
    headers = bearer_headers(client)
    assert client.get("/api/search", params={"q": "   "}, headers=headers).status_code == 400
    assert client.get("/api/search", params={"q": ""}, headers=headers).status_code == 422


def test_term_parsing_deduplicates_and_caps() -> None:
    assert parse_terms("  密封面   密封面  Ra1.6 ") == ["密封面", "ra1.6"]
    assert len(parse_terms(" ".join(f"t{index}" for index in range(20)))) == 8
    with pytest.raises(SearchQueryError):
        parse_terms("   ")


def sample_for(scope: Scope, project_id: UUID, serial_number: str) -> UUID:
    workflow_id, stage_id = scope.flow[project_id]
    batch_id = scope._insert(
        tables.build_batches,
        {
            "project_id": project_id,
            "workflow_id": workflow_id,
            "stage_id": stage_id,
            "created_by_user_id": scope.owner_id,
            "code": f"BB-{serial_number}",
            "phase": "evt",
            "planned_quantity": 1,
            "status": "planned",
        },
    )
    return scope._insert(
        tables.samples,
        {
            "project_id": project_id,
            "build_batch_id": batch_id,
            "created_by_user_id": scope.owner_id,
            "serial_number": serial_number,
            "status": "built",
        },
    )


def test_a_field_note_matches_the_prototype_by_its_printed_serial(
    client: TestClient, scope: Scope
) -> None:
    """G14/D37: no scanning — the serial in the dictated note is the link."""
    headers = bearer_headers(client)
    project_id = scope.project("PRJ-A")
    sample_id = sample_for(scope, project_id, "SN-1001")
    sample_for(scope, project_id, "SN-1002")

    response = client.post(
        f"/api/search/projects/{project_id}/sample-matches",
        json={"text": "现场复测 sn-1001 气压偏低，噪声正常"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert [item["sample_id"] for item in payload["items"]] == [str(sample_id)]
    assert payload["ambiguous"] is False


def test_two_serials_in_one_note_are_reported_as_ambiguous_not_guessed(
    client: TestClient, scope: Scope
) -> None:
    headers = bearer_headers(client)
    project_id = scope.project("PRJ-A")
    sample_for(scope, project_id, "SN-1001")
    sample_for(scope, project_id, "SN-1002")

    response = client.post(
        f"/api/search/projects/{project_id}/sample-matches",
        json={"text": "SN-1001 与 SN-1002 都出现同一缺陷"},
        headers=headers,
    )
    payload = response.json()
    assert len(payload["items"]) == 2
    assert payload["ambiguous"] is True


def test_the_more_specific_serial_is_offered_first(client: TestClient, scope: Scope) -> None:
    """SN-1 is a substring of SN-12; the longer identifier is the likelier one."""
    headers = bearer_headers(client)
    project_id = scope.project("PRJ-A")
    sample_for(scope, project_id, "SN-1")
    sample_for(scope, project_id, "SN-12")

    response = client.post(
        f"/api/search/projects/{project_id}/sample-matches",
        json={"text": "样机 SN-12 密封面异常"},
        headers=headers,
    )
    serials = [item["serial_number"] for item in response.json()["items"]]
    assert serials[0] == "SN-12"


def test_a_note_naming_no_prototype_matches_nothing(client: TestClient, scope: Scope) -> None:
    headers = bearer_headers(client)
    project_id = scope.project("PRJ-A")
    sample_for(scope, project_id, "SN-1001")

    response = client.post(
        f"/api/search/projects/{project_id}/sample-matches",
        json={"text": "今天车间温度偏高"},
        headers=headers,
    )
    assert response.json()["items"] == []
    assert response.json()["ambiguous"] is False


def test_sample_matching_is_project_scoped(client: TestClient, scope: Scope) -> None:
    headers = bearer_headers(client)
    mine = scope.project("PRJ-MINE")
    theirs = scope.project("PRJ-THEIRS")
    sample_for(scope, theirs, "SN-9999")

    response = client.post(
        f"/api/search/projects/{mine}/sample-matches",
        json={"text": "SN-9999 有问题"},
        headers=headers,
    )
    assert response.json()["items"] == []
