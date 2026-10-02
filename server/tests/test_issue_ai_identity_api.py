"""Independent Issue authorship readback; fixtures are not model-write evidence."""

# ruff: noqa: F811
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db.schema import tables
from tests.test_test_runs_api import (
    Scope,
    bearer_headers,
    client,  # noqa: F401
    isolated_test_run_database,  # noqa: F401
)


def test_ai_creator_survives_human_edit_without_impersonating_reporter(
    client: TestClient, isolated_test_run_database: str
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        project = scope.project()
        principal = scope._insert(
            tables.ai_principals,
            {
                "principal_key": "pdos-agent",
                "display_name": "PDOS Agent",
                "principal_kind": "ai",
                "created_at": datetime.now(UTC),
            },
        )
        issue = scope._insert(
            tables.issues,
            {
                "project_id": project,
                "created_by_ai_principal_id": principal,
                "title": "模拟：独立 AI 创建署名",
                "description": "仅验证署名读取，不代表真实模型建单。",
            },
        )
        headers = bearer_headers(client)
        url = f"/api/projects/{project}/issues/{issue}"
        original = client.get(url, headers=headers)
        assert original.status_code == 200, original.text
        assert original.json()["reported_by_user_id"] is None
        assert original.json()["created_by_ai_principal_id"] == str(principal)
        assert original.json()["ai_writer_name"] == "PDOS Agent"
        changed = client.patch(
            url,
            headers=headers,
            json={
                "description": "负责人已补充实际核对说明。",
                "expected_updated_at": original.json()["updated_at"],
            },
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["reported_by_user_id"] is None
        assert changed.json()["created_by_ai_principal_id"] == str(principal)
        assert changed.json()["ai_writer_name"] == "PDOS Agent"
        with scope.engine.connect() as c:
            audit = (
                c.execute(
                    select(tables.audit_log).where(
                        tables.audit_log.c.entity_id == issue,
                        tables.audit_log.c.action == "issue.update",
                    )
                )
                .mappings()
                .one()
            )
            assert audit["actor_user_id"] == scope.owner_id
            assert audit["before_snapshot"]["created_by_ai_principal_id"] == str(principal)
            assert audit["after_snapshot"]["created_by_ai_principal_id"] == str(principal)
        human = client.post(
            f"/api/projects/{project}/issues", headers=headers, json={"title": "人工新建的问题"}
        )
        assert human.status_code == 201, human.text
        assert human.json()["reported_by_user_id"] == str(scope.owner_id)
        assert human.json()["created_by_ai_principal_id"] is None
        assert human.json()["ai_writer_name"] is None
        listing = client.get(f"/api/projects/{project}/issues", headers=headers)
        assert listing.status_code == 200, listing.text
        assert len(listing.json()["items"]) == 2
        with pytest.raises(IntegrityError), scope.engine.begin() as c:
            c.execute(
                tables.issues.insert().values(
                    id=uuid4(),
                    tenant_id=scope.tenant_id,
                    project_id=project,
                    title="Invalid mixed author",
                    reported_by_user_id=scope.owner_id,
                    created_by_ai_principal_id=principal,
                )
            )
        with (
            pytest.raises(DBAPIError, match="Retain the original Issue creator"),
            scope.engine.begin() as c,
        ):
            c.execute(
                tables.issues.update()
                .where(tables.issues.c.id == issue)
                .values(
                    created_by_ai_principal_id=None,
                    reported_by_user_id=scope.owner_id,
                )
            )
    finally:
        scope.dispose()
