"""Excel test-report AI import pipeline tests (vNext V1-B10, D36)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from importlib import import_module
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, NoReturn, cast
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from openpyxl import Workbook
from psycopg import Error as PsycopgError
from pydantic import BaseModel
from sqlalchemy import Connection, RowMapping, Table, create_engine, select, text
from sqlalchemy.exc import IntegrityError

from app.ai import application_gateway
from app.ai.budget_adoption import METER_DIGEST_KEY, METER_PATH_KEY, MODE_KEY, PROFILE_KEY
from app.ai.call_identity import ModelCallSlot, model_call_id
from app.ai.context_projection import project_gateway_context
from app.ai.gateway import GatewayInvocation, GatewayResult, StructuredModelGateway
from app.api.ai import get_application_gateway
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.documents import DocumentRecord
from app.domain.test_report_import import (
    ExcelImportMapping,
    ImportBatchResult,
    ImportRevision,
    MetricColumn,
)
from app.main import app
from app.settings import get_settings
from app.storage.documents import get_document_object_store
from tests.db_cleanup import clear_test_tenants
from tests.migration_fixtures import rollback_migration_operations
from tests.test_input_metering import publication
from tests.test_model_budget_controller import response as provider_response
from tests.test_model_gateway import qualification
from tests.test_test_report_workbook import form_report
from tests.test_test_templates import pilot_selection

SERVER_ROOT = Path(__file__).resolve().parents[1]
TEST_JWT_SECRET = "test-only-jwt-secret-that-is-at-least-32-bytes"
PASSWORD = "correct horse battery staple"
SETUP_PAYLOAD = {
    "tenant_slug": "beepump",
    "tenant_name": "Beehive Technology",
    "username": "owner",
    "password": PASSWORD,
    "display_name": "Initial Owner",
}

MAPPING = ExcelImportMapping(
    case_title_column="用例名称",
    sample_serial_column="样机SN",
    result_column="测试结果",
    notes_column="备注",
    metric_columns=[MetricColumn(column="泄漏率(sccm)", name="leak_rate", unit="sccm")],
    pcb_version_column="PCB版本",
    fw_version_column="固件版本",
    pass_values=["PASS"],
    fail_values=["FAIL"],
    confidence=0.86,
    unmapped_headers=[],
)


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, *, object_key: str, content: bytes, media_type: str, sha256: str) -> None:
        del media_type, sha256
        self.objects[object_key] = content

    def delete(self, *, object_key: str) -> None:
        self.objects.pop(object_key, None)


class FakeGateway:
    def __init__(self) -> None:
        self.calls = 0
        self.contexts: list[dict[str, Any]] = []

    def invoke_structured[OutputT: BaseModel](
        self, invocation: GatewayInvocation, output_type: type[OutputT]
    ) -> GatewayResult[OutputT]:
        assert invocation.run_id is not None
        assert invocation.model_call_id == model_call_id(
            invocation.run_id, ModelCallSlot.REPORT_MAPPING
        )
        # The real gateway sends only the projected context; N7-02 found it had been empty.
        projection = project_gateway_context(invocation.context)
        assert projection.removed_paths == (), projection.removed_paths
        self.contexts.append(dict(projection.payload))
        self.calls += 1
        return GatewayResult(
            status="succeeded",
            output=output_type.model_validate(MAPPING.model_dump()),
            error_code=None,
            structured_attempts=1,
            removed_context_paths=(),
            invocation_id=uuid4(),
        )


def build_report(rows: list[tuple[Any, ...]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None  # a fresh workbook always has one
    sheet.append(["用例名称", "样机SN", "测试结果", "泄漏率(sccm)", "备注", "PCB版本", "固件版本"])
    for row in rows:
        sheet.append(list(row))
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def record_execution_dates(
    client: TestClient, headers: dict[str, str], project_id: UUID, batch_id: object
) -> None:
    """Supply the synthetic execution fact through the human amendment API."""
    url = f"/api/projects/{project_id}/npi/test-imports/{batch_id}"
    preview = client.get(f"{url}/preview", headers=headers)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    amended = client.post(
        f"{url}/execution-times",
        headers=headers,
        json={
            "expected_digest": body["digest"],
            "items": [
                {
                    "run_id": item["run"]["id"],
                    "executed_date": "2026-08-01",
                    "reason": "Synthetic fixture execution log: 2026-08-01",
                }
                for item in body["items"]
            ],
        },
    )
    assert amended.status_code == 200, amended.text


@pytest.fixture(autouse=True)
def isolated_import_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    test_url = configured_test_database_url()
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("JWT_ISSUER", "pdos-test")
    monkeypatch.setenv("JWT_AUDIENCE", "pdos-test-client")
    get_settings.cache_clear()
    get_engine.cache_clear()
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            clear_test_tenants(connection)
        yield test_url
    finally:
        with engine.begin() as connection:
            clear_test_tenants(connection)
        engine.dispose()
        get_engine().dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()
        app.dependency_overrides.clear()


@pytest.fixture
def api_context() -> Iterator[tuple[TestClient, FakeGateway]]:
    gateway = FakeGateway()
    store = FakeObjectStore()
    app.dependency_overrides[get_document_object_store] = lambda: store
    app.dependency_overrides[get_application_gateway] = lambda: gateway
    with TestClient(app) as client:
        yield client, gateway


def bearer_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": "owner", "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class Scope:
    def __init__(self, client: TestClient, database_url: str) -> None:
        setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
        self.tenant_id = UUID(setup["tenant"]["id"])
        self.owner_id = UUID(setup["user"]["id"])
        self.engine = create_engine(psycopg_database_url(database_url))

    def dispose(self) -> None:
        self.engine.dispose()

    def _insert(self, table: Table, values: dict[str, Any]) -> UUID:
        row_id: UUID = values.setdefault("id", uuid4())
        values.setdefault("tenant_id", self.tenant_id)
        with self.engine.begin() as connection:
            connection.execute(table.insert(), values)
        return row_id

    def seed(self) -> dict[str, UUID]:
        workflow_id = self._insert(tables.workflows, {"code": "WF-IMP", "name": "Workflow"})
        stage_id = self._insert(
            tables.stages,
            {"workflow_id": workflow_id, "code": "evt", "name": "EVT", "sequence": 1},
        )
        project_id = self._insert(
            tables.projects,
            {
                "workflow_id": workflow_id,
                "owner_user_id": self.owner_id,
                "code": "PRJ-IMP",
                "name": "Import project",
                "status": "active",
            },
        )
        self._insert(
            tables.project_members,
            {"project_id": project_id, "user_id": self.owner_id, "added_by_user_id": self.owner_id},
        )
        plan_id = self._insert(
            tables.test_plans,
            {
                "project_id": project_id,
                "workflow_id": workflow_id,
                "stage_id": stage_id,
                "created_by_user_id": self.owner_id,
                "phase": "evt",
                "title": "EVT plan",
                "sample_size": 3,
                "status": "active",
            },
        )
        endurance_id = self._insert(
            tables.test_cases,
            {
                "project_id": project_id,
                "plan_id": plan_id,
                "created_by_user_id": self.owner_id,
                "title": "Endurance 500h",
                "category": "reliability",
                "acceptance_criteria": "No leak",
                "severity": "major",
                "status": "planned",
            },
        )
        leak_id = self._insert(
            tables.test_cases,
            {
                "project_id": project_id,
                "plan_id": plan_id,
                "created_by_user_id": self.owner_id,
                "title": "Leak test",
                "category": "performance",
                "acceptance_criteria": "< 0.1 sccm",
                "severity": "critical",
                "status": "planned",
            },
        )
        bom_id = self._insert(
            tables.development_boms,
            {
                "project_id": project_id,
                "created_by_user_id": self.owner_id,
                "bom_type": "prototype",
                "code": "BOM-P1",
                "name": "Prototype BOM",
                "version": 1,
            },
        )
        build_id = self._insert(
            tables.build_batches,
            {
                "project_id": project_id,
                "workflow_id": workflow_id,
                "stage_id": stage_id,
                "created_by_user_id": self.owner_id,
                "phase": "evt",
                "code": "BUILD-1",
                "planned_quantity": 5,
                "status": "planned",
            },
        )
        sample_id = self._insert(
            tables.samples,
            {
                "project_id": project_id,
                "build_batch_id": build_id,
                "prototype_bom_id": bom_id,
                "created_by_user_id": self.owner_id,
                "serial_number": "SN-001",
                "status": "testing",
            },
        )
        return {
            "project_id": project_id,
            "plan_id": plan_id,
            "endurance_id": endurance_id,
            "leak_id": leak_id,
            "sample_id": sample_id,
        }

    def runs(self) -> list[RowMapping]:
        with self.engine.connect() as connection:
            return list(
                connection.execute(select(tables.test_runs).order_by(tables.test_runs.c.created_at))
                .mappings()
                .all()
            )

    def case(self, case_id: UUID) -> RowMapping:
        with self.engine.connect() as connection:
            return (
                connection.execute(
                    select(tables.test_cases).where(tables.test_cases.c.id == case_id)
                )
                .mappings()
                .one()
            )

    def mapping_versions(self) -> list[RowMapping]:
        with self.engine.connect() as connection:
            return list(connection.execute(select(tables.import_mapping_versions)).mappings().all())


def upload(
    client: TestClient, headers: dict[str, str], project_id: UUID, plan_id: UUID, content: bytes
) -> httpx2.Response:
    return client.post(
        f"/api/projects/{project_id}/npi/test-imports",
        headers=headers,
        data={"plan_id": str(plan_id)},
        files={
            "file": (
                "report.xlsx",
                content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )


def test_model_mapped_import_creates_draft_runs_without_touching_cases(
    api_context: tuple[TestClient, FakeGateway], isolated_import_database: str
) -> None:
    client, gateway = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        headers = bearer_headers(client)
        content = build_report(
            [
                ("Endurance 500h", "SN-001", "PASS", 0.05, "ok"),
                ("Leak test", "SN-001", "FAIL", 0.4, "leak at seam"),
                ("Ghost case", "SN-002", "PASS", 0.02, None),
                ("Endurance 500h", "SN-001", "MAYBE", 0.06, None),
            ]
        )

        response = upload(client, headers, ids["project_id"], ids["plan_id"], content)
        assert response.status_code == 201, response.text
        body = response.json()
        assert gateway.calls == 1
        sent = gateway.contexts[0]["report_mapping"]
        assert [item["column"] for item in sent["headers"]] == [
            "用例名称",
            "样机SN",
            "测试结果",
            "泄漏率(sccm)",
            "备注",
            "PCB版本",
            "固件版本",
        ]
        assert sent["total_rows"] == 4 and len(sent["sample_rows"]) == 4
        assert sent["sample_rows"][1]["row"] == 3
        assert {"column": "测试结果", "value": "FAIL"} in sent["sample_rows"][1]["cells"]
        assert {"column": "备注", "value": "leak at seam"} in sent["sample_rows"][1]["cells"]
        assert body["mapping_source"] == "model"
        assert body["confidence"] == pytest.approx(0.86)
        assert len(body["created_run_ids"]) == 2
        reasons = {item["reason"] for item in body["skipped_rows"]}
        assert reasons == {"unknown_test_case", "unknown_result_value"}

        runs = scope.runs()
        assert all(run["draft_state"] == "draft" for run in runs)
        assert {run["status"] for run in runs} == {"passed", "failed"}
        assert all(run["sample_id"] == ids["sample_id"] for run in runs)
        assert runs[0]["metrics"][0]["name"] == "leak_rate"
        assert scope.case(ids["endurance_id"])["status"] == "planned"
        assert scope.case(ids["leak_id"])["status"] == "planned"
    finally:
        scope.dispose()


def test_confirm_promotes_runs_syncs_cases_and_persists_mapping(
    api_context: tuple[TestClient, FakeGateway], isolated_import_database: str
) -> None:
    client, gateway = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        headers = bearer_headers(client)
        content = build_report(
            [
                ("Endurance 500h", "SN-001", "PASS", 0.05, None, "V2.1", "FW-1.4.0"),
                ("Leak test", "SN-001", "FAIL", 0.4, "leak", "V2.1", "FW-1.4.0"),
            ]
        )
        batch = upload(client, headers, ids["project_id"], ids["plan_id"], content).json()

        record_execution_dates(client, headers, ids["project_id"], batch["id"])
        confirmed = client.post(
            f"/api/projects/{ids['project_id']}/npi/test-imports/{batch['id']}/confirm",
            headers=headers,
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "confirmed"

        runs = scope.runs()
        assert all(run["draft_state"] == "confirmed" for run in runs)
        assert scope.case(ids["endurance_id"])["status"] == "passed"
        leak_case = scope.case(ids["leak_id"])
        assert leak_case["status"] == "failed"
        assert leak_case["related_issue_id"] is not None

        versions = scope.mapping_versions()
        assert len(versions) == 1
        assert versions[0]["version"] == 1

        with scope.engine.connect() as connection:
            # Report evidence stays attached to each run; confirming results
            # does not silently publish firmware or replace the sample setup.
            assert connection.execute(select(tables.sample_build_configurations)).first() is None
            assert connection.execute(select(tables.fw_releases)).first() is None
        for run in runs:
            assert run["conditions"]["report_configuration"]["pcb_version"] == "V2.1"
            assert run["conditions"]["report_configuration"]["fw_version"] == "FW-1.4.0"
            assert run["sample_configuration_revision_id"] is not None

        again = client.post(
            f"/api/projects/{ids['project_id']}/npi/test-imports/{batch['id']}/confirm",
            headers=headers,
        )
        assert again.status_code == 200
        assert again.json()["reused_existing"] is True

        second = upload(
            client,
            headers,
            ids["project_id"],
            ids["plan_id"],
            build_report([("Endurance 500h", "SN-001", "PASS", 0.04, None)]),
        )
        assert second.status_code == 201
        assert second.json()["mapping_source"] == "mapping"
        assert gateway.calls == 1
        latest = scope.runs()[-1]
        assert latest["run_number"] == 2
        assert latest["draft_state"] == "draft"
    finally:
        scope.dispose()


def test_form_import_uses_plan_and_preserves_source_without_model_or_automatic_confirmation(
    api_context: tuple[TestClient, FakeGateway], isolated_import_database: str
) -> None:
    client, gateway = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        with scope.engine.begin() as connection:
            connection.execute(
                tables.test_cases.update()
                .where(tables.test_cases.c.id == ids["endurance_id"])
                .values(title="气压精度")
            )
        headers = bearer_headers(client)
        response = upload(client, headers, ids["project_id"], ids["plan_id"], form_report())
        assert response.status_code == 201, response.text
        batch = response.json()
        assert gateway.calls == 0
        assert batch["mapping_source"] == "mapping"
        assert len(batch["created_run_ids"]) == 1
        retained = [row for row in batch["skipped_rows"] if row["reason"] == "non_decisive_result"]
        assert {row["value"] for row in retained} == {"参考", "不适用"}
        run = scope.runs()[0]
        assert run["sample_id"] is None
        assert run["draft_state"] == "draft"
        assert run["executed_at"].date().isoformat() == "2025-11-05"
        assert run["started_at"] is None
        assert run["conditions"]["report_source"]["sheet"] == "气压精度 "
        assert run["conditions"]["report_source"]["granularity"] == "worksheet_summary"
        assert scope.case(ids["endurance_id"])["status"] == "planned"
        preview = client.get(
            f"/api/projects/{ids['project_id']}/npi/test-imports/{batch['id']}/preview",
            headers=headers,
        )
        assert preview.status_code == 200
        resolved = client.post(
            f"/api/projects/{ids['project_id']}/npi/test-imports/{batch['id']}/resolve-samples",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "expected_digest": preview.json()["digest"],
                "run_ids": batch["created_run_ids"],
                "sample_id": str(ids["sample_id"]),
                "reason": "Synthetic fixture report belongs to SN-001",
            },
        )
        assert resolved.status_code == 200, resolved.text
        result = client.post(
            f"/api/projects/{ids['project_id']}/npi/test-imports/{batch['id']}/confirm",
            headers=headers,
        )
        assert result.status_code == 200, result.text
        assert scope.case(ids["endurance_id"])["status"] == "passed"
        assert scope.mapping_versions() == []  # deterministic adapter is not an AI mapping
    finally:
        scope.dispose()


def test_waived_plan_item_cannot_be_overwritten_by_import_or_late_confirmation(
    api_context: tuple[TestClient, FakeGateway], isolated_import_database: str
) -> None:
    client, _ = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        headers = bearer_headers(client)
        report = build_report([("Leak test", "SN-001", "FAIL", 0.4, "leak")])
        first = upload(client, headers, ids["project_id"], ids["plan_id"], report)
        assert first.status_code == 201, first.text
        record_execution_dates(client, headers, ids["project_id"], first.json()["id"])
        with scope.engine.begin() as connection:
            connection.execute(
                tables.test_cases.update()
                .where(tables.test_cases.c.id == ids["leak_id"])
                .values(
                    status="waived",
                    result_notes="This project has no such feature",
                    executed_at=datetime.now(UTC),
                    executed_by_user_id=scope.owner_id,
                )
            )
        rejected = client.post(
            f"/api/projects/{ids['project_id']}/npi/test-imports/{first.json()['id']}/confirm",
            headers=headers,
        )
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["detail"]["code"] == "IMPORT_CONFIRMATION_BLOCKED"
        assert "已豁免" in rejected.json()["detail"]["message"]
        assert scope.runs()[0]["draft_state"] == "draft"  # transaction rolled back
        assert scope.case(ids["leak_id"])["related_issue_id"] is None
        second = upload(client, headers, ids["project_id"], ids["plan_id"], report)
        assert second.status_code == 200, second.text
        assert second.json()["reused_existing"] is True
        assert second.json()["id"] == first.json()["id"]
        assert len(second.json()["created_run_ids"]) == 1
        empty = client.post(
            f"/api/projects/{ids['project_id']}/npi/test-imports/{second.json()['id']}/confirm",
            headers=headers,
        )
        assert empty.status_code == 409
        assert empty.json()["detail"]["code"] == "IMPORT_CONFIRMATION_BLOCKED"
        assert "已豁免" in empty.json()["detail"]["message"]
        assert scope.case(ids["leak_id"])["status"] == "waived"
    finally:
        scope.dispose()


def test_manual_configuration_upsert_and_comparison_list(
    api_context: tuple[TestClient, FakeGateway], isolated_import_database: str
) -> None:
    client, _ = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        headers = bearer_headers(client)

        upserted = client.put(
            f"/api/projects/{ids['project_id']}/npi/samples/{ids['sample_id']}/build-configuration",
            headers=headers,
            json={
                "pcb_version": "V2.2",
                "structure_version": "S1.0",
                "fw_version": "FW-1.5.0",
                "key_component_suppliers": {"motor": "Supplier A"},
                "build_date": "2026-08-20",
            },
        )
        assert upserted.status_code == 200
        body = upserted.json()
        assert body["source"] == "manual"
        assert body["draft_state"] == "confirmed"
        assert body["fw_version"] == "FW-1.5.0"
        assert body["sample_serial"] == "SN-001"

        listed = client.get(
            f"/api/projects/{ids['project_id']}/npi/sample-configurations", headers=headers
        )
        assert listed.status_code == 200
        assert [item["sample_serial"] for item in listed.json()["items"]] == ["SN-001"]

        missing = client.put(
            f"/api/projects/{ids['project_id']}/npi/samples/{uuid4()}/build-configuration",
            headers=headers,
            json={"pcb_version": "V1"},
        )
        assert missing.status_code == 404
    finally:
        scope.dispose()


def test_template_plan_creates_clean_cases_and_preserves_exclusion_and_audit(
    api_context: tuple[TestClient, FakeGateway],
    isolated_import_database: str,
) -> None:
    client, gateway = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        headers = bearer_headers(client)
        root = f"/api/projects/{ids['project_id']}/npi"
        options = client.get(f"{root}/test-templates", headers=headers)
        assert options.status_code == 200
        selection = pilot_selection().model_dump()
        payload = {
            "stage_id": options.json()["stages"][0]["id"],
            "phase": "evt",
            "title": "D14-04 测试计划",
            "sample_size": 1,
            "template": selection,
        }
        created = client.post(f"{root}/test-plans", headers=headers, json=payload)
        assert created.status_code == 201, created.text
        plan = created.json()
        snapshot = plan["template_snapshot"]
        assert snapshot["confirmed_by_user_id"] == str(scope.owner_id)
        response = client.get(root, headers=headers).json()
        current = next(item for item in response["test_plans"] if item["id"] == plan["id"])
        assert current["coverage"]["required"] == 29
        assert current["coverage"]["not_applicable"] == 1
        assert current["coverage"]["covered"] == 0
        cases = [item for item in response["test_cases"] if item["plan_id"] == plan["id"]]
        assert len(cases) == 29 and all(item["status"] == "planned" for item in cases)
        assert all(item["executed_at"] is None for item in cases)
        assert len({item["template_item_key"] for item in cases}) == 29
        assert not any(item["title"] == "手电筒功能" for item in cases)
        assert scope.runs() == [] and gateway.calls == 0
        light = upload(
            client,
            headers,
            ids["project_id"],
            UUID(plan["id"]),
            build_report([("手电筒功能", "SN-001", "PASS", None, None)]),
        )
        assert light.status_code == 201, light.text
        assert light.json()["created_run_ids"] == []
        assert light.json()["skipped_rows"][0]["reason"] == "template_not_applicable"
        assert "不带照明灯" in light.json()["skipped_rows"][0]["exclusion_reason"]
        assert (
            next(item for item in response["test_plans"] if item["id"] == str(ids["plan_id"]))[
                "coverage"
            ]["coverage_percent"]
            is None
        )
        repeated = client.post(
            f"{root}/test-plans/{plan['id']}/template", headers=headers, json=selection
        )
        assert repeated.status_code == 409
        wrong_type = client.post(
            f"{root}/test-plans",
            headers=headers,
            json={**payload, "template": {**selection, "product_type": "锂电汽车泵"}},
        )
        assert wrong_type.status_code == 409
        outside = client.post(
            f"/api/projects/{uuid4()}/npi/test-plans/{plan['id']}/template",
            headers=headers,
            json=selection,
        )
        assert outside.status_code in {403, 404}
        with scope.engine.connect() as connection:
            audit = (
                connection.execute(
                    select(tables.audit_log).where(
                        tables.audit_log.c.action == "npi.test_plan.created"
                    )
                )
                .mappings()
                .all()
            )
            assert any(
                row["after_snapshot"].get("template_snapshot", {}).get("digest")
                == snapshot["digest"]
                for row in audit
            )
        with (
            rollback_migration_operations(scope.engine),
            pytest.raises(RuntimeError, match="test template snapshots or case bindings"),
        ):
            import_module("migrations.versions.0057_test_template_snapshot").downgrade()
    finally:
        scope.dispose()


def test_empty_plan_can_bind_once_and_foreign_plan_cannot_bind(
    api_context: tuple[TestClient, FakeGateway],
    isolated_import_database: str,
) -> None:
    client, _ = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        headers = bearer_headers(client)
        root = f"/api/projects/{ids['project_id']}/npi"
        stages = client.get(f"{root}/test-templates", headers=headers).json()["stages"]
        created = client.post(
            f"{root}/test-plans",
            headers=headers,
            json={
                "stage_id": stages[0]["id"],
                "phase": "evt",
                "title": "Empty plan",
                "sample_size": 1,
            },
        )
        assert created.status_code == 201, created.text
        plan_id = created.json()["id"]
        assert (
            client.post(
                f"{root}/test-plans/{ids['plan_id']}/template",
                headers=headers,
                json=pilot_selection().model_dump(),
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"{root}/test-plans/{uuid4()}/template",
                headers=headers,
                json=pilot_selection().model_dump(),
            ).status_code
            == 404
        )
        bound = client.post(
            f"{root}/test-plans/{plan_id}/template",
            headers=headers,
            json=pilot_selection().model_dump(),
        )
        assert bound.status_code == 200, bound.text
        assert len(scope.runs()) == 0
    finally:
        scope.dispose()


@pytest.mark.parametrize("confirm_first", [False, True])
def test_same_content_reuses_batch_even_when_renamed(
    api_context: tuple[TestClient, FakeGateway], isolated_import_database: str, confirm_first: bool
) -> None:
    client, gateway = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        headers = bearer_headers(client)
        content = build_report([("Endurance 500h", "SN-001", "PASS", 0.05, "ok")])
        first = upload(client, headers, ids["project_id"], ids["plan_id"], content).json()
        assert first["reused_existing"] is False
        if confirm_first:
            record_execution_dates(client, headers, ids["project_id"], first["id"])
            assert (
                client.post(
                    f"/api/projects/{ids['project_id']}/npi/test-imports/{first['id']}/confirm",
                    headers=headers,
                ).status_code
                == 200
            )
        with scope.engine.connect() as connection:
            watched = [
                tables.documents,
                tables.test_report_import_batches,
                tables.test_runs,
                tables.events,
                tables.audit_log,
                tables.test_cases,
            ]
            before = [
                list(connection.execute(select(t).order_by(t.c.id)).mappings()) for t in watched
            ]
        store = app.dependency_overrides[get_document_object_store]()
        stored = dict(store.objects)
        renamed = client.post(
            f"/api/projects/{ids['project_id']}/npi/test-imports",
            headers=headers,
            data={"plan_id": str(ids["plan_id"])},
            files={
                "file": (
                    "renamed.xlsx",
                    content,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert renamed.status_code == 200, renamed.text
        body = renamed.json()
        assert body["reused_existing"] is True
        assert body["id"] == first["id"] and body["document_id"] == first["document_id"]
        assert body["created_run_ids"] == first["created_run_ids"]
        assert body["status"] == ("confirmed" if confirm_first else "parsed")
        assert gateway.calls == 1 and store.objects == stored
        with scope.engine.connect() as connection:
            assert [
                list(connection.execute(select(t).order_by(t.c.id)).mappings()) for t in watched
            ] == before
    finally:
        scope.dispose()


def test_duplicate_scope_is_plan_and_content_and_empty_batch_is_reused(
    api_context: tuple[TestClient, FakeGateway], isolated_import_database: str
) -> None:
    client, _ = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        headers = bearer_headers(client)
        content = build_report([("Unknown case", "SN-001", "PASS", 0.05, "ok")])
        first = upload(client, headers, ids["project_id"], ids["plan_id"], content).json()
        again = upload(client, headers, ids["project_id"], ids["plan_id"], content)
        assert again.status_code == 200 and again.json()["id"] == first["id"]
        assert again.json()["created_run_ids"] == []
        changed = upload(
            client,
            headers,
            ids["project_id"],
            ids["plan_id"],
            build_report([("Endurance 500h", "SN-001", "PASS", 0.06, "changed")]),
        )
        assert changed.status_code == 201 and changed.json()["reused_existing"] is False
        with scope.engine.begin() as connection:
            plan = dict(
                connection.execute(
                    select(tables.test_plans).where(tables.test_plans.c.id == ids["plan_id"])
                )
                .mappings()
                .one()
            )
            plan["id"] = uuid4()
            connection.execute(tables.test_plans.insert().values(**plan))
        other = upload(client, headers, ids["project_id"], plan["id"], content)
        assert other.status_code == 201 and other.json()["id"] != first["id"]
        # A plan in another project must not disclose or reuse this project's batch.
        wrong_project = upload(client, headers, uuid4(), ids["plan_id"], content)
        assert wrong_project.status_code == 403
    finally:
        scope.dispose()


def test_concurrent_identical_uploads_share_one_batch(
    api_context: tuple[TestClient, FakeGateway], isolated_import_database: str
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.domain.test_report_import import TestReportImportService

    client, gateway = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        content = build_report([("Endurance 500h", "SN-001", "PASS", 0.05, "ok")])
        store = FakeObjectStore()
        service = TestReportImportService(
            scope.engine, object_store=store, gateway=cast(StructuredModelGateway, gateway)
        )
        barrier = Barrier(2)

        def start() -> Any:
            barrier.wait(timeout=10)
            return service.start_import(
                tenant_id=scope.tenant_id,
                actor_user_id=scope.owner_id,
                project_id=ids["project_id"],
                plan_id=ids["plan_id"],
                filename="concurrent.xlsx",
                content=content,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(start) for _ in range(2)]
            results = [future.result(timeout=30) for future in futures]
        assert results[0].id == results[1].id
        assert sorted(r.reused_existing for r in results) == [False, True]
        assert len(store.objects) == len(scope.runs()) == gateway.calls == 1
    finally:
        scope.dispose()


def test_failed_parse_rolls_back_document_and_allows_retry(
    api_context: tuple[TestClient, FakeGateway],
    isolated_import_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.domain.test_report_import as importer

    client, _ = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        headers = bearer_headers(client)
        content = build_report([("Endurance 500h", "SN-001", "PASS", 0.05, "ok")])
        from app.domain.test_report_workbook import parse_workbook

        original = parse_workbook

        def fail(_: bytes) -> Any:
            raise importer.ImportError_(
                "IMPORT_INVALID_WORKBOOK", "forced failure after file staging"
            )

        monkeypatch.setattr(importer, "parse_workbook", fail)
        assert (
            upload(client, headers, ids["project_id"], ids["plan_id"], content).status_code == 422
        )
        store = app.dependency_overrides[get_document_object_store]()
        assert store.objects == {}
        with scope.engine.connect() as connection:
            assert list(connection.execute(select(tables.documents))) == []
            assert list(connection.execute(select(tables.test_report_import_batches))) == []
        monkeypatch.setattr(importer, "parse_workbook", original)
        retried = upload(client, headers, ids["project_id"], ids["plan_id"], content)
        assert retried.status_code == 201 and not retried.json()["reused_existing"]
    finally:
        scope.dispose()


@pytest.mark.parametrize("revoke", [False, True])
def test_model_mapping_releases_project_write_lock_and_rechecks_actor(
    api_context: tuple[TestClient, FakeGateway],
    isolated_import_database: str,
    monkeypatch: pytest.MonkeyPatch,
    revoke: bool,
) -> None:
    client, gateway = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        headers = bearer_headers(client)
        original = gateway.invoke_structured

        def check_locks[OutputT: BaseModel](
            invocation: GatewayInvocation, output_type: type[OutputT]
        ) -> GatewayResult[OutputT]:
            with scope.engine.begin() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '500ms'"))
                # A second real connection must be able to acquire the project
                # lock while model I/O is in progress (including trace FK checks).
                connection.execute(
                    select(tables.projects.c.id)
                    .where(tables.projects.c.id == ids["project_id"])
                    .with_for_update(nowait=True)
                ).scalar_one()
                connection.execute(
                    tables.model_invocations.insert().values(
                        id=uuid4(),
                        tenant_id=scope.tenant_id,
                        project_id=ids["project_id"],
                        agent_key=invocation.agent_key,
                        agent_tier=invocation.agent_tier.value,
                        prompt_version=invocation.prompt_version,
                        provider="minimax",
                        model="test-only",
                        protocol="openai-compatible",
                        status="succeeded",
                        structured_attempts=1,
                    )
                )
                if revoke:
                    connection.execute(
                        tables.users.update()
                        .where(tables.users.c.id == scope.owner_id)
                        .values(is_active=False)
                    )
            return original(invocation, output_type)

        monkeypatch.setattr(gateway, "invoke_structured", check_locks)
        content = build_report([("Endurance 500h", "SN-001", "PASS", 0.05, "ok")])
        response = upload(client, headers, ids["project_id"], ids["plan_id"], content)
        assert response.status_code == (403 if revoke else 201), response.text
        assert gateway.calls == 1
        if revoke:
            assert response.json()["detail"]["code"] == "IMPORT_ACCESS_DENIED"
            with scope.engine.connect() as connection:
                assert connection.execute(select(tables.documents)).first() is None
                assert connection.execute(select(tables.test_report_import_batches)).first() is None
            assert app.dependency_overrides[get_document_object_store]().objects == {}
    finally:
        scope.dispose()


def test_import_rechecks_original_session_version_after_request_wait(
    api_context: tuple[TestClient, FakeGateway],
    isolated_import_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.test_report_import import TestReportImportService

    client, gateway = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        headers = bearer_headers(client)
        original = TestReportImportService._start_import_serialized

        def rotated(
            service: TestReportImportService,
            *,
            tenant_id: UUID,
            actor_user_id: UUID,
            project_id: UUID,
            plan_id: UUID,
            filename: str,
            content: bytes,
            auth_version: int | None,
            queued_run_id: UUID | None = None,
            queued_mapping: ExcelImportMapping | None = None,
        ) -> ImportBatchResult:
            with scope.engine.begin() as connection:
                connection.execute(
                    tables.users.update()
                    .where(tables.users.c.id == scope.owner_id)
                    .values(auth_version=tables.users.c.auth_version + 1)
                )
            return original(
                service,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
                plan_id=plan_id,
                filename=filename,
                content=content,
                auth_version=auth_version,
                queued_run_id=queued_run_id,
                queued_mapping=queued_mapping,
            )

        monkeypatch.setattr(TestReportImportService, "_start_import_serialized", rotated)
        content = build_report([("Endurance 500h", "SN-001", "PASS", 0.05, "ok")])
        denied = upload(client, headers, ids["project_id"], ids["plan_id"], content)
        assert denied.status_code == 403 and gateway.calls == 0
        assert app.dependency_overrides[get_document_object_store]().objects == {}
    finally:
        scope.dispose()


@pytest.mark.parametrize("change_prompt", [False, True, "body"])
def test_successful_mapping_survives_business_rollback_without_new_model_request(
    api_context: tuple[TestClient, FakeGateway],
    isolated_import_database: str,
    monkeypatch: pytest.MonkeyPatch,
    change_prompt: bool | Literal["body"],
) -> None:
    import app.domain.test_report_import as importer

    client, gateway = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        headers = bearer_headers(client)
        content = build_report([("Endurance 500h", "SN-001", "PASS", 0.05, "ok")])
        original = importer.TestReportImportService._parse_import

        def fail(
            service: importer.TestReportImportService,
            connection: Connection,
            *,
            tenant_id: UUID,
            actor_user_id: UUID,
            project_id: UUID,
            plan_id: UUID,
            plan: RowMapping,
            document: DocumentRecord,
            content: bytes,
            prepared_mapping: ExcelImportMapping | None,
            corrected_mapping: ExcelImportMapping | None = None,
            revision: ImportRevision | None = None,
        ) -> NoReturn:
            raise importer.ImportError_("IMPORT_TEST_ROLLBACK", "synthetic failure after mapping")

        monkeypatch.setattr(importer.TestReportImportService, "_parse_import", fail)
        assert (
            upload(client, headers, ids["project_id"], ids["plan_id"], content).status_code == 422
        )
        with scope.engine.connect() as c:
            run = c.execute(select(tables.agent_runs)).mappings().one()
            assert run["event_count"] == 0 and run["subscription_id"] is None
            assert run["status"] == "succeeded" and run["requested_by_user_id"] == scope.owner_id
            assert "sample_rows" not in run["run_context"]["mapping_request"]
            assert c.execute(select(tables.documents)).first() is None
            assert c.execute(select(tables.test_report_import_batches)).first() is None
        monkeypatch.setattr(importer.TestReportImportService, "_parse_import", original)
        if change_prompt:
            monkeypatch.setattr(
                importer,
                "IMPORT_PROMPT",
                importer.IMPORT_PROMPT.model_copy(
                    update=(
                        {"instruction": "synthetic changed instructions without a version bump"}
                        if change_prompt == "body"
                        else {"version": "synthetic-new-prompt"}
                    )
                ),
            )
        repeated = upload(client, headers, ids["project_id"], ids["plan_id"], content)
        assert repeated.status_code == (409 if change_prompt else 201), repeated.text
        assert gateway.calls == 1
        with scope.engine.connect() as c:
            assert len(list(c.execute(select(tables.agent_runs)))) == 1
    finally:
        scope.dispose()


@pytest.mark.parametrize("unexpected", [False, True])
def test_failed_mapping_request_is_not_redispatched_on_same_upload(
    api_context: tuple[TestClient, FakeGateway],
    isolated_import_database: str,
    monkeypatch: pytest.MonkeyPatch,
    unexpected: bool,
) -> None:
    client, gateway = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        headers = bearer_headers(client)
        content = build_report([("Endurance 500h", "SN-001", "PASS", 0.05, "ok")])

        def fail[OutputT: BaseModel](
            invocation: GatewayInvocation, output_type: type[OutputT]
        ) -> GatewayResult[OutputT]:
            gateway.calls += 1
            if unexpected:
                raise RuntimeError("synthetic response interruption")
            return GatewayResult(
                status="degraded",
                output=None,
                error_code="PROVIDER_TIMEOUT",
                structured_attempts=1,
                removed_context_paths=(),
                invocation_id=uuid4(),
            )

        monkeypatch.setattr(gateway, "invoke_structured", fail)
        if unexpected:
            with pytest.raises(RuntimeError, match="synthetic response"):
                upload(client, headers, ids["project_id"], ids["plan_id"], content)
        else:
            assert (
                upload(client, headers, ids["project_id"], ids["plan_id"], content).status_code
                == 422
            )
        repeated = upload(client, headers, ids["project_id"], ids["plan_id"], content)
        assert repeated.status_code == 422 and gateway.calls == 1
        with scope.engine.connect() as c:
            run = c.execute(select(tables.agent_runs)).mappings().one()
            assert run["status"] == "degraded" and run["run_context"]["mapping_result"] is None
            assert c.execute(select(tables.documents)).first() is None
    finally:
        scope.dispose()


@pytest.mark.parametrize("stale_session", [False, True])
@pytest.mark.parametrize("row_count", [1, 7])
def test_import_actual_api_budget_factory_persists_same_run_trace_and_charge(
    api_context: tuple[TestClient, FakeGateway],
    isolated_import_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stale_session: bool,
    row_count: int,
) -> None:
    client, _ = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        headers = bearer_headers(client)
        path, _, digest = publication(tmp_path, qualified_input_limit=4000)
        calls: list[httpx2.Request] = []

        def respond(request: httpx2.Request) -> httpx2.Response:
            calls.append(request)
            return provider_response(MAPPING.model_dump_json())

        client_class = httpx2.Client
        monkeypatch.setattr(
            httpx2,
            "Client",
            lambda **kwargs: client_class(transport=httpx2.MockTransport(respond), **kwargs),
        )
        monkeypatch.setattr(
            application_gateway, "load_golden_qualifications", lambda *a, **kw: [qualification()]
        )
        environment = {
            "PDOS_LLM_PROVIDER": "minimax",
            "PDOS_LLM_MODEL": "MiniMax-M2.7",
            "PDOS_LLM_BASE_URL": "https://fake-openai.local/v1",
            "PDOS_LLM_API_KEY": "test-only",
            MODE_KEY: "budgeted",
            PROFILE_KEY: "short",
            METER_PATH_KEY: str(path),
            METER_DIGEST_KEY: digest,
        }

        def configured() -> Iterator[StructuredModelGateway]:
            with application_gateway.configured_application_gateway(
                scope.engine, environment
            ) as gateway:
                yield gateway

        app.dependency_overrides[get_application_gateway] = configured
        if stale_session:
            from app.ai import application_authorization

            original = application_authorization.issue_application_authorization

            def changed(
                connection: Connection,
                *,
                tenant_id: UUID,
                run_id: UUID,
                actor_user_id: UUID,
                purpose: str,
                auth_version: int | None = None,
            ) -> None:
                assert auth_version is not None
                connection.execute(
                    tables.users.update()
                    .where(tables.users.c.id == actor_user_id)
                    .values(auth_version=tables.users.c.auth_version + 1)
                )
                original(
                    connection,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    actor_user_id=actor_user_id,
                    purpose=purpose,
                    auth_version=auth_version,
                )

            monkeypatch.setattr(
                application_authorization, "issue_application_authorization", changed
            )
        content = build_report([("Endurance 500h", "SN-001", "PASS", 0.05, "ok")] * row_count)
        first = upload(client, headers, ids["project_id"], ids["plan_id"], content)
        if stale_session:
            assert first.status_code == 403, first.text
            assert calls == []
            with scope.engine.connect() as c:
                assert c.execute(select(tables.application_authorizations)).first() is None
                assert c.execute(select(tables.budget_run_links)).first() is None
            return
        assert first.status_code == 201, first.text
        repeated = upload(client, headers, ids["project_id"], ids["plan_id"], content)
        assert repeated.status_code == 200 and repeated.json()["id"] == first.json()["id"]
        with scope.engine.connect() as c:
            run = c.execute(select(tables.agent_runs)).mappings().one()
            trace = c.execute(select(tables.model_invocations)).mappings().one()
            link = c.execute(select(tables.budget_run_links)).mappings().one()
            authorization = c.execute(select(tables.application_authorizations)).mappings().one()
            assert authorization["run_id"] == run["id"]
            assert authorization["principal_id"] == run["requested_by_user_id"]
            assert authorization["body"]["purpose"] == "report_mapping"
            observation = (
                c.execute(select(tables.application_context_observations)).mappings().one()
            )
            manifest = c.execute(select(tables.application_context_manifests)).mappings().one()
            assert observation["metadata"]["total_count"] == row_count
            assert observation["metadata"]["shown_count"] == min(5, row_count)
            assert observation["metadata"]["truncated"] == (row_count > 5)
            assert observation["metadata"]["taint"] == "untrusted_external"
            assert manifest["body"]["completeness"] == ("partial" if row_count > 5 else "complete")
            assert manifest["observation_id"] == observation["id"]
            checkpoint = c.execute(select(tables.application_result_checkpoints)).mappings().one()
            assert checkpoint["manifest_id"] == manifest["id"]
            assert checkpoint["body"]["output"] == MAPPING.model_dump(mode="json")

            entries = list(
                c.execute(
                    select(tables.budget_journal).order_by(tables.budget_journal.c.revision)
                ).mappings()
            )
        assert len(calls) == 1 and len(entries) == 3
        assert run["id"] == trace["run_id"] == link["run_id"]
        assert str(trace["id"]) == run["run_context"]["model_invocation_id"]
        assert entries[-1]["charged_tokens"] == 10 and entries[-1]["held_tokens"] == 0
        assert run["status"] == "succeeded"
    finally:
        scope.dispose()


@pytest.mark.parametrize(
    "changes",
    [
        {"context_version": "run-context-v2"},
        {"request_id": None},
        {"requested_by_user_id": None},
        {"event_count": 1},
    ],
)
def test_event_free_mapping_requires_server_purpose_and_user_identity(
    api_context: tuple[TestClient, FakeGateway],
    isolated_import_database: str,
    changes: dict[str, object],
) -> None:
    client, _ = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        headers = bearer_headers(client)
        content = build_report([("Endurance 500h", "SN-001", "PASS", 0.05, "ok")])
        assert (
            upload(client, headers, ids["project_id"], ids["plan_id"], content).status_code == 201
        )
        with scope.engine.connect() as c:
            row = dict(c.execute(select(tables.agent_runs)).mappings().one())
        now = datetime.now(UTC)
        row.update(id=uuid4(), request_id=str(uuid4()), window_started_at=now, window_ended_at=now)
        row.update(changes)
        with pytest.raises(IntegrityError) as denied, scope.engine.begin() as c:
            c.execute(tables.agent_runs.insert().values(**row))
        assert isinstance(denied.value.orig, PsycopgError)
        assert denied.value.orig.sqlstate == "23514"
        assert denied.value.orig.diag.constraint_name == "ck_agent_runs_event_bounds_consistent"
    finally:
        scope.dispose()


def test_legacy_duplicates_prefer_confirmed_batch_without_deleting_history(
    api_context: tuple[TestClient, FakeGateway],
    isolated_import_database: str,
) -> None:
    client, _ = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        headers = bearer_headers(client)
        content = build_report([("Endurance 500h", "SN-001", "PASS", 0.05, "ok")])
        first = upload(client, headers, ids["project_id"], ids["plan_id"], content).json()
        with scope.engine.begin() as connection:
            batch = dict(
                connection.execute(select(tables.test_report_import_batches)).mappings().one()
            )
            batch["id"] = uuid4()
            connection.execute(tables.test_report_import_batches.insert().values(**batch))
        record_execution_dates(client, headers, ids["project_id"], batch["id"])
        confirmed = client.post(
            f"/api/projects/{ids['project_id']}/npi/test-imports/{batch['id']}/confirm",
            headers=headers,
        )
        assert confirmed.status_code == 200
        repeated = upload(client, headers, ids["project_id"], ids["plan_id"], content)
        assert repeated.status_code == 200
        assert repeated.json()["id"] == str(batch["id"]) != first["id"]
        assert repeated.json()["status"] == "confirmed"
        with scope.engine.connect() as connection:
            assert len(list(connection.execute(select(tables.test_report_import_batches)))) == 2
    finally:
        scope.dispose()
