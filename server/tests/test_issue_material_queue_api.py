"""Material event queue over real domain/API/database actions; synthetic supply/model."""

# ruff: noqa: F811
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.ai.application_gateway import configured_application_gateway
from app.ai.issue_event_queue import IssueEventQueue
from app.db.schema import tables
from tests import test_application_budget_factory as factory
from tests.test_application_budget_factory import factory_setup  # noqa: F401
from tests.test_issue_event_queue_api import controls
from tests.test_issue_event_runs_api import fixture_meter, live  # noqa: F401
from tests.test_model_budget_controller import response
from tests.test_test_runs_api import (
    Scope,
    bearer_headers,
    client,  # noqa: F401
    isolated_test_run_database,  # noqa: F401
)


def seed_supply(scope: Scope, project: UUID, quantity: int) -> None:
    """Synthetic import originals, never real ERP or uploaded user material."""
    now = datetime.now(UTC)
    document = scope._insert(
        tables.documents,
        dict(
            project_id=project,
            uploaded_by_user_id=scope.owner_id,
            object_key=f"synthetic/{uuid4()}",
            filename="synthetic-supply.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            classification="internal",
            size_bytes=1,
            sha256="a" * 64,
            extraction_status="preview_only",
        ),
    )
    batch, snapshot = uuid4(), uuid4()
    with scope.engine.begin() as c:
        c.execute(
            tables.supply_import_batches.insert().values(
                id=batch,
                tenant_id=scope.tenant_id,
                project_id=project,
                document_id=document,
                document_digest="a" * 64,
                source_system="synthetic-test",
                source_version=str(uuid4()),
                as_of=now,
                fresh_until=now + timedelta(days=1),
                captured_at=now,
                configuration={"coverage": "synthetic single pool"},
                content_digest="b" * 64,
                created_by_user_id=scope.owner_id,
                request_id=uuid4(),
                request_digest="c" * 64,
                reason="隔离测试供给",
                row_count=1,
                ignored_rows=[],
            )
        )
        c.execute(
            tables.supply_snapshots.insert().values(
                id=snapshot,
                tenant_id=scope.tenant_id,
                project_id=project,
                batch_id=batch,
                external_pool_id="POOL-1",
                external_item_id="MAT-01",
                quantity=quantity,
                unit="pcs",
                availability="known",
                supply_kind="on_hand",
                quality_status="released",
                source_row=2,
                raw_cells={"A2": "MAT-01"},
                contract={
                    "id": str(snapshot),
                    "tenant_id": str(scope.tenant_id),
                    "scope": {"kind": "project", "ref_id": str(project)},
                    "source_system": "synthetic-test",
                    "external_item_id": "MAT-01",
                    "unit": "pcs",
                    "availability": "known",
                    "quantity": str(quantity),
                    "as_of": now.isoformat(),
                    "fresh_until": (now + timedelta(days=1)).isoformat(),
                    "sources": [{"ref_id": str(document), "digest": "a" * 64}],
                },
            )
        )


def material_fixture(
    client: TestClient, scope: Scope, project: UUID, headers: dict[str, str]
) -> dict[str, Any]:
    build = scope._insert(
        tables.build_batches,
        dict(
            project_id=project,
            workflow_id=scope.workflow_id,
            stage_id=scope.stage_id,
            created_by_user_id=scope.owner_id,
            phase="evt",
            code="BUILD-MATERIAL",
            planned_quantity=4,
        ),
    )
    bom = scope._insert(
        tables.development_boms,
        dict(
            project_id=project,
            created_by_user_id=scope.owner_id,
            bom_type="prototype",
            code="PBOM-MATERIAL",
            name="Synthetic material BOM",
        ),
    )
    scope._insert(
        tables.development_bom_items,
        dict(
            project_id=project,
            bom_id=bom,
            line_number=1,
            part_number="PART-01",
            description="Synthetic part",
            quantity=1,
            unit="pcs",
            material_reference="MAT-01",
        ),
    )
    calendar = client.post(
        "/api/planning/calendars",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_version": 0,
            "name": "Synthetic calendar",
            "timezone": "UTC",
            "working_weekdays": [0, 1, 2, 3, 4],
            "intervals": [{"start_minute": 540, "end_minute": 1020}],
            "reason": "隔离测试",
        },
    )
    assert calendar.status_code == 200, calendar.text
    node_base = f"/api/projects/{project}/execution/nodes"
    choices = client.get(node_base, headers=headers)
    assert choices.status_code == 200, choices.text
    choice = next(x for x in choices.json()["sources"] if x["id"] == str(build))
    registered = client.post(
        node_base,
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "node_kind": "build",
            "source_id": str(build),
            "expected_source_digest": choice["source_digest"],
            "calendar_version_id": calendar.json()["id"],
        },
    )
    assert registered.status_code == 200, registered.text
    node = registered.json()["id"]
    base = f"/api/projects/{project}/npi"
    selection = {"bom_id": str(bom), "need_by_node_id": str(node)}
    preview = client.post(
        f"{base}/builds/{build}/materials/preview", headers=headers, json=selection
    )
    assert preview.status_code == 200, preview.text
    frozen = client.post(
        f"{base}/builds/{build}/materials/freeze",
        headers=headers,
        json={
            **selection,
            "request_id": str(uuid4()),
            "expected_digest": preview.json()["digest"],
            "reason": "隔离测试固定需求",
        },
    )
    assert frozen.status_code == 200, frozen.text
    seed_supply(scope, project, 0)
    coverage = client.post(
        f"{base}/builds/{build}/supply-allocations/coverage-preview", headers=headers, json={}
    )
    assert coverage.status_code == 200, coverage.text
    material = coverage.json()["materials"][0]
    assert float(material["observed_on_hand_gap"]) == 4
    created = client.post(
        f"{base}/builds/{build}/material-exceptions",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_digest": coverage.json()["digest"],
            "material_key": material["material_key"],
            "selection": {},
            "title": "隔离测试物料缺口",
            "severity": "medium",
            "reason": "核对现货缺口",
        },
    )
    assert created.status_code == 200, created.text
    return dict(created.json())


def review(
    client: TestClient, base: str, exception: dict[str, Any], headers: dict[str, str]
) -> None:
    path = f"{base}/npi/material-exceptions/{exception['id']}"
    current = client.get(path, headers=headers)
    assert current.status_code == 200, current.text
    saved = client.post(
        path + "/review",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_version": current.json()["latest"]["version"],
            "expected_digest": current.json()["current"]["digest"],
            "selection": {},
            "disposition": "follow_up",
            "reason": "隔离测试再次核对",
        },
    )
    assert saved.status_code == 200, saved.text


@pytest.mark.parametrize("scenario", ["recovery", "pending"])
def test_material_confirm_review_stale_queue_and_recovery(
    client: TestClient,
    isolated_test_run_database: str,
    factory_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        live(monkeypatch)
        project, headers = scope.project(), bearer_headers(client)
        with scope.engine.begin() as c:
            c.execute(
                tables.projects.update()
                .where(tables.projects.c.id == project)
                .values(current_stage_id=scope.stage_id)
            )
        controls(client, project, headers)
        exception = material_fixture(client, scope, project, headers)
        base = f"/api/projects/{project}"
        environment, calls, _ = factory_setup
        output = {
            "disposition": "reuse_issue",
            "existing_issue_id": exception["issue_id"],
            "citations": [
                {
                    "reference_id": "material.original.shortage",
                    "exact_quote": (
                        "物料：MAT-01；已登记范围现货缺口：4.00000000 pcs；"
                        "固定需求：4.000000 pcs"
                    ),
                }
            ],
        }
        monkeypatch.setattr(
            factory, "response", lambda: response(json.dumps(output, ensure_ascii=False))
        )
        with configured_application_gateway(scope.engine, environment) as gateway:
            queue = IssueEventQueue(scope.engine, gateway)
            queued = queue.dispatch_once()
            assert queued.queued_count == 1, queued
            assert not calls
            assert queue.execute_next()
            assert len(calls) == 1
            sources = client.get(base + "/ai-issue-event-sources", headers=headers).json()["items"]
            assert sources[0]["source_kind"] == "material_exception"
            assert sources[0]["source_status"] == "current", sources
            attention = client.get(base + "/ai-issue-event-runs?attention=true", headers=headers)
            assert attention.status_code == 200, attention.text
            run = attention.json()["items"][0]
            assert run["status"] == "succeeded", run
            if scenario == "pending":
                assert run["write_execution"]["route"] == "confirm"
                with scope.engine.connect() as c:
                    assert (
                        c.execute(
                            select(func.count()).select_from(tables.ai_issue_applications)
                        ).scalar_one()
                        == 0
                    )
                    assert (
                        c.execute(select(func.count()).select_from(tables.issues)).scalar_one() == 1
                    )
                return
            applied = client.post(
                base + "/ai-issue-applications/" + run["run_id"],
                headers=headers,
                json={
                    "request_id": str(uuid4()),
                    "result_id": run["result_id"],
                    "expected_digest": run["source_digest"],
                },
            )
            assert applied.status_code == 200, applied.text
            assert (
                client.get(base + "/ai-issue-event-runs?attention=true", headers=headers).json()[
                    "items"
                ]
                == []
            )
            review(client, base, exception, headers)
            assert queue.dispatch_once().queued_count == 1
            # A newer human review invalidates the already queued source before any model call.
            review(client, base, exception, headers)
            assert queue.execute_next()
            assert len(calls) == 1
            stale = client.get(base + "/ai-issue-event-runs", headers=headers).json()["items"][0]
            # The source already has an application; further reviews stay in source history,
            # rather than reopening the same Issue as another confirmation task.
            assert (
                client.get(base + "/ai-issue-event-runs?attention=true", headers=headers).json()[
                    "items"
                ]
                == []
            )
            assert stale["status"] == "failed", stale
            assert queue.dispatch_once().queued_count == 1
            assert queue.execute_next()
            assert len(calls) == 2
            # Supply recovery is independently observed; it never closes the original Issue.
            seed_supply(scope, project, 4)
            review(client, base, exception, headers)
            skipped = queue.dispatch_once()
            assert skipped.skipped_count == 1 and skipped.queued_count == 0, skipped
            assert not queue.execute_next()
            assert queue.dispatch_once().scanned_event_count == 0
        sources = client.get(base + "/ai-issue-event-sources", headers=headers).json()["items"]
        assert len(sources) == 4
        assert all(item["source_status"] == "changed" for item in sources), sources
        for source in sources:
            history = client.get(
                base + "/ai-issue-event-history",
                headers=headers,
                params={"event_row_id": source["event_row_id"]},
            )
            assert history.status_code == 200, history.text
            assert len(history.json()["items"]) == 1
        with scope.engine.connect() as c:
            assert c.execute(select(func.count()).select_from(tables.issues)).scalar_one() == 1
            assert c.execute(select(tables.issues.c.status)).scalar_one() == "open"
        assert len(calls) == 2
    finally:
        scope.dispose()
