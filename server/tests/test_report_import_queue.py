"""HTTP upload receipts, staged files and original-call recovery."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import text

from app.ai.application_gateway import configured_application_gateway
from app.ai.gateway import GatewayInvocation, GatewayResult, StructuredModelGateway
from app.ai.report_import_queue import ReportImportQueue
from app.db.engine import get_engine
from app.db.schema import tables
from app.main import app
from app.storage.documents import get_document_object_store
from tests.test_application_leases import expire
from tests.test_application_run_budget_api import factory
from tests.test_application_waits import rows
from tests.test_model_budget_controller import evidence
from tests.test_test_report_import_api import (
    MAPPING,
    FakeObjectStore,
    Scope,
    bearer_headers,
    build_report,
    record_execution_dates,
)
from tests.test_test_report_import_api import isolated_import_database as isolated_import_database


class Store(FakeObjectStore):
    def get(self, *, object_key: str, max_bytes: int) -> bytes:
        content = self.objects[object_key]
        assert len(content) <= max_bytes
        return content


QueuedImport = tuple[
    TestClient,
    dict[str, str],
    Scope,
    dict[str, UUID],
    dict[str, str],
    list[httpx2.Request],
    Store,
    bytes,
]


@pytest.fixture
def queued_import(
    isolated_import_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> Iterator[QueuedImport]:
    store = Store()
    app.dependency_overrides[get_document_object_store] = lambda: store
    with TestClient(app) as client:
        scope = Scope(client, isolated_import_database)
        ids = scope.seed()
        original = StructuredModelGateway.invoke_structured
        env, calls, _ = factory(
            get_engine(), tmp_path, monkeypatch, request=request, output=MAPPING.model_dump()
        )
        monkeypatch.setattr(StructuredModelGateway, "invoke_structured", original)
        content = build_report([("Leak test", "SN-001", "PASS", 0.05, "ok")])
        try:
            yield client, bearer_headers(client), scope, ids, env, calls, store, content
        finally:
            scope.dispose()


def submit(
    q: QueuedImport, filename: str = "report.xlsx", content: bytes | None = None
) -> dict[str, object]:
    client, headers, _, ids, _, _, _, original = q
    result = client.post(
        f"/api/projects/{ids['project_id']}/npi/test-import-requests",
        headers=headers,
        data={"plan_id": str(ids["plan_id"])},
        files={
            "file": (
                filename,
                content or original,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert result.status_code == 202, result.text
    return evidence(result.json())


def read(q: QueuedImport, run: object) -> dict[str, object]:
    assert isinstance(run, str)
    client, headers, _, ids, *_ = q
    result = client.get(
        f"/api/projects/{ids['project_id']}/npi/test-import-requests/{run}", headers=headers
    )
    assert result.status_code == 200, result.text
    return evidence(result.json())


def work(q: QueuedImport) -> bool:
    with configured_application_gateway(get_engine(), q[4]) as gateway:
        return ReportImportQueue(get_engine(), object_store=q[6], gateway=gateway).run_next()


def test_upload_completes_in_background_and_confirmed_mapping_skips_queue(
    queued_import: QueuedImport,
) -> None:
    q = queued_import
    client, headers, scope, ids, _, calls, store, _ = q
    first = submit(q)
    assert first["status"] == "queued" and first["batch"] is None
    assert submit(q, "renamed.xlsx") == first
    assert len(store.objects) == 1 and not calls and not rows(tables.application_run_leases)
    assert work(q) and not work(q)
    result = read(q, first["run_id"])
    batch = evidence(result["batch"])
    created_run_ids = batch["created_run_ids"]
    assert isinstance(created_run_ids, list)
    assert result["status"] == "completed" and batch["status"] == "parsed", result
    assert len(created_run_ids) == 1 and len(calls) == 1
    assert scope.case(ids["leak_id"])["status"] == "planned"
    assert len(store.objects) == 1 and "/documents/" in next(iter(store.objects))
    assert rows(tables.application_import_inputs)[0]["released_at"] is not None
    record_execution_dates(client, headers, ids["project_id"], batch["id"])
    confirm = client.post(
        f"/api/projects/{ids['project_id']}/npi/test-imports/{batch['id']}/confirm",
        headers=headers,
    )
    assert confirm.status_code == 200, confirm.text
    replay = submit(q, "again.xlsx")
    replay_batch = evidence(replay["batch"])
    assert replay_batch["reused_existing"] and replay_batch["status"] == "confirmed"
    known = submit(q, content=build_report([("Leak test", "SN-001", "PASS", 0.04, "next")]))
    assert known["run_id"] is None and known["status"] == "completed"
    assert len(calls) == 1 and len(rows(tables.application_import_inputs)) == 1


def test_cancel_cleans_staged_file_without_model_or_batch(queued_import: QueuedImport) -> None:
    q = queued_import
    first = submit(q)
    response = q[0].post(f"/api/ai/runs/{first['run_id']}/cancel", headers=q[1])
    assert response.status_code == 200, response.text
    assert work(q) and not work(q)
    assert read(q, first["run_id"])["status"] == "cancelled"
    assert not q[5] and not q[6].objects and not rows(tables.test_report_import_batches)


def test_recovers_saved_mapping_without_second_model_call(
    queued_import: QueuedImport, monkeypatch: pytest.MonkeyPatch
) -> None:
    q = queued_import
    first = submit(q)
    original = StructuredModelGateway.invoke_structured
    interrupted = False

    def stop_after_result[OutputT: BaseModel](
        gateway: StructuredModelGateway, invocation: GatewayInvocation, output_type: type[OutputT]
    ) -> GatewayResult[OutputT]:
        nonlocal interrupted
        result = original(gateway, invocation, output_type)
        if not interrupted:
            interrupted = True
            assert invocation.run_id is not None
            expire(get_engine(), invocation.run_id)
            with get_engine().begin() as c:
                c.execute(text("SELECT cehub_ai.expire_application_runs(100)"))
            raise RuntimeError("synthetic exit after mapping result")
        return result

    monkeypatch.setattr(StructuredModelGateway, "invoke_structured", stop_after_result)
    assert work(q)
    assert read(q, first["run_id"])["status"] == "queued"
    assert rows(tables.application_import_inputs)[0]["resolved_at"] is None
    assert work(q) and not work(q)
    assert read(q, first["run_id"])["status"] == "completed"
    assert len(q[5]) == 1 and len(rows(tables.test_report_import_batches)) == 1


def test_staged_file_changed_stops_before_model(queued_import: QueuedImport) -> None:
    q = queued_import
    first = submit(q)
    key = next(iter(q[6].objects))
    q[6].objects[key] = b"changed"
    assert work(q) and not work(q)
    result = read(q, first["run_id"])
    assert result["status"] == "failed" and result["error_code"] == "IMPORT_STAGED_FILE_CHANGED"
    assert not q[5] and not q[6].objects and not rows(tables.test_report_import_batches)


def test_sync_endpoint_does_not_claim_a_queued_upload(queued_import: QueuedImport) -> None:
    q = queued_import
    first = submit(q)
    result = q[0].post(
        f"/api/projects/{q[3]['project_id']}/npi/test-imports",
        headers=q[1],
        data={"plan_id": str(q[3]["plan_id"])},
        files={
            "file": (
                "same.xlsx",
                q[7],
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert result.status_code == 409, result.text
    assert not q[5] and read(q, first["run_id"])["status"] == "queued"
    assert work(q) and read(q, first["run_id"])["status"] == "completed"


def test_cancellation_after_mapping_prevents_draft_commit(
    queued_import: QueuedImport, monkeypatch: pytest.MonkeyPatch
) -> None:
    q = queued_import
    first = submit(q)
    original = StructuredModelGateway.invoke_structured

    def cancel_after_result[OutputT: BaseModel](
        gateway: StructuredModelGateway, invocation: GatewayInvocation, output_type: type[OutputT]
    ) -> GatewayResult[OutputT]:
        result = original(gateway, invocation, output_type)
        cancelled = q[0].post(f"/api/ai/runs/{first['run_id']}/cancel", headers=q[1])
        assert cancelled.status_code == 200, cancelled.text
        return result

    monkeypatch.setattr(StructuredModelGateway, "invoke_structured", cancel_after_result)
    assert work(q) and not work(q)
    assert read(q, first["run_id"])["status"] == "cancelled"
    assert len(q[5]) == 1 and not q[6].objects
    assert not rows(tables.test_report_import_batches)
