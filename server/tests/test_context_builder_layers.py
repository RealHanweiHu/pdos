from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from app.ai.context_builder import RunContextBuilder
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url

SERVER_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def context_builder_database_url() -> Iterator[str]:
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


def seed_project(
    connection: Connection,
    *,
    slug: str,
) -> tuple[UUID, UUID, UUID, UUID]:
    tenant_id = uuid4()
    owner_id = uuid4()
    engineer_id = uuid4()
    inactive_quality_id = uuid4()
    workflow_id = uuid4()
    project_id = uuid4()
    connection.execute(
        tables.tenants.insert(),
        {"id": tenant_id, "slug": slug, "name": slug.title()},
    )
    connection.execute(
        tables.users.insert(),
        [
            {
                "id": owner_id,
                "tenant_id": tenant_id,
                "username": f"owner-{slug}",
                "email": f"private-owner-{slug}@example.invalid",
                "display_name": f"Private Owner {slug}",
                "role": "owner",
                "is_active": True,
            },
            {
                "id": engineer_id,
                "tenant_id": tenant_id,
                "username": f"engineer-{slug}",
                "email": f"private-engineer-{slug}@example.invalid",
                "display_name": f"Private Engineer {slug}",
                "role": "engineer",
                "is_active": True,
            },
            {
                "id": inactive_quality_id,
                "tenant_id": tenant_id,
                "username": f"quality-{slug}",
                "email": None,
                "display_name": f"Private Quality {slug}",
                "role": "quality",
                "is_active": False,
            },
        ],
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
            "owner_user_id": owner_id,
            "code": f"PRJ-{slug.upper()}",
            "name": slug.title(),
            "status": "active",
        },
    )
    connection.execute(
        tables.project_members.insert(),
        [
            {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "project_id": project_id,
                "user_id": owner_id,
                "added_by_user_id": owner_id,
            },
            {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "project_id": project_id,
                "user_id": engineer_id,
                "added_by_user_id": owner_id,
            },
            {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "project_id": project_id,
                "user_id": inactive_quality_id,
                "added_by_user_id": owner_id,
            },
        ],
    )
    return tenant_id, project_id, owner_id, engineer_id


def append_document(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    uploader_id: UUID,
    classification: str,
    extraction_status: str = "extracted",
    fragment_count: int = 1,
) -> UUID:
    document_id = uuid4()
    connection.execute(
        tables.documents.insert(),
        {
            "id": document_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "uploaded_by_user_id": uploader_id,
            "object_key": f"private/{document_id}/source.pdf",
            "filename": f"evidence-{classification}.pdf",
            "media_type": "application/pdf",
            "classification": classification,
            "size_bytes": 100,
            "sha256": "a" * 64,
            "extraction_status": extraction_status,
            "fragment_count": fragment_count,
        },
    )
    if fragment_count:
        connection.execute(
            tables.document_fragments.insert(),
            [
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "document_id": document_id,
                    "ordinal": ordinal,
                    "locator": f"page:{ordinal}",
                    "text": (f"Scoped extracted evidence {ordinal}. " + "x" * 770),
                }
                for ordinal in range(1, fragment_count + 1)
            ],
        )
    return document_id


def append_event(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    document_id: UUID,
    occurred_at: datetime,
) -> int:
    return int(
        connection.execute(
            tables.events.insert()
            .values(
                tenant_id=tenant_id,
                project_id=project_id,
                event_id=f"document:{uuid4()}:uploaded",
                event_type="DOCUMENT_UPLOADED",
                schema_version=1,
                source="context_builder_test",
                entity="document",
                entity_id=document_id,
                payload={"private_raw_payload": "must-not-cross"},
                timestamp=occurred_at,
            )
            .returning(tables.events.c.id)
        ).scalar_one()
    )


def run_values(
    *,
    tenant_id: UUID,
    project_id: UUID,
    event_id: int,
    occurred_at: datetime,
    agent_key: str = "knowledge_lite",
) -> dict[str, object]:
    return {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "project_id": project_id,
        "agent_key": agent_key,
        "event_row_ids": [event_id],
        "event_count": 1,
        "window_started_at": occurred_at - timedelta(minutes=1),
        "window_ended_at": occurred_at + timedelta(minutes=14),
    }


def test_owner_builder_adds_capped_multimodal_and_pii_free_user_context(
    context_builder_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(context_builder_database_url))
    occurred_at = datetime(2026, 8, 13, 1, tzinfo=UTC)
    try:
        with engine.begin() as connection:
            tenant_id, project_id, owner_id, _ = seed_project(connection, slug="context-a")
            document_id = append_document(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                uploader_id=owner_id,
                classification="internal",
                fragment_count=25,
            )
            event_id = append_event(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                document_id=document_id,
                occurred_at=occurred_at,
            )
            context = RunContextBuilder().build(
                connection,
                run=run_values(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    event_id=event_id,
                    occurred_at=occurred_at,
                ),
                built_at=occurred_at + timedelta(minutes=15),
            )

        assert context.schema_version == 2
        assert context.multimodal.status == "ready"
        assert context.multimodal.requested_document_count == 1
        assert context.multimodal.available_document_count == 1
        assert context.multimodal.total_fragment_count == 25
        assert context.multimodal.shown_fragment_count < 20
        assert context.multimodal.truncated is True
        assert context.multimodal.documents[0].document_id == document_id
        assert all(len(item.excerpt) <= 1_000 for item in context.multimodal.documents[0].fragments)
        assert context.user.perspective_role == "engineer"
        assert [(item.role, item.active_member_count) for item in context.user.project_roles] == [
            ("engineer", 1),
            ("owner", 1),
        ]
        serialized = context.model_dump_json()
        assert "private/" not in serialized
        assert "example.invalid" not in serialized
        assert "Private Owner" not in serialized
        assert "private_raw_payload" not in serialized
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("classification", "extraction_status", "fragment_count"),
    [
        ("confidential", "extracted", 1),
        ("restricted", "extracted", 1),
        ("internal", "ocr_required", 0),
    ],
)
def test_owner_builder_fails_closed_for_unavailable_document_context(
    context_builder_database_url: str,
    classification: str,
    extraction_status: str,
    fragment_count: int,
) -> None:
    engine = create_engine(psycopg_database_url(context_builder_database_url))
    occurred_at = datetime(2026, 8, 13, 2, tzinfo=UTC)
    try:
        with engine.begin() as connection:
            tenant_id, project_id, owner_id, _ = seed_project(
                connection,
                slug=f"unavailable-{classification}-{extraction_status}",
            )
            document_id = append_document(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                uploader_id=owner_id,
                classification=classification,
                extraction_status=extraction_status,
                fragment_count=fragment_count,
            )
            event_id = append_event(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                document_id=document_id,
                occurred_at=occurred_at,
            )
            context = RunContextBuilder().build(
                connection,
                run=run_values(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    event_id=event_id,
                    occurred_at=occurred_at,
                ),
                built_at=occurred_at + timedelta(minutes=15),
            )
        assert context.multimodal.status == "not_available"
        assert context.multimodal.documents == ()
        assert context.multimodal.unavailable_document_count == 1
    finally:
        engine.dispose()


def test_owner_builder_rejects_cross_project_document_reference(
    context_builder_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(context_builder_database_url))
    occurred_at = datetime(2026, 8, 13, 3, tzinfo=UTC)
    try:
        with engine.begin() as connection:
            tenant_a, project_a, owner_a, _ = seed_project(connection, slug="scope-a")
            tenant_b, project_b, owner_b, _ = seed_project(connection, slug="scope-b")
            document_b = append_document(
                connection,
                tenant_id=tenant_b,
                project_id=project_b,
                uploader_id=owner_b,
                classification="internal",
            )
            event_id = append_event(
                connection,
                tenant_id=tenant_a,
                project_id=project_a,
                document_id=document_b,
                occurred_at=occurred_at,
            )
            context = RunContextBuilder().build(
                connection,
                run=run_values(
                    tenant_id=tenant_a,
                    project_id=project_a,
                    event_id=event_id,
                    occurred_at=occurred_at,
                ),
                built_at=occurred_at + timedelta(minutes=15),
            )
        assert context.multimodal.status == "not_available"
        assert context.multimodal.documents == ()
        assert owner_a != owner_b
    finally:
        engine.dispose()


def test_context_v2_migration_round_trip_and_lossy_downgrade_guard(
    context_builder_database_url: str,
) -> None:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    engine = create_engine(psycopg_database_url(context_builder_database_url))
    occurred_at = datetime(2026, 8, 13, 4, tzinfo=UTC)
    try:
        command.downgrade(config, "0024_phase_two_agents")
        columns = {
            column["name"]: column
            for column in inspect(engine).get_columns("agent_runs", schema="cehub_ai")
        }
        assert columns["context_version"]["default"] == "'run-context-v1'::character varying"
        command.upgrade(config, "head")
        with engine.begin() as connection:
            tenant_id, project_id, _, _ = seed_project(connection, slug="v2-guard")
            subscription_id = uuid4()
            connection.execute(
                tables.agent_subscriptions.insert(),
                {
                    "id": subscription_id,
                    "tenant_id": tenant_id,
                    "agent_key": "knowledge_lite",
                },
            )
            run_id = uuid4()
            connection.execute(
                tables.agent_runs.insert(),
                {
                    "id": run_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "subscription_id": subscription_id,
                    "agent_key": "knowledge_lite",
                    "window_started_at": occurred_at,
                    "window_ended_at": occurred_at + timedelta(minutes=15),
                    "first_event_row_id": 1,
                    "last_event_row_id": 1,
                    "event_count": 1,
                    "event_row_ids": [1],
                    "run_context": {"schema_version": 2},
                },
            )
            version = connection.execute(
                text("SELECT context_version FROM cehub_ai.agent_runs WHERE id = :run_id"),
                {"run_id": run_id},
            ).scalar_one()
        assert version == "run-context-v2"
        with pytest.raises(DBAPIError):
            command.downgrade(config, "0024_phase_two_agents")
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
        command.upgrade(config, "head")
        engine.dispose()
