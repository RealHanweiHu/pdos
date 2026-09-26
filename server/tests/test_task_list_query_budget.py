"""Task list query budgets and dependency semantics against isolated PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event

from app.db.schema import tables
from app.domain.tasks import TaskService
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


def project(scope: Scope, code: str, *, tenant_id: UUID | None = None) -> UUID:
    tenant_id = tenant_id or scope.tenant_id
    workflow_id = scope._insert(
        tables.workflows, {"tenant_id": tenant_id, "code": code, "name": code}
    )
    return scope._insert(
        tables.projects,
        {"tenant_id": tenant_id, "workflow_id": workflow_id, "code": code, "name": code},
    )


def task(scope: Scope, project_id: UUID, status: str, *, index: int = 0) -> UUID:
    return scope._insert(
        tables.tasks,
        {
            "project_id": project_id,
            "title": f"Task {index}",
            "status": status,
            "blocked_reason": "Waiting for hardware" if status == "blocked" else None,
            "completed_at": NOW if status == "done" else None,
            "updated_at": NOW + timedelta(seconds=index),
        },
    )


def depend(scope: Scope, project_id: UUID, task_id: UUID, *predecessors: UUID) -> None:
    with scope.engine.begin() as connection:
        connection.execute(
            tables.task_dependencies.insert(),
            [
                {
                    "id": uuid4(),
                    "tenant_id": scope.tenant_id,
                    "project_id": project_id,
                    "task_id": task_id,
                    "depends_on_task_id": predecessor,
                }
                for predecessor in predecessors
            ],
        )


@pytest.mark.parametrize("task_count", [1, 500])
def test_list_query_count_stays_constant_and_empty_scope_needs_no_dependency_read(
    scope: Scope, task_count: int
) -> None:
    project_id = project(scope, "BUDGET")
    ids = [uuid4() for _ in range(task_count)]
    with scope.engine.begin() as connection:
        connection.execute(
            tables.tasks.insert(),
            [
                {
                    "id": task_id,
                    "tenant_id": scope.tenant_id,
                    "project_id": project_id,
                    "title": f"Task {index}",
                    "updated_at": NOW + timedelta(seconds=index),
                }
                for index, task_id in enumerate(ids)
            ],
        )
    if task_count > 1:
        for index in range(1, task_count):
            depend(scope, project_id, ids[index], *ids[max(0, index - 3) : index])
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
        records = TaskService(scope.engine).list(tenant_id=scope.tenant_id, project_id=project_id)
        assert len(statements) == 2
        assert [record.id for record in records] == ids[::-1]
        for record in records:
            index = ids.index(record.id)
            expected = tuple(sorted(ids[max(0, index - 3) : index], key=str))
            assert record.dependency_task_ids == expected
            assert record.unresolved_dependency_ids == expected
            assert record.readiness == ("waiting" if expected else "ready")
        statements.clear()
        assert TaskService(scope.engine).list(tenant_id=scope.tenant_id, project_id=uuid4()) == []
        assert len(statements) == 1
    finally:
        event.remove(scope.engine, "before_cursor_execute", observe)


def test_batch_preserves_get_readiness_order_and_tenant_project_boundaries(scope: Scope) -> None:
    project_id = project(scope, "SEMANTICS")
    other_project = project(scope, "OTHER")
    outsider = task(scope, other_project, "todo")
    statuses = ["done", "skipped", "in_progress", "todo", "blocked", "pending_approval", "todo"]
    ids = [task(scope, project_id, status, index=index) for index, status in enumerate(statuses)]
    depend(scope, project_id, ids[3], *ids[:3])
    depend(scope, project_id, ids[4], ids[2])
    depend(scope, project_id, ids[5], ids[2])
    depend(scope, project_id, ids[6], *ids[:2])
    foreign_tenant = uuid4()
    with scope.engine.begin() as connection:
        connection.execute(
            tables.tenants.insert(),
            {
                "id": foreign_tenant,
                "slug": "foreign",
                "name": "Foreign tenant",
            },
        )
    foreign_project = project(scope, "FOREIGN", tenant_id=foreign_tenant)
    service = TaskService(scope.engine)
    records = service.list(tenant_id=scope.tenant_id, project_id=project_id)
    assert [record.id for record in records] == ids[::-1]
    assert outsider not in {record.id for record in records}
    assert [record.readiness for record in records] == [
        "ready",
        "waiting_approval",
        "blocked",
        "waiting",
        "ready",
        "complete",
        "complete",
    ]
    assert records[3].unresolved_dependency_ids == (ids[2],)
    for record in records:
        assert record == service.get(
            tenant_id=scope.tenant_id, project_id=project_id, task_id=record.id
        )
    assert service.list(tenant_id=foreign_tenant, project_id=project_id) == []
    assert service.list(tenant_id=scope.tenant_id, project_id=foreign_project) == []


def test_list_uses_one_snapshot_when_a_predecessor_finishes_between_queries(scope: Scope) -> None:
    project_id = project(scope, "SNAPSHOT")
    predecessor = task(scope, project_id, "in_progress")
    dependent = task(scope, project_id, "todo", index=1)
    depend(scope, project_id, dependent, predecessor)
    writer_engine = create_engine(scope.engine.url)
    changed = False

    def complete_after_task_read(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        nonlocal changed
        if changed or "FROM cehub_project.tasks" not in statement:
            return
        changed = True
        with writer_engine.begin() as writer:
            writer.execute(
                tables.tasks.update()
                .where(tables.tasks.c.id == predecessor)
                .values(status="done", completed_at=NOW)
            )

    event.listen(scope.engine, "after_cursor_execute", complete_after_task_read)
    try:
        records = TaskService(scope.engine).list(tenant_id=scope.tenant_id, project_id=project_id)
    finally:
        event.remove(scope.engine, "after_cursor_execute", complete_after_task_read)
        writer_engine.dispose()
    assert changed
    by_id = {record.id: record for record in records}
    assert by_id[predecessor].status == "in_progress"
    assert by_id[dependent].readiness == "waiting"
    assert by_id[dependent].unresolved_dependency_ids == (predecessor,)
    refreshed = TaskService(scope.engine).list(tenant_id=scope.tenant_id, project_id=project_id)
    assert {record.id: record for record in refreshed}[dependent].readiness == "ready"
