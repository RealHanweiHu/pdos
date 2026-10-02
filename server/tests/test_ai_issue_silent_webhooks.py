"""Silent AI completions never leak through automatic or legacy webhook queues.

All SQL is recorded, never executed. Explicit-send query contracts are compiled
against PostgreSQL; the trusted AI-origin classifier is replaced at its boundary.
"""

import json
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock
from uuid import UUID

import psycopg
import pytest
from sqlalchemy import Engine
from sqlalchemy.dialects import postgresql

from app.auth.repository import AuthContext
from app.domain import webhook_sources as sources
from app.domain.product_workspace import ProductWorkError
from app.integrations import webhook_worker as worker
from app.integrations.webhook_protocol import WebhookTransport, body_bytes

TENANT = UUID("11111111-1111-4111-8111-111111111111")
PROJECT = UUID("22222222-2222-4222-8222-222222222222")
ISSUE = UUID("33333333-3333-4333-8333-333333333333")
ENDPOINT = UUID("44444444-4444-4444-8444-444444444444")
DELIVERY = UUID("55555555-5555-4555-8555-555555555555")
ATTEMPT = UUID("66666666-6666-4666-8666-666666666666")
ACTOR = UUID("77777777-7777-4777-8777-777777777777")
CONTROL = UUID("88888888-8888-4888-8888-888888888888")
NOW = datetime.now(UTC)
CONTEXT = cast(AuthContext, SimpleNamespace(tenant=SimpleNamespace(id=TENANT)))
EVENT = {
    "id": 31,
    "tenant_id": TENANT,
    "project_id": PROJECT,
    "entity_id": ISSUE,
    "event_type": "ISSUE_CREATED",
    "event_id": "original-issue-created",
    "timestamp": NOW,
}
ISSUE_ROW = {
    "id": ISSUE,
    "title": "测试异常",
    "status": "open",
    "severity": "high",
    "owner_user_id": None,
    "updated_at": NOW,
}
ENDPOINT_ROW = {
    "id": ENDPOINT,
    "tenant_id": TENANT,
    "project_id": PROJECT,
    "audience": "internal",
    "topics": ["work.updated"],
    "expires_at": NOW + timedelta(days=1),
    "auto_start_at": NOW - timedelta(days=1),
    "url": "https://receiver.invalid/pdos",
}


class Result:
    def __init__(self, value: Any = None):
        self.value = value

    def mappings(self) -> "Result":
        return self

    def scalars(self) -> "Result":
        return self

    def one_or_none(self) -> Any:
        return self.value

    def scalar_one_or_none(self) -> Any:
        return self.value

    def one(self) -> Any:
        assert self.value is not None
        return self.value

    def all(self) -> list[Any]:
        assert isinstance(self.value, list)
        return self.value


class Connection:
    """Consume explicit read replies; capture real SQL statements and writes."""

    def __init__(self, *replies: Any):
        self.replies = deque(replies)
        self.reads: list[Any] = []
        self.writes: list[Any] = []

    def execute(self, statement: Any) -> Result:
        if statement.is_select:
            self.reads.append(statement)
            assert self.replies, "Unexpected SQL read in a pure test"
            return Result(self.replies.popleft())
        self.writes.append(statement)
        return Result()


class MemoryEngine:
    def __init__(self, connection: Connection):
        self.connection = connection

    @contextmanager
    def begin(self) -> Iterator[Connection]:
        yield self.connection


def forbidden(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("This test must never connect to a database or external receiver")


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(WebhookTransport, "post", forbidden)
    monkeypatch.setattr(sources, "authorize", Mock())
    monkeypatch.setattr(worker, "authorize", Mock())
    monkeypatch.setattr(worker, "principal", Mock(return_value=CONTEXT))


@pytest.mark.parametrize(
    ("automated", "proven_ai", "silent"),
    [(True, True, True), (False, True, False), (True, False, False)],
    ids=["automated-ai-is-silent", "explicit-human-send-kept", "unproven-origin-not-misclassified"],
)
def test_notification_uses_trusted_origin_only_for_automatic_sends(
    monkeypatch: pytest.MonkeyPatch, automated: bool, proven_ai: bool, silent: bool
) -> None:
    classifier = Mock(return_value=proven_ai)
    monkeypatch.setattr(sources, "is_silent_ai_issue_event", classifier)
    c = Connection(EVENT, *([] if silent else [ISSUE_ROW]))
    if silent:
        with pytest.raises(sources.SilentAICompletion, match="静默"):
            sources.notification(c, CONTEXT, ENDPOINT_ROW, 31, automated=automated)
        assert len(c.reads) == 1  # Stop before projecting a message body.
    else:
        result = sources.notification(c, CONTEXT, ENDPOINT_ROW, 31, automated=automated)
        assert result["topic"] == "work.updated"
        assert result["data"]["current_record"]["title"] == ISSUE_ROW["title"]
    assert classifier.call_count == int(automated)
    assert not c.replies


def test_withdrawn_issue_cannot_be_projected_even_for_an_explicit_send() -> None:
    c = Connection(EVENT, None)
    with pytest.raises(ProductWorkError, match="原工作项不可读取"):
        sources.notification(c, CONTEXT, ENDPOINT_ROW, 31)
    query = str(c.reads[-1].compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]
    assert "issues.withdrawn_at IS NULL" in query
    assert "issues.tenant_id" in query and "issues.project_id" in query
    assert not c.replies


@pytest.mark.parametrize("actor", [None, ACTOR], ids=["no-immutable-consent", "named-consent"])
def test_explicit_send_requires_scoped_immutable_queue_audit_or_named_retry(
    actor: UUID | None,
) -> None:
    c = Connection(actor)
    delivery = {
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "id": DELIVERY,
        "status": "retry_wait",
        "reason": "pretend this mutable text was a human send",
    }
    assert sources.has_explicit_send(c, delivery) is (actor is not None)
    compiled = c.reads[0].compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
    sql, params = str(compiled), compiled.params
    assert "UNION ALL" in sql
    assert "audit_log.after_snapshot" in sql and "IS false" in sql
    assert "audit_log.actor_user_id IS NOT NULL" in sql
    assert "webhook_delivery_actions.actor_user_id IS NOT NULL" in sql
    for value in (TENANT, PROJECT, DELIVERY, "webhook.queued", "automated", "retry"):
        assert value in params.values()
    assert "webhook_service" in params.values() and "WEBHOOK_RECORDED" in params.values()
    assert "events.timestamp = cehub_audit.audit_log.timestamp" in sql
    assert "webhook_deliveries.reason" not in sql
    assert "webhook_deliveries.status" not in sql
    assert not c.replies


def test_dispatch_records_the_scan_but_does_not_queue_automatic_ai_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = Connection([ENDPOINT_ROW], [31], EVENT)
    monkeypatch.setattr(sources, "is_silent_ai_issue_event", Mock(return_value=True))
    insert = Mock(side_effect=AssertionError("Silent success must not create a delivery"))
    monkeypatch.setattr(worker, "insert_delivery", insert)
    subject = worker.WebhookWorker(cast(Engine, MemoryEngine(c)))
    assert subject.dispatch() == 0
    insert.assert_not_called()
    scan = next(s for s in c.writes if s.table.name == "webhook_scans")
    values = scan.compile().params
    assert values["source_event_id"] == 31
    assert values["delivery_id"] is None
    assert values["result"] == "not_applicable_or_unavailable"
    assert not c.replies


@pytest.mark.parametrize(
    ("consent", "source_exists", "expected"),
    [
        (None, True, "cancelled"),
        ("queued", True, "delivered"),
        ("retry", True, "delivered"),
        ("retry", False, "source_changed"),
    ],
    ids=["legacy-or-unknown-auto-queue", "named-original-send", "explicit-retry", "withdrawn"],
)
def test_delivery_rechecks_explicit_consent_and_never_posts_silent_or_withdrawn_sources(
    monkeypatch: pytest.MonkeyPatch, consent: str | None, source_exists: bool, expected: str
) -> None:
    payload = {"event_id": "original-issue-created", "title": "测试异常"}
    basis = sources.notification(Connection(EVENT, ISSUE_ROW), CONTEXT, ENDPOINT_ROW, 31)
    attempt = {
        "delivery_id": DELIVERY,
        "control_id": CONTROL,
        "signed_timestamp": int(datetime.now(UTC).timestamp()),
    }
    delivery = {
        "id": DELIVERY,
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "endpoint_id": ENDPOINT,
        "lease_id": ATTEMPT,
        "lease_until": datetime.now(UTC) + timedelta(minutes=2),
        "status": "sending",
        "source_event_id": 31,
        "attempt_count": 1,
        "attempt_limit": 3,
        "payload": payload,
        "payload_digest": sha256(body_bytes(payload)).hexdigest(),
        "basis_digest": basis["digest"],
        "reason": "manually edited claim, not trusted consent",
    }
    c = Connection(
        attempt,
        delivery,
        ENDPOINT_ROW,
        delivery,
        ACTOR if consent else None,
        EVENT,
        *([] if consent is None else [ISSUE_ROW if source_exists else None]),
    )
    classifier = Mock(return_value=True)
    monkeypatch.setattr(sources, "is_silent_ai_issue_event", classifier)
    monkeypatch.setattr(worker, "control", Mock(return_value={"id": CONTROL, "status": "active"}))
    monkeypatch.setattr(
        worker, "get_settings", lambda: SimpleNamespace(webhook_delivery_enabled=True)
    )
    decrypt = Mock(return_value=b"synthetic-test-signing-key")
    monkeypatch.setattr(worker, "decrypt_key", decrypt)
    record = Mock()
    monkeypatch.setattr(worker, "worker_event", record)
    transport = Mock(spec=WebhookTransport)
    transport.post.return_value = (
        200,
        json.dumps(
            {
                "delivery_id": str(DELIVERY),
                "event_id": "original-issue-created",
                "accepted": True,
            }
        ).encode(),
    )
    subject = worker.WebhookWorker(cast(Engine, MemoryEngine(c)), transport=transport)
    assert subject.deliver(ATTEMPT) == expected
    updates = {s.table.name: s.compile().params for s in c.writes}
    assert updates["webhook_deliveries"]["status"] == expected
    if expected == "delivered":
        transport.post.assert_called_once()
        assert updates["webhook_attempts"]["outcome"] == "delivered"
        assert classifier.call_count == 0
    else:
        transport.post.assert_not_called()
        decrypt.assert_not_called()
        assert updates["webhook_attempts"]["outcome"] == "abandoned"
        assert updates["webhook_attempts"]["error_code"] == (
            "silent_ai_success" if expected == "cancelled" else "source_or_principal_changed"
        )
    assert updates["webhook_deliveries"]["lease_id"] is None
    record.assert_called_once()
    assert not c.replies
