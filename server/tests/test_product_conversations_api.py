"""Queued typed PM conversation PostgreSQL/API cases; collection is not execution evidence."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import DBAPIError

from app.auth.passwords import PasswordService
from app.db.schema import tables
from tests.product_master_reference_fixtures import (
    master_reference_database_guard as master_reference_database_guard,
)
from tests.test_product_manager_loop_api import command
from tests.test_product_work_preparation_api import space
from tests.test_test_runs_api import PASSWORD, Scope, bearer_headers
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


@dataclass
class Candidate:
    client: TestClient
    scope: Scope
    headers: dict[str, str]
    space_id: str
    line: dict[str, Any]

    def create(self, kind: str = "market_space", **changes: Any) -> dict[str, Any]:
        body: dict[str, Any] = {"request_id": str(uuid4()), "scope_kind": kind}
        if kind in {"market_space", "product_line"}:
            body["market_space_id"] = self.space_id
        if kind == "product_line":
            body["product_line_id"] = self.line["id"]
        body.update(changes)
        return self.post("/api/conversations", body)

    def post(
        self,
        url: str,
        body: dict[str, Any],
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = self.client.post(url, headers=headers or self.headers, json=body)
        assert response.status_code == status, response.text
        return dict(response.json())

    def message(
        self, conversation: dict[str, Any], text: str = "内部说明", **changes: Any
    ) -> dict[str, Any]:
        body = {"request_id": str(uuid4()), "expected_context_version": 1, "body": text}
        body.update(changes)
        return body

    def save(
        self,
        conversation: dict[str, Any],
        body: dict[str, Any],
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self.post(f"/api/conversations/{conversation['id']}/messages", body, status, headers)

    def read(
        self, conversation: dict[str, Any], status: int = 200, headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        response = self.client.get(
            f"/api/conversations/{conversation['id']}", headers=headers or self.headers
        )
        assert response.status_code == status, response.text
        return dict(response.json())

    def attachment(self, conversation: dict[str, Any]) -> dict[str, Any]:
        return self.post(
            f"/api/conversations/{conversation['id']}/attachments",
            {
                "request_id": str(uuid4()),
                "filename": "synthetic.pdf",
                "size_bytes": 8,
                "sha256": "a" * 64,
                "classification": "internal",
            },
        )

    def no_models_or_business_files(self) -> None:
        with self.scope.engine.connect() as c:
            for table in (tables.model_invocations, tables.product_source_files):
                assert (
                    c.execute(
                        select(func.count())
                        .select_from(table)
                        .where(table.c.tenant_id == self.scope.tenant_id)
                    ).scalar_one()
                    == 0
                )

    def stored(self, conversation: dict[str, Any]) -> list[dict[str, Any]]:
        with self.scope.engine.connect() as c:
            return [
                dict(row)
                for row in c.execute(
                    select(tables.conversation_messages)
                    .where(
                        tables.conversation_messages.c.tenant_id == self.scope.tenant_id,
                        tables.conversation_messages.c.conversation_id == UUID(conversation["id"]),
                    )
                    .order_by(tables.conversation_messages.c.sequence)
                ).mappings()
            ]


@pytest.fixture
def candidate(client: TestClient, isolated_test_run_database: str) -> Iterator[Candidate]:
    scope = Scope(client, isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        sid = space(client, headers)
        response = client.post(
            f"/api/product-work/spaces/{sid}/products",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "code": "PM-PRIVATE-LINE",
                "name": "合成产品线",
                "level": "line",
                "owner_user_id": str(scope.owner_id),
            },
        )
        assert response.status_code == 201, response.text
        yield Candidate(client, scope, headers, sid, dict(response.json()))
    finally:
        scope.dispose()


def colleague(candidate: Candidate) -> tuple[UUID, dict[str, str]]:
    username = "pm-private-" + uuid4().hex[:10]
    user = candidate.scope._insert(
        tables.users,
        {
            "username": username,
            "display_name": "合成内部成员",
            "role": "engineer",
            "password_hash": PasswordService().hash(PASSWORD),
            "is_active": True,
        },
    )
    response = candidate.client.put(
        f"/api/product-work/spaces/{candidate.space_id}/members/{user}",
        headers=candidate.headers,
        json={"access": "contributor"},
    )
    assert response.status_code == 204, response.text
    candidate.post(
        f"/api/product-work/spaces/{candidate.space_id}/products/{candidate.line['id']}/members",
        {**command(candidate.line), "user_id": str(user), "access": "contributor"},
    )
    login = candidate.client.post(
        "/api/auth/login",
        json={
            "tenant_slug": "beepump",
            "username": username,
            "password": PASSWORD,
        },
    )
    assert login.status_code == 200, login.text
    return user, {"Authorization": "Bearer " + login.json()["access_token"]}


def test_private_typed_create_listing_and_original_create_replay(candidate: Candidate) -> None:
    for kind in ("personal", "market_space", "product_line"):
        request_id = str(uuid4())
        conversation = candidate.create(kind, request_id=request_id)
        assert conversation["project_id"] is None and conversation["visibility"] == "private"
        assert candidate.create(kind, request_id=request_id) == conversation
        params = {
            key: conversation[key]
            for key in ("scope_kind", "market_space_id", "product_line_id")
            if conversation[key] is not None
        }
        listed = candidate.client.get(
            "/api/conversations", headers=candidate.headers, params=params
        )
        assert listed.status_code == 200, listed.text
        assert [item["id"] for item in listed.json()["items"]] == [conversation["id"]]


def test_mixed_project_pm_and_shared_nonproject_scopes_reject_before_write(
    candidate: Candidate,
) -> None:
    for body in (
        {"scope_kind": "personal", "market_space_id": candidate.space_id},
        {
            "scope_kind": "market_space",
            "market_space_id": candidate.space_id,
            "project_id": str(uuid4()),
        },
        {"scope_kind": "product_line", "market_space_id": candidate.space_id},
        {"scope_kind": "personal", "visibility": "project"},
    ):
        candidate.post("/api/conversations", {"request_id": str(uuid4()), **body}, 422)
    with candidate.scope.engine.connect() as c:
        assert (
            c.execute(
                select(func.count())
                .select_from(tables.conversations)
                .where(tables.conversations.c.tenant_id == candidate.scope.tenant_id)
            ).scalar_one()
            == 0
        )


def test_other_internal_member_cannot_read_private_history_or_attachments(
    candidate: Candidate,
) -> None:
    _, other = colleague(candidate)
    conversation = candidate.create("product_line")
    candidate.save(conversation, candidate.message(conversation))
    attachment = candidate.attachment(conversation)
    candidate.read(conversation, 403, other)
    for suffix in ("attachments", f"attachments/{attachment['id']}"):
        response = candidate.client.get(
            f"/api/conversations/{conversation['id']}/{suffix}", headers=other
        )
        assert response.status_code == 403, response.text
    listed = candidate.client.get(
        "/api/conversations",
        headers=other,
        params={
            "scope_kind": "product_line",
            "market_space_id": candidate.space_id,
            "product_line_id": candidate.line["id"],
        },
    )
    assert listed.status_code == 200 and listed.json()["items"] == []


def test_space_line_and_role_revocation_blocks_current_reads_and_original_replay_then_restores(
    candidate: Candidate,
) -> None:
    user, headers = colleague(candidate)
    # Use the colleague's own private identity.
    conversation = candidate.post(
        "/api/conversations",
        {
            "request_id": str(uuid4()),
            "scope_kind": "product_line",
            "market_space_id": candidate.space_id,
            "product_line_id": candidate.line["id"],
        },
        headers=headers,
    )
    body = candidate.message(conversation)
    saved = candidate.save(conversation, body, headers=headers)
    original = candidate.stored(conversation)
    for target in ("space", "line", "role"):
        table = {
            "space": tables.market_space_members,
            "line": tables.product_line_members,
            "role": tables.users,
        }[target]
        with candidate.scope.engine.begin() as c:
            if target == "role":
                c.execute(table.update().where(table.c.id == user).values(role="supplier"))
            else:
                where = [table.c.tenant_id == candidate.scope.tenant_id, table.c.user_id == user]
                where.append(table.c.market_space_id == UUID(candidate.space_id))
                c.execute(table.delete().where(*where))
        candidate.read(conversation, 403, headers)
        candidate.save(conversation, body, 403, headers)
        listed = candidate.client.get(
            "/api/conversations",
            headers=headers,
            params={
                "scope_kind": "product_line",
                "market_space_id": candidate.space_id,
                "product_line_id": candidate.line["id"],
            },
        )
        assert listed.status_code == 403, listed.text
        with candidate.scope.engine.begin() as c:
            if target == "role":
                c.execute(table.update().where(table.c.id == user).values(role="engineer"))
            else:
                values = {
                    "tenant_id": candidate.scope.tenant_id,
                    "market_space_id": UUID(candidate.space_id),
                    "user_id": user,
                    "access": "contributor",
                    "added_by_user_id": candidate.scope.owner_id,
                }
                if target == "line":
                    values["product_line_id"] = UUID(candidate.line["id"])
                c.execute(table.insert().values(**values))
        assert candidate.read(conversation, headers=headers)["items"][0]["id"] == saved["id"]
        assert candidate.save(conversation, body, headers=headers)["id"] == saved["id"]
        assert candidate.stored(conversation) == original


def test_personal_note_and_pdf_registration_never_run_model_or_create_business_file(
    candidate: Candidate,
) -> None:
    conversation = candidate.create("personal")
    attachment = candidate.attachment(conversation)
    assert attachment["status"] == "awaiting_upload"
    saved = candidate.save(
        conversation, candidate.message(conversation, "稍后研究", attachment_ids=[attachment["id"]])
    )
    assert saved["action"] == "note" and saved["product_work_request"] is None
    result = candidate.post(
        f"/api/conversations/{conversation['id']}/messages/{saved['id']}/run", {}
    )
    assert result["status"] == "saved"
    candidate.no_models_or_business_files()


def test_natural_pm_goal_freezes_request_and_operation_without_model(candidate: Candidate) -> None:
    conversation = candidate.create("market_space")
    body = candidate.message(conversation, "请整理研究计划")
    saved = candidate.save(conversation, body)
    fixed = saved["product_work_request"]
    assert saved["action"] == "product_work" and saved["operation_request_id"]
    assert fixed["selection"]["capability"] == "research_planning"
    assert fixed["selection"]["product_line_id"] is None
    assert fixed["user_instruction"] == body["body"] and len(fixed["expected_digest"]) == 64
    assert candidate.save(conversation, body) == saved
    assert candidate.read(conversation)["items"][0]["product_work_request"] == fixed
    candidate.no_models_or_business_files()


def test_unqualified_dispatch_returns_409_but_preserves_original_request(
    candidate: Candidate, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai import product_work_runs
    from app.ai.rollout_guard import CapabilityUnavailableError

    def unavailable(_key: str) -> None:
        raise CapabilityUnavailableError("CAPABILITY_DISABLED")

    monkeypatch.setattr(product_work_runs, "require_live_key", unavailable)
    conversation = candidate.create()
    body = candidate.message(conversation, "请整理研究计划")
    saved = candidate.save(conversation, body)
    before = candidate.stored(conversation)
    candidate.post(f"/api/conversations/{conversation['id']}/messages/{saved['id']}/run", {}, 409)
    assert candidate.stored(conversation) == before
    assert (
        candidate.save(conversation, body)["operation_request_id"] == saved["operation_request_id"]
    )
    candidate.no_models_or_business_files()


def test_nonproject_rejects_explicit_project_actions_without_partial_history(
    candidate: Candidate,
) -> None:
    conversation = candidate.create()
    for action in ("project_query", "minutes", "change_work_package", "quality_work_package"):
        candidate.save(conversation, candidate.message(conversation, action=action), 409)
    assert candidate.stored(conversation) == []


def test_archive_blocks_new_submission_and_preserves_original_history(candidate: Candidate) -> None:
    conversation = candidate.create()
    body = candidate.message(conversation)
    saved = candidate.save(conversation, body)
    before = candidate.stored(conversation)
    candidate.post(f"/api/conversations/{conversation['id']}/archive", {"archived": True})
    candidate.save(conversation, candidate.message(conversation), 409)
    assert candidate.save(conversation, body)["id"] == saved["id"]
    candidate.post(f"/api/conversations/{conversation['id']}/archive", {"archived": False})
    assert candidate.read(conversation)["items"][0]["id"] == saved["id"]
    assert candidate.stored(conversation) == before


def test_strict_parent_fk_and_null_scope_mutation_reject_without_changing_rows(
    candidate: Candidate,
) -> None:
    conversation = candidate.create()
    candidate.save(conversation, candidate.message(conversation))
    attachment = candidate.attachment(conversation)
    before = candidate.stored(conversation)
    with candidate.scope.engine.begin() as c:
        deployed = {
            fk["name"]: fk
            for fk in inspect(c).get_foreign_keys(
                "conversation_attachment_requests", schema="cehub_ai"
            )
        }
        assert deployed["fk_conversation_attachment_requests_typed_attachment"][
            "constrained_columns"
        ] == ["tenant_id", "conversation_id", "attachment_id"]
        for changes in (
            {"scope_kind": "personal", "market_space_id": None},
            {"project_id": uuid4()},
        ):
            with pytest.raises(DBAPIError), c.begin_nested():
                c.execute(
                    tables.conversations.update()
                    .where(tables.conversations.c.id == UUID(conversation["id"]))
                    .values(**changes)
                )
        with (
            pytest.raises(
                DBAPIError, match="Upload request must retain its exact attachment scope"
            ),
            c.begin_nested(),
        ):
            c.execute(
                tables.conversation_attachment_requests.insert().values(
                    tenant_id=candidate.scope.tenant_id,
                    project_id=None,
                    conversation_id=uuid4(),
                    request_id=uuid4(),
                    attachment_id=UUID(attachment["id"]),
                    request_digest="a" * 64,
                )
            )
    assert candidate.stored(conversation) == before


def test_pm_run_guard_rejects_different_fixed_source_actor(candidate: Candidate) -> None:
    conversation = candidate.create()
    saved = candidate.save(conversation, candidate.message(conversation, "请整理研究计划"))
    fixed = saved["product_work_request"]
    now = datetime.now(UTC)
    with (
        candidate.scope.engine.begin() as c,
        pytest.raises(
            DBAPIError, match="Product run must match the exact saved conversation request"
        ),
        c.begin_nested(),
    ):
        c.execute(
            tables.agent_runs.insert().values(
                id=uuid4(),
                tenant_id=candidate.scope.tenant_id,
                project_id=None,
                scope_kind="market_space",
                market_space_id=UUID(candidate.space_id),
                agent_key="product_management_intelligence",
                request_id=saved["operation_request_id"],
                requested_by_user_id=candidate.scope.owner_id,
                status="running",
                event_count=0,
                event_row_ids=[],
                window_started_at=now,
                window_ended_at=now,
                started_at=now,
                context_version="product-work-request-v1",
                run_context={
                    "product_work_selection": fixed["selection"],
                    "product_work_expected_digest": fixed["expected_digest"],
                    "product_work_user_instruction": fixed["user_instruction"],
                    "product_work_source": {
                        "selection": fixed["selection"],
                        "digest": fixed["expected_digest"],
                        "market_space_id": candidate.space_id,
                        "actor_id": str(uuid4()),
                    },
                },
            )
        )
    candidate.no_models_or_business_files()
