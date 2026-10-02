"""Actual failed-test provenance and stable original-event browsing."""

# ruff: noqa: F811
from io import BytesIO
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import func, select

from app.db.schema import tables
from tests.test_test_runs_api import (
    Scope,
    bearer_headers,
    client,  # noqa: F401
    isolated_test_run_database,  # noqa: F401
    runs_url,
)


def test_existing_issue_reused_and_original_failure_preserved(
    client: TestClient, isolated_test_run_database: str
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        project = scope.project()
        case = scope.test_case(project)
        headers = bearer_headers(client)
        original = client.post(
            runs_url(project, case),
            headers=headers,
            json={"status": "failed", "result_notes": "模拟：耐久测试出现泄漏。"},
        )
        assert original.status_code == 201, original.text
        issue = original.json()["related_issue_id"]
        endpoint = f"/api/projects/{project}/ai-issue-event-sources"
        first = client.get(endpoint, headers=headers)
        assert first.status_code == 200, first.text
        items = first.json()["items"]
        assert len(items) == 1
        item = items[0]
        assert item["source_kind"] == "test_failure"
        assert item["source_status"] == "current", item
        assert item["existing_issue"]["id"] == issue
        assert "模拟：耐久测试出现泄漏。" in str(item["source"])
        assert "audit" not in item["source"] and "run_audit" not in item["source"]
        assert set(item["source"]["human"]) == {"id", "display_name"}
        second = client.post(
            runs_url(project, case),
            headers=headers,
            json={"status": "passed", "result_notes": "模拟：整改后复测通过。"},
        )
        assert second.status_code == 201, second.text
        latest = client.get(endpoint, headers=headers).json()["items"][0]
        assert latest["source_status"] == "changed", latest
        assert latest["source_digest"] != item["source_digest"]
        assert latest["existing_issue"]["id"] == issue
        assert "模拟：耐久测试出现泄漏。" in str(latest["source"])
        existing = scope.issue_row(UUID(issue))
        assert existing is not None and existing["status"] == "open"
        with scope.engine.connect() as c:
            assert c.execute(select(func.count()).select_from(tables.issues)).scalar_one() == 1
            assert (
                c.execute(select(func.count()).select_from(tables.model_invocations)).scalar_one()
                == 0
            )
        assert client.get(endpoint, headers=headers).headers["cache-control"] == "no-store"
        assert client.get(endpoint + "?before=9007199254740991", headers=headers).status_code == 409
        assert (
            client.get(
                f"/api/projects/{uuid4()}/ai-issue-event-sources", headers=headers
            ).status_code
            == 404
        )
    finally:
        scope.dispose()


def test_confirmed_report_failure_uses_its_original_import_batch(
    client: TestClient, isolated_test_run_database: str
) -> None:
    from app.api.ai import get_application_gateway
    from app.main import app
    from app.storage.documents import get_document_object_store
    from tests.test_test_report_import_api import FakeGateway, FakeObjectStore, upload
    from tests.test_test_report_import_api import Scope as ImportScope
    from tests.test_test_report_workbook import form_report

    gateway = FakeGateway()
    store = FakeObjectStore()
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_application_gateway] = lambda: gateway
    app.dependency_overrides[get_document_object_store] = lambda: store
    scope = ImportScope(client, isolated_test_run_database)
    try:
        ids = scope.seed()
        with scope.engine.begin() as c:
            c.execute(
                tables.test_cases.update()
                .where(tables.test_cases.c.id == ids["endurance_id"])
                .values(title="气压精度")
            )
        book = load_workbook(BytesIO(form_report()))
        book["气压精度 "]["D10"] = "不合格"
        content = BytesIO()
        book.save(content)
        headers = bearer_headers(client)
        imported = upload(client, headers, ids["project_id"], ids["plan_id"], content.getvalue())
        assert imported.status_code == 201, imported.text
        batch = imported.json()
        base = f"/api/projects/{ids['project_id']}/npi/test-imports/{batch['id']}"
        preview = client.get(base + "/preview", headers=headers)
        resolved = client.post(
            base + "/resolve-samples",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "expected_digest": preview.json()["digest"],
                "run_ids": batch["created_run_ids"],
                "sample_id": str(ids["sample_id"]),
                "reason": "模拟来源核对：按原报告绑定样机",
            },
        )
        assert resolved.status_code == 200, resolved.text
        confirmed = client.post(base + "/confirm", headers=headers)
        assert confirmed.status_code == 200, confirmed.text
        assert gateway.calls == 0
        sources = client.get(
            f"/api/projects/{ids['project_id']}/ai-issue-event-sources", headers=headers
        )
        assert sources.status_code == 200, sources.text
        items = sources.json()["items"]
        assert len(items) == 1
        assert items[0]["source_status"] == "current", items
        assert items[0]["existing_issue"]["id"] == str(
            scope.case(ids["endurance_id"])["related_issue_id"]
        )
        assert batch["id"] in str(items[0]["source"])
    finally:
        scope.dispose()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_legacy_failure_without_issue_and_original_event_pagination(
    client: TestClient, isolated_test_run_database: str
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        project = scope.project()
        case = scope.test_case(project)
        headers = bearer_headers(client)
        legacy = f"/api/projects/{project}/npi/test-cases/{case}/result"
        for status in ("failed", "passed", "failed"):
            r = client.post(
                legacy,
                headers=headers,
                json={"status": status, "result_notes": "模拟旧入口", "related_issue_id": None},
            )
            assert r.status_code == 200, r.text
        endpoint = f"/api/projects/{project}/ai-issue-event-sources"
        response = client.get(endpoint + "?limit=1", headers=headers)
        assert response.status_code == 200, response.text
        first = response.json()
        assert first["items"][0]["existing_issue"] is None
        assert first["items"][0]["source_status"] == "current"
        assert first["next_before"] is not None
        second = client.get(
            endpoint + f"?limit=1&before={first['next_before']}", headers=headers
        ).json()
        assert second["next_before"] is None
        assert second["items"][0]["event_row_id"] < first["items"][0]["event_row_id"]
        assert second["items"][0]["source_status"] == "changed"
        for query in ("limit=0", "limit=21", "before=0", "before=nope"):
            assert client.get(endpoint + "?" + query, headers=headers).status_code == 422
    finally:
        scope.dispose()
