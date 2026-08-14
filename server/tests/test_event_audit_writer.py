from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine, func, select, text
from sqlalchemy.exc import IntegrityError

from app.auth.roles import Role
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.events.catalog import UnknownEventTypeError
from app.events.writer import (
    AuditDraft,
    EventAuditWriter,
    EventDraft,
    EventSourceMismatchError,
    InvalidEventPayloadError,
    SensitiveAuditDataError,
)

SERVER_ROOT = Path(__file__).resolve().parents[1]


class NoExecuteConnection:
    def execute(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("invalid drafts must fail before touching the database")


def disconnected_writer() -> EventAuditWriter:
    return EventAuditWriter(
        cast(Connection, cast(Any, NoExecuteConnection())),
        tenant_id=uuid4(),
        actor_user_id=uuid4(),
    )


def test_writer_rejects_unknown_mismatched_or_invalid_events_before_io() -> None:
    writer = disconnected_writer()
    entity_id = uuid4()
    audit = AuditDraft(action="project.create", after_snapshot={"name": "PDOS"})

    with pytest.raises(UnknownEventTypeError):
        writer.record(
            EventDraft(
                event_id="unknown:1",
                event_type="NOT_REGISTERED",
                source="project_service",
                entity_id=entity_id,
                payload={},
            ),
            audit,
        )

    with pytest.raises(EventSourceMismatchError):
        writer.record(
            EventDraft(
                event_id="project:1",
                event_type="PROJECT_CREATED",
                source="untrusted_client_value",
                entity_id=entity_id,
                payload={"project_code": "PDOS-001", "project_name": "PDOS"},
            ),
            audit,
        )

    with pytest.raises(InvalidEventPayloadError):
        writer.record(
            EventDraft(
                event_id="project:1",
                event_type="PROJECT_CREATED",
                source="project_service",
                entity_id=entity_id,
                payload={"project_code": "PDOS-001"},
            ),
            audit,
        )


def test_writer_blocks_secret_bearing_payloads_and_audit_snapshots() -> None:
    writer = disconnected_writer()
    event = EventDraft(
        event_id="tenant:1",
        event_type="TENANT_BOOTSTRAPPED",
        source="auth_service",
        entity_id=uuid4(),
        payload={"initial_admin_user_id": "user-1"},
    )

    with pytest.raises(SensitiveAuditDataError):
        writer.record(
            event,
            AuditDraft(
                action="tenant.bootstrap",
                after_snapshot={"password_hash": "must-never-be-recorded"},
            ),
        )


@pytest.fixture
def writer_database_url() -> Iterator[str]:
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


def test_business_event_and_audit_commit_or_rollback_as_one_unit(
    writer_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(writer_database_url))
    tenant_id = uuid4()
    owner_id = uuid4()
    workflow_id = uuid4()
    project_id = uuid4()
    rolled_back_project_id = uuid4()
    event_id = "project:pdos-001:created"

    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": "beepump", "name": "Beehive Technology"},
            )
            connection.execute(
                tables.users.insert(),
                {
                    "id": owner_id,
                    "tenant_id": tenant_id,
                    "username": "owner",
                    "display_name": "Owner",
                    "role": Role.OWNER,
                },
            )
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": workflow_id,
                    "tenant_id": tenant_id,
                    "code": "npd",
                    "name": "NPD",
                    "version": 1,
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": project_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "code": "PDOS-001",
                    "name": "PDOS",
                },
            )
            result = EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=owner_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=event_id,
                    event_type="PROJECT_CREATED",
                    source="project_service",
                    entity_id=project_id,
                    payload={"project_code": "PDOS-001", "project_name": "PDOS"},
                ),
                AuditDraft(
                    action="project.create",
                    after_snapshot={"code": "PDOS-001", "name": "PDOS"},
                ),
            )
        assert result.event_row_id > 0
        assert result.audit_row_id > 0

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                tables.projects.insert(),
                {
                    "id": rolled_back_project_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "code": "PDOS-ROLLBACK",
                    "name": "Must Roll Back",
                },
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=owner_id,
                project_id=rolled_back_project_id,
            ).record(
                EventDraft(
                    event_id=event_id,
                    event_type="PROJECT_CREATED",
                    source="project_service",
                    entity_id=rolled_back_project_id,
                    payload={
                        "project_code": "PDOS-ROLLBACK",
                        "project_name": "Must Roll Back",
                    },
                ),
                AuditDraft(
                    action="project.create",
                    after_snapshot={"code": "PDOS-ROLLBACK"},
                ),
            )

        with engine.connect() as connection:
            assert (
                connection.execute(select(func.count()).select_from(tables.events)).scalar_one()
                == 1
            )
            assert (
                connection.execute(select(func.count()).select_from(tables.audit_log)).scalar_one()
                == 1
            )
            assert (
                connection.execute(
                    select(func.count())
                    .select_from(tables.projects)
                    .where(tables.projects.c.id == rolled_back_project_id)
                ).scalar_one()
                == 0
            )
    finally:
        engine.dispose()
