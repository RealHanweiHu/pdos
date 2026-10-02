"""Actual file extraction and durable synthetic model receipt -> atomic RFQ T1 draft intake."""

# ruff: noqa: F811
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, select
from sqlalchemy.exc import DBAPIError

from app.db.schema import tables
from app.main import app
from app.storage.documents import get_document_object_store
from tests.migration_fixtures import rollback_migration_operations
from tests.test_product_source_files_api import Store, setup
from tests.test_product_work_runs_api import (
    assert_wire_sources,
    configure,
    enable_test_only,
    output_for,
)
from tests.test_test_runs_api import Scope
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def test_rfq_fixed_file_receipt_single_confirmation_and_rollback(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    store = Store()
    app.dependency_overrides[get_document_object_store] = lambda: store
    try:
        base, headers, content, body = setup(client, scope)
        registered = client.post(base + "/source-files", headers=headers, json=body).json()
        path = base + "/source-files/" + registered["id"]
        assert client.put(path + "/upload", headers=headers, content=content).status_code == 200
        assert client.post(path + "/parse", headers=headers).status_code == 200
        selection = dict(
            capability="rfq_requirements",
            question="抽取压力要求，缺少条件保持未知",
            product_line_id=None,
            sources=[dict(kind="file", id=registered["id"], ordinals=[1])],
        )
        prepared = client.post(base + "/product-ai-context", headers=headers, json=selection)
        assert prepared.status_code == 200, prepared.text
        ref = next(
            r for r in prepared.json()["references"] if r["reference_id"].startswith("file:")
        )
        statement = dict(
            nature="observed",
            text="客户要求最大压力120 kPa",
            citations=[
                dict(
                    reference_id=ref["reference_id"],
                    digest=ref["digest"],
                    field_path=["text"],
                    quoted_value=ref["fields"]["text"],
                )
            ],
        )
        output = output_for("rfq_requirements")
        output.update(
            disposition="analysis",
            summary=[statement],
            requirements=[
                dict(
                    title="最大压力",
                    description="最大压力120 kPa；测试工况待澄清",
                    priority="high",
                    acceptance_criteria=[],
                    basis=statement,
                    missing=["测试方法和工况待澄清"],
                    category_label=None,
                )
            ],
        )
        calls = configure(scope, tmp_path, monkeypatch, output, request=request)
        run_request = dict(
            request_id=str(uuid4()), selection=selection, expected_digest=prepared.json()["digest"]
        )
        gated = client.post(base + "/product-ai-runs", headers=headers, json=run_request)
        assert gated.status_code == 409 and "CAPABILITY_SHADOW" in gated.text
        enable_test_only(monkeypatch, "rfq_requirements")
        run = client.post(base + "/product-ai-runs", headers=headers, json=run_request)
        assert run.status_code == 200 and run.json()["status"] == "succeeded", run.text
        assert len(calls) == 1
        assert_wire_sources(calls, prepared.json(), scope.tenant_id)
        read = client.post(
            base + "/rfq-ai-finding", headers=headers, json=dict(run_id=run.json()["run_id"])
        )
        assert read.status_code == 200, read.text
        finding = read.json()["finding"]
        assert finding["status"] == "pending_review"
        confirm = dict(
            run_id=run.json()["run_id"],
            finding_id=finding["id"],
            expected_digest=finding["proposed_digest"],
            decision="accepted",
            comment="核对原文后登记草稿",
            items=output["requirements"],
        )
        wrong = deepcopy(confirm)
        wrong["items"][0]["basis"]["citations"][0]["quoted_value"] = "fabricated"
        rejected = client.post(base + "/rfq-ai-confirm", headers=headers, json=wrong)
        assert rejected.status_code == 409, rejected.text
        # Late business write failure must roll back acceptance, first row, links and audit.
        from app.domain.requirements import RequirementService

        original = RequirementService.create_connection

        def fail_second(self: RequirementService, connection: Connection, **kwargs: Any) -> Any:
            if kwargs["draft"].code.endswith("-02"):
                raise ValueError("injected last-row failure")
            return original(self, connection, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(RequirementService, "create_connection", fail_second)
            batch = deepcopy(confirm)
            batch["items"] *= 2
            with pytest.raises(ValueError, match="injected last-row"):
                client.post(base + "/rfq-ai-confirm", headers=headers, json=batch)
        with scope.engine.connect() as c:
            assert (
                c.execute(select(func.count()).select_from(tables.requirements)).scalar_one() == 0
            )
            assert (
                c.execute(
                    select(tables.findings.c.status).where(
                        tables.findings.c.id == UUID(finding["id"])
                    )
                ).scalar_one()
                == "pending_review"
            )
        applied = client.post(base + "/rfq-ai-confirm", headers=headers, json=confirm)
        assert applied.status_code == 200, applied.text
        assert applied.json()["finding"]["status"] == "applied"
        assert (
            client.post(base + "/rfq-ai-confirm", headers=headers, json=confirm).json()
            == applied.json()
        )
        with scope.engine.connect() as c:
            requirement = c.execute(select(tables.requirements)).mappings().one()
            assert requirement["status"] == "draft" and requirement["acceptance_criteria"] == []
            assert requirement["customer_id"] is None
            assert c.execute(select(func.count()).select_from(tables.projects)).scalar_one() == 0
            link = c.execute(select(tables.product_rfq_requirement_links)).mappings().one()
            assert link["accepted_item"]["missing"] and link["accepted_item"]["basis"] == statement
        with pytest.raises(DBAPIError), scope.engine.begin() as c:
            c.execute(tables.product_rfq_requirement_links.update().values(accepted_item={}))
        with (
            pytest.raises(DBAPIError, match="Retain RFQ"),
            rollback_migration_operations(scope.engine),
        ):
            import_module("migrations.versions.0404_product_rfq_requirements").downgrade()
        # A fresh request can never confirm against a revoked original.
        run_request["request_id"] = str(uuid4())
        newer = client.post(base + "/product-ai-runs", headers=headers, json=run_request)
        assert newer.status_code == 200, newer.text
        pending = client.post(
            base + "/rfq-ai-finding", headers=headers, json=dict(run_id=newer.json()["run_id"])
        ).json()["finding"]
        assert client.post(path + "/revoke", headers=headers).status_code == 200
        confirm.update(
            run_id=newer.json()["run_id"],
            finding_id=pending["id"],
            expected_digest=pending["proposed_digest"],
        )
        refused = client.post(base + "/rfq-ai-confirm", headers=headers, json=confirm)
        assert refused.status_code == 409, refused.text
    finally:
        app.dependency_overrides.pop(get_document_object_store, None)
        scope.engine.dispose()
