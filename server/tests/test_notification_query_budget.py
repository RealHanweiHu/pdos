"""Notification summaries stay bounded as unread history grows."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.db.schema import tables
from app.domain.reminders import ReminderService
from tests import test_reminders_api as reminder_fixtures
from tests.test_reminders_api import Scope

client = reminder_fixtures.client
isolated_reminder_database = reminder_fixtures.isolated_reminder_database
NOW = datetime(2026, 9, 8, tzinfo=UTC)


@pytest.fixture
def scope(client: TestClient, isolated_reminder_database: str) -> Iterator[Scope]:
    value = Scope(client, isolated_reminder_database)
    try:
        yield value
    finally:
        value.dispose()


@pytest.mark.parametrize("unread_per_policy", [1, 1000])
def test_notification_counts_cover_full_unread_history_in_two_queries(
    scope: Scope, unread_per_policy: int
) -> None:
    other_recipient = scope.user("other", "engineer")
    project_id = scope.project(member_ids=(other_recipient,))
    values: list[dict[str, Any]] = []

    def reminder(recipient: UUID, policy: str, status: str) -> dict[str, Any]:
        reminder_id = uuid4()
        return {
            "id": reminder_id,
            "tenant_id": scope.tenant_id,
            "project_id": project_id,
            "recipient_user_id": recipient,
            "target_entity": "task",
            "target_entity_id": uuid4(),
            "policy_key": policy,
            "title": f"Reminder {reminder_id}",
            "dedupe_key": str(reminder_id),
            "status": status,
            "fire_at": NOW,
            "fired_at": NOW if status in {"fired", "acknowledged"} else None,
            "acknowledged_at": NOW if status == "acknowledged" else None,
        }

    for policy in ("task_accept", "task_due_overdue1"):
        values.extend(reminder(scope.owner_id, policy, "fired") for _ in range(unread_per_policy))
    values.extend(reminder(scope.owner_id, "issue_verify", "acknowledged") for _ in range(50))
    values.extend(reminder(other_recipient, "issue_stalled", "fired") for _ in range(100))
    values.append(reminder(scope.owner_id, "task_due_t1", "scheduled"))
    with scope.engine.begin() as connection:
        connection.execute(tables.reminders.insert(), values)
    statements: list[str] = []

    def observe(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(scope.engine, "before_cursor_execute", observe)
    try:
        items, unread, digest = ReminderService(scope.engine).list_notifications(
            tenant_id=scope.tenant_id, recipient_user_id=scope.owner_id, limit=50
        )
        assert len(statements) == 2
        assert "GROUP BY" in statements[1]
        assert len(items) == 50
        assert unread == unread_per_policy * 2
        assert digest == {
            "task_accept": unread_per_policy,
            "task_due_overdue1": unread_per_policy,
        }
        assert all(item.status in {"fired", "acknowledged"} for item, _, _ in items)
        statements.clear()
        assert ReminderService(scope.engine).list_notifications(
            tenant_id=uuid4(), recipient_user_id=scope.owner_id, limit=50
        ) == ([], 0, {})
        assert len(statements) == 2
    finally:
        event.remove(scope.engine, "before_cursor_execute", observe)
