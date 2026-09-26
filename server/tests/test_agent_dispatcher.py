from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine, select

from app.ai.context_builder import RunContextBuilder
from app.ai.runtime_contract import AgentKey
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.worker.dispatcher import AgentDispatcher
from tests.db_cleanup import clear_test_tenants

SERVER_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def dispatcher_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            clear_test_tenants(connection)
        yield test_url
    finally:
        engine.dispose()
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


def seed_project(connection: Connection, *, slug: str) -> tuple[UUID, UUID]:
    tenant_id = uuid4()
    workflow_id = uuid4()
    project_id = uuid4()
    connection.execute(
        tables.tenants.insert(),
        {"id": tenant_id, "slug": slug, "name": slug.title()},
    )
    connection.execute(
        tables.workflows.insert(),
        {
            "id": workflow_id,
            "tenant_id": tenant_id,
            "code": "npd",
            "name": "NPD",
        },
    )
    connection.execute(
        tables.projects.insert(),
        {
            "id": project_id,
            "tenant_id": tenant_id,
            "workflow_id": workflow_id,
            "code": f"PRJ-{slug.upper()}",
            "name": f"Project {slug.title()}",
            "status": "active",
        },
    )
    return tenant_id, project_id


def append_event(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID | None,
    event_type: str,
    occurred_at: datetime,
) -> int:
    return int(
        connection.execute(
            tables.events.insert()
            .values(
                tenant_id=tenant_id,
                project_id=project_id,
                event_id=f"{event_type.lower()}:{uuid4()}",
                event_type=event_type,
                schema_version=1,
                source="dispatcher_test",
                entity="project",
                entity_id=project_id or uuid4(),
                payload={},
                timestamp=occurred_at,
            )
            .returning(tables.events.c.id)
        ).scalar_one()
    )


def test_dispatcher_atomically_debounces_by_tenant_project_and_agent(
    dispatcher_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(dispatcher_database_url))
    started_at = datetime(2026, 8, 11, 20, tzinfo=UTC)
    try:
        with engine.begin() as connection:
            tenant_a, project_a = seed_project(connection, slug="alpha")
            tenant_b, project_b = seed_project(connection, slug="beta")
            first_id = append_event(
                connection,
                tenant_id=tenant_a,
                project_id=project_a,
                event_type="ISSUE_CREATED",
                occurred_at=started_at,
            )
            second_id = append_event(
                connection,
                tenant_id=tenant_a,
                project_id=project_a,
                event_type="TEST_FAILED",
                occurred_at=started_at + timedelta(minutes=5),
            )
            ignored_id = append_event(
                connection,
                tenant_id=tenant_a,
                project_id=project_a,
                event_type="PROJECT_CREATED",
                occurred_at=started_at + timedelta(minutes=6),
            )
            other_id = append_event(
                connection,
                tenant_id=tenant_b,
                project_id=project_b,
                event_type="ISSUE_CREATED",
                occurred_at=started_at + timedelta(minutes=3),
            )

        dispatcher = AgentDispatcher(engine, debounce_minutes=15)
        result_a = dispatcher.dispatch_tenant(tenant_id=tenant_a)
        result_b = dispatcher.dispatch_tenant(tenant_id=tenant_b)

        assert result_a.scanned_event_count == 3
        assert result_a.routed_event_count == 3
        assert result_a.created_run_count == 2
        assert result_a.merged_event_count == 1
        assert result_a.last_event_row_id == ignored_id
        assert result_b.last_event_row_id == other_id

        with engine.connect() as connection:
            runs = list(
                connection.execute(
                    select(tables.agent_runs).order_by(tables.agent_runs.c.tenant_id)
                ).mappings()
            )
            cursors = list(connection.execute(select(tables.agent_dispatcher_cursors)).mappings())

        alpha_project_run = next(
            row
            for row in runs
            if row["tenant_id"] == tenant_a and row["agent_key"] == AgentKey.PROJECT_INTELLIGENCE
        )
        alpha_quality_run = next(
            row
            for row in runs
            if row["tenant_id"] == tenant_a and row["agent_key"] == AgentKey.QUALITY_INTELLIGENCE
        )
        beta_run = next(row for row in runs if row["tenant_id"] == tenant_b)
        assert alpha_project_run["project_id"] == project_a
        assert alpha_project_run["event_row_ids"] == [first_id, second_id]
        assert alpha_project_run["event_count"] == 2
        assert alpha_project_run["window_started_at"] == started_at
        assert alpha_project_run["window_ended_at"] == started_at + timedelta(minutes=15)
        assert alpha_quality_run["project_id"] == project_a
        assert alpha_quality_run["event_row_ids"] == [second_id]
        assert alpha_quality_run["event_count"] == 1
        assert beta_run["project_id"] == project_b
        assert beta_run["event_row_ids"] == [other_id]
        assert {row["tenant_id"]: row["last_event_row_id"] for row in cursors} == {
            tenant_a: ignored_id,
            tenant_b: other_id,
        }

        repeated = dispatcher.dispatch_tenant(tenant_id=tenant_a)
        assert repeated.scanned_event_count == 0
        assert repeated.created_run_count == 0
        with engine.connect() as connection:
            assert len(list(connection.execute(select(tables.agent_runs)))) == 3
    finally:
        engine.dispose()


def test_paused_subscription_consumes_cursor_without_creating_a_run(
    dispatcher_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(dispatcher_database_url))
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection, slug="paused")
            connection.execute(
                tables.agent_subscriptions.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "agent_key": AgentKey.KNOWLEDGE_LITE,
                    "status": "paused",
                    "paused_reason": "failure threshold reached",
                },
            )
            event_id = append_event(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                event_type="DOCUMENT_UPLOADED",
                occurred_at=datetime(2026, 8, 11, 20, tzinfo=UTC),
            )

        result = AgentDispatcher(engine).dispatch_tenant(tenant_id=tenant_id)

        assert result.scanned_event_count == 1
        assert result.routed_event_count == 0
        assert result.created_run_count == 0
        assert result.last_event_row_id == event_id
        with engine.connect() as connection:
            assert list(connection.execute(select(tables.agent_runs))) == []
    finally:
        engine.dispose()


def test_configurable_debounce_uses_epoch_aligned_windows_across_clock_hours(
    dispatcher_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(dispatcher_database_url))
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection, slug="ninety")
            event_ids = [
                append_event(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    event_type="ISSUE_CREATED",
                    occurred_at=occurred_at,
                )
                for occurred_at in (
                    datetime(2026, 8, 11, 19, 40, tzinfo=UTC),
                    datetime(2026, 8, 11, 20, 10, tzinfo=UTC),
                )
            ]

        result = AgentDispatcher(engine, debounce_minutes=90).dispatch_tenant(tenant_id=tenant_id)

        assert result.created_run_count == 1
        assert result.merged_event_count == 1
        with engine.connect() as connection:
            run = connection.execute(select(tables.agent_runs)).mappings().one()
        assert run["window_started_at"] == datetime(2026, 8, 11, 19, 30, tzinfo=UTC)
        assert run["window_ended_at"] == datetime(2026, 8, 11, 21, tzinfo=UTC)
        assert run["event_row_ids"] == event_ids
    finally:
        engine.dispose()


def test_due_run_is_sealed_with_server_preaggregated_frozen_context(
    dispatcher_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(dispatcher_database_url))
    now = datetime.now(UTC)
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection, slug="context")
            workflow_id = connection.execute(
                select(tables.projects.c.workflow_id).where(tables.projects.c.id == project_id)
            ).scalar_one()
            stage_ids = [uuid4(), uuid4(), uuid4()]
            connection.execute(
                tables.stages.insert(),
                [
                    {
                        "id": stage_id,
                        "tenant_id": tenant_id,
                        "workflow_id": workflow_id,
                        "code": f"s{sequence}",
                        "name": f"Stage {sequence}",
                        "sequence": sequence,
                    }
                    for sequence, stage_id in enumerate(stage_ids, start=1)
                ],
            )
            connection.execute(
                tables.projects.update()
                .where(tables.projects.c.id == project_id)
                .values(current_stage_id=stage_ids[1])
            )
            connection.execute(
                tables.issues.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "title": "Recent issue",
                        "created_at": now - timedelta(days=2),
                    },
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "title": "Old issue",
                        "created_at": now - timedelta(days=10),
                    },
                ],
            )
            connection.execute(
                tables.risks.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "title": "Open risk",
                },
            )
            connection.execute(
                tables.tasks.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "title": "Overdue task",
                    "due_date": now.date() - timedelta(days=1),
                },
            )
            connection.execute(
                tables.gates.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "stage_id": stage_ids[2],
                    "code": "G3",
                    "name": "Gate 3",
                    "review_due_at": now + timedelta(days=4),
                },
            )
            event_id = append_event(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                event_type="ISSUE_CREATED",
                occurred_at=now - timedelta(minutes=16),
            )

        dispatcher = AgentDispatcher(engine)
        dispatcher.dispatch_tenant(tenant_id=tenant_id)
        sealed = dispatcher.seal_due_runs(now=now)

        assert len(sealed.queued_run_ids) == 1
        with engine.connect() as connection:
            run = connection.execute(select(tables.agent_runs)).mappings().one()
        assert run["status"] == "queued"
        assert run["run_context"] == {}
        assert run["event_row_ids"] == [event_id]
        with engine.connect() as connection:
            context = RunContextBuilder().build(connection, run=run, built_at=now)
        assert context.tenant_id == tenant_id
        assert context.project_id == project_id
        assert context.run_id == run["id"]
        assert context.project["current_stage"] == {
            "code": "s2",
            "name": "Stage 2",
            "sequence": 2,
        }
        assert context.execution == {
            "open_issue_count": 2,
            "issues_created_last_7_days": 1,
            "open_risk_count": 1,
            "overdue_task_count": 1,
            "stage_progress_percent": 67,
            "next_gate_due_in_days": 4,
            "remaining_tokens_today": 2_000_000,
            "agent_runs_today": 1,
        }
    finally:
        engine.dispose()


def test_dispatcher_does_not_queue_shadow_agents_in_employee_worker(
    dispatcher_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(dispatcher_database_url))
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection, slug="shadow")
            event_id = append_event(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                event_type="SUPPLIER_DELAY_REPORTED",
                occurred_at=datetime.now(UTC),
            )
        result = AgentDispatcher(engine).dispatch_tenant(tenant_id=tenant_id)
        assert result.last_event_row_id == event_id
        with engine.connect() as connection:
            keys = set(connection.execute(select(tables.agent_runs.c.agent_key)).scalars())
        assert "supplier_intelligence" not in keys
        assert "executive_intelligence" not in keys
    finally:
        engine.dispose()
