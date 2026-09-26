"""Meeting / agenda / transcript contract tests (vNext V2-1, D6/D35)."""

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
from sqlalchemy import Table, create_engine, select

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
START = "2026-09-01T01:00:00Z"
END = "2026-09-01T02:00:00Z"


@pytest.fixture(autouse=True)
def isolated_meeting_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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

    def project(self, *, member_ids: tuple[UUID, ...] = ()) -> UUID:
        workflow_id = self._insert(tables.workflows, {"code": "WF-MTG", "name": "Workflow"})
        self._insert(
            tables.stages,
            {"workflow_id": workflow_id, "code": "evt", "name": "EVT", "sequence": 1},
        )
        project_id = self._insert(
            tables.projects,
            {
                "workflow_id": workflow_id,
                "owner_user_id": self.owner_id,
                "code": "PRJ-MTG",
                "name": "Meeting project",
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


@pytest.fixture
def scope(client: TestClient, isolated_meeting_database: str) -> Iterator[Scope]:
    built = Scope(client, isolated_meeting_database)
    try:
        yield built
    finally:
        built.dispose()


def create_meeting(
    client: TestClient,
    headers: dict[str, str],
    project_id: UUID,
    **overrides: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "meeting_type": "weekly",
        "title": "项目周会",
        "scheduled_start_at": START,
        "scheduled_end_at": END,
    }
    body.update(overrides)
    response = client.post(f"/api/projects/{project_id}/meetings", json=body, headers=headers)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def preparation(
    client: TestClient, headers: dict[str, str], project_id: UUID, meeting_id: str
) -> dict[str, Any]:
    result = client.get(
        f"/api/projects/{project_id}/meetings/{meeting_id}/preparation", headers=headers
    )
    assert result.status_code == 200, result.text
    value: dict[str, Any] = result.json()
    return value


def test_creating_a_meeting_seats_the_organizer_and_audits_the_write(
    client: TestClient, scope: Scope
) -> None:
    headers = bearer_headers(client)
    engineer_id = scope.user("engineer", "engineer")
    project_id = scope.project(member_ids=(engineer_id,))

    meeting = create_meeting(
        client,
        headers,
        project_id,
        participants=[{"user_id": str(engineer_id), "participation": "required"}],
    )
    assert meeting["status"] == "scheduled"
    assert meeting["organizer_user_id"] == str(scope.owner_id)

    roster = client.get(
        f"/api/projects/{project_id}/meetings/{meeting['id']}/participants",
        headers=headers,
    ).json()["items"]
    seats = {item["user_id"]: item["participation"] for item in roster}
    assert seats[str(scope.owner_id)] == "organizer"
    assert seats[str(engineer_id)] == "required"

    with scope.engine.connect() as connection:
        actions = [
            row.action
            for row in connection.execute(
                select(tables.audit_log.c.action).where(
                    tables.audit_log.c.tenant_id == scope.tenant_id
                )
            ).all()
        ]
        events = [
            row.event_type
            for row in connection.execute(
                select(tables.events.c.event_type).where(
                    tables.events.c.tenant_id == scope.tenant_id
                )
            ).all()
        ]
    assert "meeting.created" in actions
    assert "MEETING_STATE_CHANGED" in events


def test_a_non_member_cannot_be_seated_in_the_meeting(client: TestClient, scope: Scope) -> None:
    """未授权会议不可接入: the invite list cannot widen the project's reach."""
    headers = bearer_headers(client)
    outsider_id = scope.user("outsider", "engineer")
    project_id = scope.project()

    response = client.post(
        f"/api/projects/{project_id}/meetings",
        json={
            "meeting_type": "weekly",
            "title": "项目周会",
            "scheduled_start_at": START,
            "scheduled_end_at": END,
            "participants": [{"user_id": str(outsider_id), "participation": "required"}],
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "MEETING_PARTICIPANT_NOT_IN_PROJECT"


def test_an_engineer_cannot_create_or_bind_but_can_read_and_upload(
    client: TestClient, scope: Scope
) -> None:
    owner_headers = bearer_headers(client)
    engineer_id = scope.user("engineer", "engineer")
    project_id = scope.project(member_ids=(engineer_id,))
    meeting = create_meeting(client, owner_headers, project_id)
    engineer_headers = bearer_headers(client, username="engineer")

    denied = client.post(
        f"/api/projects/{project_id}/meetings",
        json={
            "meeting_type": "weekly",
            "title": "自建周会",
            "scheduled_start_at": START,
            "scheduled_end_at": END,
        },
        headers=engineer_headers,
    )
    assert denied.status_code == 403

    denied_bind = client.post(
        f"/api/projects/{project_id}/meetings/{meeting['id']}/conference",
        json={
            "provider": "dingtalk",
            "external_meeting_id": "conf-1",
            "join_url": "https://meeting.dingtalk.com/j/conf-1",
        },
        headers=engineer_headers,
    )
    assert denied_bind.status_code == 403

    readable = client.get(
        f"/api/projects/{project_id}/meetings/{meeting['id']}", headers=engineer_headers
    )
    assert readable.status_code == 200

    uploaded = client.post(
        f"/api/projects/{project_id}/meetings/{meeting['id']}/transcripts",
        json={"authorized_source": True, "content": "会议记录", "segments": []},
        headers=engineer_headers,
    )
    assert uploaded.status_code == 201


@pytest.mark.parametrize(
    ("provider", "join_url"),
    [
        # A chat deep link is not a conference: 私聊不可接入.
        ("dingtalk_chat", "https://meeting.dingtalk.com/j/conf-1"),
        ("zoom", "https://zoom.us/j/1"),
        ("dingtalk", "http://meeting.dingtalk.com/j/conf-1"),
        ("dingtalk", "dingtalk://im/chat?id=private-thread"),
    ],
)
def test_only_https_conference_links_from_allowed_providers_bind(
    client: TestClient, scope: Scope, provider: str, join_url: str
) -> None:
    headers = bearer_headers(client)
    project_id = scope.project()
    meeting = create_meeting(client, headers, project_id)

    response = client.post(
        f"/api/projects/{project_id}/meetings/{meeting['id']}/conference",
        json={
            "provider": provider,
            "external_meeting_id": "conf-1",
            "join_url": join_url,
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "MEETING_CONFERENCE_REJECTED"

    unchanged = client.get(
        f"/api/projects/{project_id}/meetings/{meeting['id']}", headers=headers
    ).json()
    assert unchanged["external_provider"] is None
    assert unchanged["external_join_url"] is None


def test_binding_a_conference_is_recorded_and_not_silently_replaced(
    client: TestClient, scope: Scope
) -> None:
    headers = bearer_headers(client)
    project_id = scope.project()
    meeting = create_meeting(client, headers, project_id)

    bound = client.post(
        f"/api/projects/{project_id}/meetings/{meeting['id']}/conference",
        json={
            "provider": "dingtalk",
            "external_meeting_id": "conf-1",
            "join_url": "https://meeting.dingtalk.com/j/conf-1",
        },
        headers=headers,
    )
    assert bound.status_code == 200
    assert bound.json()["external_provider"] == "dingtalk"
    assert bound.json()["source"] == "dingtalk"

    rebind = client.post(
        f"/api/projects/{project_id}/meetings/{meeting['id']}/conference",
        json={
            "provider": "tencent_meeting",
            "external_meeting_id": "conf-2",
            "join_url": "https://meeting.tencent.com/dm/conf-2",
        },
        headers=headers,
    )
    assert rebind.status_code == 400
    still = client.get(
        f"/api/projects/{project_id}/meetings/{meeting['id']}", headers=headers
    ).json()
    assert still["external_meeting_id"] == "conf-1"


def test_agenda_is_positional_and_carries_its_source_link(client: TestClient, scope: Scope) -> None:
    headers = bearer_headers(client)
    project_id = scope.project()
    meeting = create_meeting(client, headers, project_id)
    issue_id = scope._insert(
        tables.issues,
        {
            "project_id": project_id,
            "reported_by_user_id": scope.owner_id,
            "title": "关键问题",
            "severity": "high",
            "status": "open",
        },
    )
    original = preparation(client, headers, project_id, meeting["id"])
    issue_source = next(
        item
        for group in original["sources"]
        for item in group["items"]
        if item["kind"] == "issue" and item["id"] == str(issue_id)
    )

    response = client.put(
        f"/api/projects/{project_id}/meetings/{meeting['id']}/agenda",
        json={
            "expected_digest": original["digest"],
            "items": [
                {"title": "上周行动项复查", "item_kind": "review"},
                {
                    "title": "关键问题",
                    "item_kind": "exception",
                    "source_kind": "issue",
                    "source_entity_id": str(issue_id),
                    "source_digest": issue_source["digest"],
                },
            ],
        },
        headers=headers,
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["position"] for item in items] == [1, 2]
    assert items[1]["source_kind"] == "issue"
    assert items[1]["source_entity_id"] == str(issue_id)

    # Replacing the agenda renumbers from 1 rather than colliding on position.
    replaced = client.put(
        f"/api/projects/{project_id}/meetings/{meeting['id']}/agenda",
        json={
            "items": [{"title": "只剩一项"}],
            "expected_digest": preparation(client, headers, project_id, meeting["id"])["digest"],
        },
        headers=headers,
    )
    assert replaced.status_code == 200
    assert [item["position"] for item in replaced.json()["items"]] == [1]


def test_reuploading_identical_transcript_bytes_does_not_fork_the_record(
    client: TestClient, scope: Scope
) -> None:
    headers = bearer_headers(client)
    project_id = scope.project()
    meeting = create_meeting(client, headers, project_id)
    payload = {
        "authorized_source": True,
        "content": "张工：本周样机装配完成。\n李工：测试计划顺延两天。",
        "segments": [
            {"sequence": 1, "content": "本周样机装配完成。", "speaker_label": "张工"},
            {
                "sequence": 2,
                "content": "测试计划顺延两天。",
                "speaker_label": "李工",
                "started_offset_ms": 8000,
            },
        ],
    }

    first = client.post(
        f"/api/projects/{project_id}/meetings/{meeting['id']}/transcripts",
        json=payload,
        headers=headers,
    )
    assert first.status_code == 201
    assert first.json()["segment_count"] == 2
    assert first.json()["speaker_labeled"] is True
    assert first.json()["reused_existing"] is False

    second = client.post(
        f"/api/projects/{project_id}/meetings/{meeting['id']}/transcripts",
        json=payload,
        headers=headers,
    )
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["reused_existing"] is True

    listed = client.get(
        f"/api/projects/{project_id}/meetings/{meeting['id']}/transcripts",
        headers=headers,
    ).json()["items"]
    assert len(listed) == 1

    with scope.engine.connect() as connection:
        segments = connection.execute(
            select(tables.meeting_transcript_segments.c.sequence).where(
                tables.meeting_transcript_segments.c.tenant_id == scope.tenant_id
            )
        ).all()
    assert sorted(row.sequence for row in segments) == [1, 2]


def test_status_moves_forward_only_and_cancelling_requires_a_reason(
    client: TestClient, scope: Scope
) -> None:
    headers = bearer_headers(client)
    project_id = scope.project()
    meeting = create_meeting(client, headers, project_id)
    url = f"/api/projects/{project_id}/meetings/{meeting['id']}/status"

    started = client.post(url, json={"status": "in_progress"}, headers=headers)
    assert started.status_code == 200
    assert started.json()["actual_start_at"] is not None

    completed = client.post(url, json={"status": "completed"}, headers=headers)
    assert completed.status_code == 200
    assert completed.json()["actual_end_at"] is not None

    reopened = client.post(url, json={"status": "in_progress"}, headers=headers)
    assert reopened.status_code == 409


def test_completing_a_never_started_meeting_invents_no_actual_times(
    client: TestClient, scope: Scope
) -> None:
    """Nobody marked it started, so there is no observed start or end to report."""
    headers = bearer_headers(client)
    project_id = scope.project()
    meeting = create_meeting(client, headers, project_id)

    completed = client.post(
        f"/api/projects/{project_id}/meetings/{meeting['id']}/status",
        json={"status": "completed"},
        headers=headers,
    )
    assert completed.status_code == 200
    assert completed.json()["actual_start_at"] is None
    assert completed.json()["actual_end_at"] is None


def test_cancelling_without_a_reason_is_refused(client: TestClient, scope: Scope) -> None:
    headers = bearer_headers(client)
    project_id = scope.project()
    meeting = create_meeting(client, headers, project_id)

    response = client.post(
        f"/api/projects/{project_id}/meetings/{meeting['id']}/status",
        json={"status": "cancelled"},
        headers=headers,
    )
    assert response.status_code == 409


def test_an_active_meeting_cannot_be_archived_and_agenda_freezes_when_completed(
    client: TestClient, scope: Scope
) -> None:
    headers = bearer_headers(client)
    project_id = scope.project()
    meeting = create_meeting(client, headers, project_id)
    base = f"/api/projects/{project_id}/meetings/{meeting['id']}"

    too_early = client.post(f"{base}/archive", headers=headers)
    assert too_early.status_code == 409

    client.post(f"{base}/status", json={"status": "completed"}, headers=headers)
    frozen = client.put(
        f"{base}/agenda",
        json={
            "items": [{"title": "补记"}],
            "expected_digest": preparation(client, headers, project_id, meeting["id"])["digest"],
        },
        headers=headers,
    )
    assert frozen.status_code == 409

    archived = client.post(f"{base}/archive", headers=headers)
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    # Archiving twice is a no-op, not a second archive timestamp.
    again = client.post(f"{base}/archive", headers=headers)
    assert again.json()["archived_at"] == archived.json()["archived_at"]


def test_a_meeting_in_another_project_is_not_reachable(client: TestClient, scope: Scope) -> None:
    headers = bearer_headers(client)
    project_id = scope.project()
    meeting = create_meeting(client, headers, project_id)
    other_project_id = uuid4()

    response = client.get(
        f"/api/projects/{other_project_id}/meetings/{meeting['id']}", headers=headers
    )
    assert response.status_code in {403, 404}
