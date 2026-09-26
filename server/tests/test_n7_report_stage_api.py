"""Synthetic stage journey from actual project tasks to retained report downloads."""

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.auth.roles import Role
from app.db.engine import get_engine
from app.db.schema import tables
from app.exports.definition_documents import MIMES
from tests.stage_plan_fixtures import seed_formal_task
from tests.test_product_engineering_api import SETUP_PAYLOAD, bearer_headers, seed_user
from tests.test_product_engineering_api import client as client
from tests.test_product_engineering_api import (
    isolated_product_database as isolated_product_database,
)
from tests.test_projects_api import approved_case, create_project


def post(
    client: TestClient, url: str, headers: dict[str, str], body: dict[str, Any]
) -> dict[str, Any]:
    response = client.post(url, headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return cast(dict[str, Any], response.json())


def test_synthetic_weekly_report_retains_bytes_and_rechecks_download_access(
    client: TestClient, isolated_product_database: str
) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD)
    assert setup.status_code == 201, setup.text
    tenant, owner = UUID(setup.json()["tenant"]["id"]), UUID(setup.json()["user"]["id"])
    manager = bearer_headers(client)
    case = approved_case(client, manager, suffix="N7-REPORT-SYNTHETIC")
    project_response = create_project(client, manager, case["id"], code="N7-REPORT-SYNTHETIC")
    assert project_response.status_code == 201, project_response.text
    project = UUID(project_response.json()["id"])
    reader_id = seed_user(
        isolated_product_database,
        tenant_id=tenant,
        project_id=project,
        owner_id=owner,
        username="synthetic-report-reader",
        role=Role.ENGINEER,
    )
    reader = bearer_headers(client, username="synthetic-report-reader")
    with get_engine().begin() as connection:
        connection.execute(
            tables.projects.update().where(tables.projects.c.id == project).values(status="active")
        )
        task, _ = seed_formal_task(connection, tenant, project, owner, reader_id)

    base = f"/api/projects/{project}/reports"
    day = datetime.now(UTC).date().isoformat()
    scope = {"kind": "weekly", "period_start": day, "period_end": day}
    generated: list[tuple[dict[str, Any], dict[str, Any], bytes]] = []
    for format, mime in MIMES.items():
        body = {"scope": scope, "format": format, "reason": "Synthetic stage test; no real export"}
        preview = post(client, base + "/preview", manager, body)
        assert str(task) in {row["id"] for row in preview["source"]["current_work"]["tasks"]}
        assert preview["source"]["warnings"]
        command = {**body, "request_id": str(uuid4()), "expected_digest": preview["digest"]}
        saved = post(client, base + "/save", manager, command)
        assert post(client, base + "/save", manager, command) == saved
        download = client.get(base + f"/{saved['id']}/download", headers=reader)
        assert download.status_code == 200, download.text
        assert download.headers["cache-control"] == "no-store"
        assert download.headers["content-type"].startswith(mime)
        assert len(download.content) == saved["byte_size"]
        assert sha256(download.content).hexdigest() == saved["content_digest"]
        assert download.content.startswith(b"%PDF" if format == "pdf" else b"PK")
        generated.append((command, saved, download.content))

    history = post(client, base + "/history", manager, {"kind": "weekly"})
    assert {item["id"] for item in history["items"]} == {item[1]["id"] for item in generated}
    with get_engine().connect() as connection:
        assert (
            connection.scalar(
                select(func.count())
                .select_from(tables.events)
                .where(
                    tables.events.c.tenant_id == tenant,
                    tables.events.c.project_id == project,
                    tables.events.c.event_type == "PROJECT_REPORT_EXPORTED",
                )
            )
            == 4
        )
        assert (
            connection.scalar(
                select(func.count())
                .select_from(tables.audit_log)
                .where(
                    tables.audit_log.c.tenant_id == tenant,
                    tables.audit_log.c.project_id == project,
                    tables.audit_log.c.action == "project_report.exported",
                )
            )
            == 4
        )

    first_command, first, original_bytes = generated[0]
    with get_engine().begin() as connection:
        connection.execute(
            tables.tasks.update()
            .where(tables.tasks.c.id == task)
            .values(title="Synthetic source changed after the retained report")
        )
    stale = client.post(
        base + "/save",
        headers=manager,
        json={**first_command, "request_id": str(uuid4())},
    )
    assert stale.status_code == 409, stale.text
    assert post(client, base + "/save", manager, first_command) == first
    url = base + f"/{first['id']}/download"
    assert client.get(url, headers=reader).content == original_bytes

    with pytest.raises(DBAPIError), get_engine().begin() as connection:
        connection.execute(
            tables.project_report_exports.update()
            .where(tables.project_report_exports.c.id == UUID(first["id"]))
            .values(content=b"replacement")
        )
    with get_engine().begin() as connection:
        connection.execute(
            tables.project_members.delete().where(
                tables.project_members.c.project_id == project,
                tables.project_members.c.user_id == reader_id,
            )
        )
    assert client.get(url, headers=reader).status_code == 403
    assert client.get(url, headers=manager).content == original_bytes
