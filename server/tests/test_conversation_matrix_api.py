"""Queued PostgreSQL/HTTP matrix bridge cases; collection is not execution evidence.

The full existing product-manager journey creates every matrix/roadmap through
its domain APIs. No qualification, model invocation, migration, or trigger bypass
is performed here. The coordinator must allocate an isolated test database.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.db.schema import tables
from tests.product_master_reference_fixtures import (
    master_reference_database_guard as master_reference_database_guard,
)
from tests.test_product_conversations_api import Candidate, colleague
from tests.test_product_conversations_api import candidate as candidate
from tests.test_product_manager_loop_api import (
    test_research_to_released_definition_matrix_and_roadmap_without_project as seed_journey,
)
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


@dataclass
class MatrixCandidate:
    private: Candidate
    record: dict[str, Any]
    selection: dict[str, Any]

    def conversation(self) -> dict[str, Any]:
        return self.private.create("product_line")

    def save(self, conversation: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        body = self.private.message(
            conversation, "请解释产品矩阵和路线图", matrix_selection=self.selection
        )
        return body, self.private.save(conversation, body)


@pytest.fixture
def matrix_candidate(
    candidate: Candidate, isolated_test_run_database: str, monkeypatch: pytest.MonkeyPatch
) -> MatrixCandidate:
    from fastapi.testclient import TestClient

    from tests import test_product_manager_loop_api as journey
    from tests.test_test_runs_api import Scope

    # Reuse the already-created tenant/user, avoiding a second setup request.
    # The seed still executes its complete original HTTP/domain workflow.
    def existing_scope(_client: TestClient, _url: str) -> Scope:
        assert _client is candidate.client and _url == isolated_test_run_database
        return candidate.scope

    with monkeypatch.context() as patch:
        patch.setattr(journey, "Scope", existing_scope)
        seed_journey(candidate.client, isolated_test_run_database)
    with candidate.scope.engine.connect() as c:
        record = dict(
            c.execute(
                select(tables.product_matrix_records)
                .where(tables.product_matrix_records.c.tenant_id == candidate.scope.tenant_id)
                .order_by(tables.product_matrix_records.c.created_at.desc())
                .limit(1)
            )
            .mappings()
            .one()
        )
        roads = list(
            c.execute(
                select(tables.product_roadmap_revisions.c.id).where(
                    tables.product_roadmap_revisions.c.tenant_id == candidate.scope.tenant_id,
                    tables.product_roadmap_revisions.c.market_space_id == record["market_space_id"],
                    tables.product_roadmap_revisions.c.product_line_id == record["product_line_id"],
                    tables.product_roadmap_revisions.c.state == "published",
                )
            ).scalars()
        )
    assert roads, "The domain seed must actually publish a roadmap"
    private = Candidate(
        candidate.client,
        candidate.scope,
        candidate.headers,
        str(record["market_space_id"]),
        {"id": str(record["product_line_id"])},
    )
    return MatrixCandidate(
        private, record, {"record_id": str(record["id"]), "roadmap_ids": [str(roads[-1])]}
    )


def assert_no_runs(candidate: Candidate) -> None:
    with candidate.scope.engine.connect() as c:
        for table in (tables.agent_runs, tables.model_invocations):
            assert (
                c.execute(
                    select(func.count())
                    .select_from(table)
                    .where(table.c.tenant_id == candidate.scope.tenant_id)
                ).scalar_one()
                == 0
            )


def test_matrix_without_selection_is_saved_note_without_run(candidate: Candidate) -> None:
    conversation = candidate.create()
    saved = candidate.save(conversation, candidate.message(conversation, "请解释产品矩阵和路线图"))
    assert saved["action"] == "note" and saved["product_work_request"] is None
    before = candidate.stored(conversation)
    result = candidate.post(
        f"/api/conversations/{conversation['id']}/messages/{saved['id']}/run", {}
    )
    assert result["status"] == "saved"
    assert candidate.stored(conversation) == before
    assert_no_runs(candidate)


def test_matrix_options_are_private_and_exact_line(
    matrix_candidate: MatrixCandidate,
    candidate: Candidate,
) -> None:
    fixture = matrix_candidate
    conversation = fixture.conversation()
    path = f"/api/conversations/{conversation['id']}/matrix-options"
    response = candidate.client.get(path, headers=candidate.headers)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert str(fixture.record["id"]) in [item["id"] for item in items]
    assert all(set(item) == {"id", "title", "version"} for item in items)
    # Same space without a line does not silently pick a line-scoped matrix.
    broad = fixture.private.create("market_space")
    response = candidate.client.get(
        f"/api/conversations/{broad['id']}/matrix-options", headers=candidate.headers
    )
    assert response.status_code == 200, response.text
    assert str(fixture.record["id"]) not in [item["id"] for item in response.json()["items"]]
    _, other = colleague(candidate)
    denied = candidate.client.get(path, headers=other)
    assert denied.status_code == 403, denied.text
    assert str(fixture.record["id"]) not in denied.text


def test_matrix_fixed_signature_retry_and_scope_rejection(
    matrix_candidate: MatrixCandidate,
) -> None:
    fixture = matrix_candidate
    candidate = fixture.private
    conversation = fixture.conversation()
    body, saved = fixture.save(conversation)
    fixed = saved["product_work_request"]
    context = candidate.post(
        f"/api/product-work/spaces/{candidate.space_id}/matrix-ai-context", fixture.selection
    )
    assert fixed == {
        "kind": "matrix",
        "selection": fixture.selection,
        "expected_digest": context["digest"],
        "user_instruction": body["body"],
        "product_line_id": candidate.line["id"],
    }
    before = candidate.stored(conversation)
    assert candidate.save(conversation, body) == saved
    assert candidate.stored(conversation) == before
    assert candidate.read(conversation)["items"][0]["product_work_request"] == fixed
    changed = {**body, "body": "另一问题"}
    candidate.save(conversation, changed, 409)
    # Same authorized space, wrong exact line: no source is substituted.
    broad = candidate.create("market_space")
    candidate.save(
        broad, candidate.message(broad, "解释矩阵", matrix_selection=fixture.selection), 403
    )
    assert candidate.stored(broad) == []
    personal = candidate.create("personal")
    candidate.save(
        personal, candidate.message(personal, "解释矩阵", matrix_selection=fixture.selection), 409
    )
    assert candidate.stored(personal) == []
    assert_no_runs(candidate)


def test_unqualified_matrix_dispatch_preserves_frozen_message(
    matrix_candidate: MatrixCandidate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ai import product_matrix_runs
    from app.ai.rollout_guard import CapabilityUnavailableError

    def unavailable(_key: str) -> None:
        raise CapabilityUnavailableError("CAPABILITY_DISABLED")

    monkeypatch.setattr(product_matrix_runs, "require_live_key", unavailable)
    fixture = matrix_candidate
    conversation = fixture.conversation()
    body, saved = fixture.save(conversation)
    candidate = fixture.private
    before = candidate.stored(conversation)
    candidate.post(f"/api/conversations/{conversation['id']}/messages/{saved['id']}/run", {}, 409)
    assert candidate.stored(conversation) == before
    assert candidate.save(conversation, body) == saved
    assert_no_runs(candidate)


def test_sql_matrix_run_rejects_forged_original_result(matrix_candidate: MatrixCandidate) -> None:
    fixture = matrix_candidate
    conversation = fixture.conversation()
    _, saved = fixture.save(conversation)
    fixed = saved["product_work_request"]
    candidate = fixture.private
    before = candidate.stored(conversation)
    now = datetime.now(UTC)
    with (
        candidate.scope.engine.begin() as c,
        pytest.raises(
            DBAPIError,
            match="Matrix run must match its exact saved request and original frozen result",
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
                context_version="product-matrix-request-v1",
                run_context={
                    "matrix_selection": fixed["selection"],
                    "matrix_expected_digest": fixed["expected_digest"],
                    "matrix_user_instruction": fixed["user_instruction"],
                    "matrix_source": {
                        "selection": fixed["selection"],
                        "digest": fixed["expected_digest"],
                        "market_space_id": candidate.space_id,
                        "actor_id": str(candidate.scope.owner_id),
                        "record_result_digest": "0" * 64,
                    },
                },
            )
        )
    assert candidate.stored(conversation) == before
    assert_no_runs(candidate)


def conversation_sequence(candidate: Candidate, conversation: dict[str, Any]) -> int:
    with candidate.scope.engine.connect() as c:
        return int(
            c.execute(
                select(tables.conversations.c.next_sequence).where(
                    tables.conversations.c.tenant_id == candidate.scope.tenant_id,
                    tables.conversations.c.id == UUID(conversation["id"]),
                )
            ).scalar_one()
        )


def test_sql_unknown_kind_rejects_insert_without_advancing_history(
    matrix_candidate: MatrixCandidate,
) -> None:
    fixture = matrix_candidate
    conversation = fixture.conversation()
    _, saved = fixture.save(conversation)
    candidate = fixture.private
    before = candidate.stored(conversation)
    sequence = conversation_sequence(candidate, conversation)
    fixed = {**saved["product_work_request"], "kind": "forged_matrix_agent"}
    with (
        candidate.scope.engine.begin() as c,
        pytest.raises(DBAPIError, match="Unknown product conversation request kind"),
        c.begin_nested(),
    ):
        c.execute(
            tables.conversation_messages.insert().values(
                id=uuid4(),
                tenant_id=candidate.scope.tenant_id,
                project_id=None,
                conversation_id=UUID(conversation["id"]),
                author_user_id=candidate.scope.owner_id,
                sequence=sequence,
                context_version=conversation["context_version"],
                request_id=uuid4(),
                request_digest="a" * 64,
                body="拒绝未知类型",
                action="product_work",
                dispatch_input="拒绝未知类型",
                operation_request_id=str(uuid4()),
                product_work_request=fixed,
            )
        )
    assert candidate.stored(conversation) == before
    assert conversation_sequence(candidate, conversation) == sequence
    assert_no_runs(candidate)


class PrivateMemoryStore:
    """Only the object storage boundary is synthetic; upload/parser/SQL are real."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, *, object_key: str, content: bytes, media_type: str, sha256: str) -> None:
        from hashlib import sha256 as hash_bytes

        assert hash_bytes(content).hexdigest() == sha256
        assert media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        self.objects[object_key] = content

    def get(self, *, object_key: str, max_bytes: int) -> bytes:
        content = self.objects[object_key]
        assert len(content) <= max_bytes
        return content

    def delete(self, *, object_key: str) -> None:
        self.objects.pop(object_key, None)


def test_sql_matrix_binding_rejects_legally_uploaded_extracted_attachment(
    matrix_candidate: MatrixCandidate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hashlib import sha256
    from io import BytesIO

    from openpyxl import Workbook

    from app.main import app
    from app.storage.documents import get_document_object_store

    fixture = matrix_candidate
    candidate = fixture.private
    conversation = fixture.conversation()
    store = PrivateMemoryStore()
    overrides: dict[Callable[..., Any], Callable[..., Any]] = dict(app.dependency_overrides)
    overrides[get_document_object_store] = lambda: store
    monkeypatch.setattr(app, "dependency_overrides", overrides)
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["来源", "合成待验证工艺约束"])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    content = output.getvalue()
    attachment = candidate.post(
        f"/api/conversations/{conversation['id']}/attachments",
        {
            "request_id": str(uuid4()),
            "filename": "synthetic-matrix-source.xlsx",
            "size_bytes": len(content),
            "sha256": sha256(content).hexdigest(),
            "classification": "internal",
        },
    )
    base = f"/api/conversations/{conversation['id']}/attachments/{attachment['id']}"
    uploaded = candidate.client.post(base + "/content", headers=candidate.headers, content=content)
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["status"] == "uploaded"
    parsed = candidate.post(base + "/parse", {})
    assert parsed["status"] == "extracted", parsed
    with candidate.scope.engine.connect() as c:
        row = (
            c.execute(
                select(tables.conversation_attachments).where(
                    tables.conversation_attachments.c.id == UUID(attachment["id"]),
                )
            )
            .mappings()
            .one()
        )
        assert row["status"] == "extracted" and row["classification"] == "internal"
        assert row["fragments"], "Actual XLSX parser must retain nonempty source text"
    _, saved = fixture.save(conversation)
    before = candidate.stored(conversation)
    sequence = conversation_sequence(candidate, conversation)
    with (
        candidate.scope.engine.begin() as c,
        pytest.raises(DBAPIError, match="Matrix requests cannot use private attachment bindings"),
        c.begin_nested(),
    ):
        c.execute(
            tables.conversation_message_attachments.insert().values(
                tenant_id=candidate.scope.tenant_id,
                project_id=None,
                conversation_id=UUID(conversation["id"]),
                message_id=UUID(saved["id"]),
                attachment_id=UUID(attachment["id"]),
                ordinal=1,
            )
        )
    with candidate.scope.engine.connect() as c:
        assert (
            c.execute(
                select(func.count())
                .select_from(tables.conversation_message_attachments)
                .where(tables.conversation_message_attachments.c.message_id == UUID(saved["id"]))
            ).scalar_one()
            == 0
        )
    assert candidate.stored(conversation) == before
    assert conversation_sequence(candidate, conversation) == sequence
    assert_no_runs(candidate)


def test_sql_downgrade_protection_preserves_matrix_history(
    matrix_candidate: MatrixCandidate,
) -> None:
    from importlib import import_module

    from sqlalchemy import text

    migration = import_module("migrations.versions.0413_conversation_matrix_runs")
    fixture = matrix_candidate
    candidate = fixture.private
    conversation = fixture.conversation()
    _, saved = fixture.save(conversation)
    before = candidate.stored(conversation)
    sequence = conversation_sequence(candidate, conversation)
    with (
        candidate.scope.engine.begin() as c,
        pytest.raises(DBAPIError, match="Retain conversation matrix request and run history"),
        c.begin_nested(),
    ):
        # Run only the actual PL/pgSQL refusal block; never downgrade the schema.
        c.execute(text(migration.DOWNGRADE_PROTECTION))
    assert candidate.stored(conversation) == before
    assert conversation_sequence(candidate, conversation) == sequence
    assert candidate.read(conversation)["items"][0]["id"] == saved["id"]
    assert_no_runs(candidate)
