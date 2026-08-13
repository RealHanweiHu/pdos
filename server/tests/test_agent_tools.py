from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine, text

from app.ai.embeddings import EmbeddingResult
from app.ai.runtime_contract import AgentKey, EventReference, FrozenRunContext
from app.ai.tools import TOOL_DEFINITIONS, AgentReadTools, ToolScopeViolationError
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.memories import MemoryDraft, MemoryService

SERVER_ROOT = Path(__file__).resolve().parents[1]


class StaticEmbeddingGateway:
    provider = "test"
    model = "memory-v1"
    dimensions = 3

    def embed(self, text_value: str) -> EmbeddingResult:
        assert text_value.strip()
        return EmbeddingResult(provider=self.provider, model=self.model, values=(1.0, 0.0, 0.0))


@pytest.fixture
def agent_tools_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
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
        {"id": workflow_id, "tenant_id": tenant_id, "code": "npd", "name": "NPD"},
    )
    connection.execute(
        tables.projects.insert(),
        {
            "id": project_id,
            "tenant_id": tenant_id,
            "workflow_id": workflow_id,
            "code": f"PRJ-{slug.upper()}",
            "name": slug.title(),
            "status": "active",
        },
    )
    return tenant_id, project_id


def frozen_context(*, tenant_id: UUID, project_id: UUID) -> FrozenRunContext:
    occurred_at = datetime(2026, 8, 11, 20, 1, tzinfo=UTC)
    return FrozenRunContext(
        tenant_id=tenant_id,
        project_id=project_id,
        run_id=uuid4(),
        agent_key=AgentKey.PROJECT_INTELLIGENCE,
        built_at=occurred_at + timedelta(minutes=15),
        window_started_at=occurred_at - timedelta(minutes=1),
        window_ended_at=occurred_at + timedelta(minutes=14),
        trigger_events=(
            EventReference(
                id=1,
                event_type="ISSUE_CREATED",
                entity="issue",
                entity_id=uuid4(),
                timestamp=occurred_at,
            ),
        ),
        project={"id": str(project_id), "code": "PRJ-1", "status": "active"},
        execution={"open_issue_count": 2},
    )


def append_event(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    number: int,
) -> int:
    return int(
        connection.execute(
            tables.events.insert()
            .values(
                tenant_id=tenant_id,
                project_id=project_id,
                event_id=f"issue:{project_id}:{number}",
                event_type="ISSUE_CREATED",
                schema_version=1,
                source="tool_test",
                entity="issue",
                entity_id=uuid4(),
                payload={"private_description": "must not leave tool"},
                timestamp=datetime(2026, 8, 11, 20, number, tzinfo=UTC),
            )
            .returning(tables.events.c.id)
        ).scalar_one()
    )


def test_tool_definitions_freeze_use_do_not_use_negative_example_and_boundary() -> None:
    assert [definition.name for definition in TOOL_DEFINITIONS] == [
        "get_project_context",
        "search_memory",
        "get_recent_events",
    ]
    for definition in TOOL_DEFINITIONS:
        assert "Use when" in definition.description
        assert "Do not use" in definition.description
        assert "Negative example" in definition.description
        assert "Boundary" in definition.description
        assert definition.input_example


def test_tools_fail_close_on_claimed_scope_and_memory_is_explicitly_not_enabled(
    agent_tools_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(agent_tools_database_url))
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection, slug="bound")
        tools = AgentReadTools(
            engine,
            run_context=frozen_context(tenant_id=tenant_id, project_id=project_id),
        )

        with pytest.raises(ToolScopeViolationError):
            tools.get_project_context(project_id=uuid4())
        with pytest.raises(ToolScopeViolationError):
            tools.get_recent_events(project_id=uuid4())
        with pytest.raises(ToolScopeViolationError):
            tools.search_memory(project_id=uuid4(), query="injected scope")

        project = tools.get_project_context(project_id=project_id)
        assert project.project["id"] == str(project_id)
        memory = tools.search_memory(project_id=project_id, query="gate readiness")
        assert memory.source_status == "not_enabled"
        assert memory.shown_count == memory.total_count == 0
        assert not memory.truncated
        assert "已显示 0 之 0 条" in memory.continuation
    finally:
        engine.dispose()


def test_memory_search_returns_only_verified_project_scoped_memory(
    agent_tools_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(agent_tools_database_url))
    gateway = StaticEmbeddingGateway()
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection, slug="memory")
            other_tenant_id, other_project_id = seed_project(connection, slug="memory-other")
            creator_id = uuid4()
            verifier_id = uuid4()
            for user_id, username in (
                (creator_id, "memory-creator"),
                (verifier_id, "memory-verifier"),
            ):
                connection.execute(
                    tables.users.insert(),
                    {
                        "id": user_id,
                        "tenant_id": tenant_id,
                        "username": username,
                        "display_name": username,
                        "role": "quality",
                    },
                )
            other_creator_id = uuid4()
            other_verifier_id = uuid4()
            for user_id, username in (
                (other_creator_id, "other-creator"),
                (other_verifier_id, "other-verifier"),
            ):
                connection.execute(
                    tables.users.insert(),
                    {
                        "id": user_id,
                        "tenant_id": other_tenant_id,
                        "username": username,
                        "display_name": username,
                        "role": "quality",
                    },
                )
        service = MemoryService(engine)
        verified = service.create(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=creator_id,
            draft=MemoryDraft(
                title="Gate readiness lesson",
                content="Validate connector pin mapping before DVT.",
                tags=("DVT",),
            ),
        )
        service.verify(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=verifier_id,
            memory_id=verified.id,
            gateway=gateway,
        )
        service.create(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=creator_id,
            draft=MemoryDraft(title="Draft secret", content="Must not be retrieved."),
        )
        other = service.create(
            tenant_id=other_tenant_id,
            project_id=other_project_id,
            actor_user_id=other_creator_id,
            draft=MemoryDraft(title="Other tenant", content="Must remain isolated."),
        )
        service.verify(
            tenant_id=other_tenant_id,
            project_id=other_project_id,
            actor_user_id=other_verifier_id,
            memory_id=other.id,
            gateway=gateway,
        )
        tools = AgentReadTools(
            engine,
            run_context=frozen_context(tenant_id=tenant_id, project_id=project_id),
            embedding_gateway=gateway,
        )

        page = tools.search_memory(project_id=project_id, query="connector DVT", limit=10)

        assert page.source_status == "ready"
        assert page.shown_count == page.total_count == 1
        assert page.items[0]["memory_id"] == str(verified.id)
        assert page.items[0]["title"] == "Gate readiness lesson"
        assert "created_by_user_id" not in page.items[0]
        assert "embedding" not in page.items[0]
    finally:
        engine.dispose()


def test_recent_events_are_tenant_bound_payload_free_and_explicitly_paginated(
    agent_tools_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(agent_tools_database_url))
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection, slug="page")
            other_tenant_id, other_project_id = seed_project(connection, slug="other")
            event_ids = [
                append_event(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    number=number,
                )
                for number in range(1, 4)
            ]
            append_event(
                connection,
                tenant_id=other_tenant_id,
                project_id=other_project_id,
                number=4,
            )
        tools = AgentReadTools(
            engine,
            run_context=frozen_context(tenant_id=tenant_id, project_id=project_id),
        )

        first = tools.get_recent_events(project_id=project_id, limit=2)
        assert [item["id"] for item in first.items] == event_ids[:2]
        assert first.shown_count == 2
        assert first.total_count == 3
        assert first.truncated
        assert first.next_after_id == event_ids[1]
        assert f"已显示 2 之 3 条；使用 after_id={event_ids[1]} 续读。" == first.continuation
        assert "payload" not in first.items[0]

        second = tools.get_recent_events(
            project_id=project_id,
            after_id=first.next_after_id or 0,
            limit=2,
        )
        assert [item["id"] for item in second.items] == event_ids[2:]
        assert second.shown_count == second.total_count == 1
        assert not second.truncated
        assert second.next_after_id is None
    finally:
        engine.dispose()


def test_document_fragments_are_tenant_bound_and_never_expose_object_keys(
    agent_tools_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(agent_tools_database_url))
    document_id = uuid4()
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection, slug="document")
            user_id = uuid4()
            connection.execute(
                tables.users.insert(),
                {
                    "id": user_id,
                    "tenant_id": tenant_id,
                    "username": "uploader",
                    "display_name": "Uploader",
                    "role": "engineer",
                },
            )
            connection.execute(
                tables.documents.insert(),
                {
                    "id": document_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "uploaded_by_user_id": user_id,
                    "object_key": "private/source.xlsx",
                    "filename": "source.xlsx",
                    "media_type": (
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    ),
                    "classification": "internal",
                    "size_bytes": 10,
                    "sha256": "a" * 64,
                    "extraction_status": "extracted",
                    "fragment_count": 1,
                },
            )
            connection.execute(
                tables.document_fragments.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "document_id": document_id,
                    "ordinal": 1,
                    "locator": "sheet:Risk,rows:1-2",
                    "text": "Connector delay\tHigh",
                },
            )
        tools = AgentReadTools(
            engine,
            run_context=frozen_context(tenant_id=tenant_id, project_id=project_id),
        )

        page = tools.get_document_fragments(
            project_id=project_id,
            document_id=document_id,
        )

        assert page.shown_count == page.total_count == 1
        assert page.items[0]["locator"] == "sheet:Risk,rows:1-2"
        assert "object_key" not in page.items[0]
        assert "private/source.xlsx" not in str(page.items)
        with pytest.raises(ToolScopeViolationError):
            tools.get_document_fragments(project_id=uuid4(), document_id=document_id)

        with engine.begin() as connection:
            connection.execute(
                tables.documents.update()
                .where(tables.documents.c.id == document_id)
                .values(classification="confidential")
            )
        assert (
            tools.get_document_fragments(
                project_id=project_id,
                document_id=document_id,
            ).shown_count
            == 0
        )
    finally:
        engine.dispose()
