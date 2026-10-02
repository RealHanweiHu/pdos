"""Actual PDF/XLSX parsing before project creation, with private scoped sources."""

# ruff: noqa: F811
from hashlib import sha256
from importlib import import_module
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from pypdf import PdfWriter
from reportlab.pdfgen.canvas import Canvas  # type: ignore[import-untyped]
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.db.schema import tables
from app.main import app
from app.storage.documents import get_document_object_store
from tests.migration_fixtures import rollback_migration_operations
from tests.test_product_work_preparation_api import space
from tests.test_test_runs_api import PASSWORD, Scope, bearer_headers
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


class Store:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, *, object_key: str, content: bytes, **kwargs: Any) -> None:
        self.objects[object_key] = content

    def get(self, *, object_key: str, max_bytes: int) -> bytes:
        return self.objects[object_key]

    def delete(self, *, object_key: str) -> None:
        self.objects.pop(object_key, None)


def document(kind: str) -> bytes:
    output = BytesIO()
    if kind == "xlsx":
        wb = Workbook()
        sheet = wb.active
        assert sheet is not None
        sheet.append(["RFQ", "Maximum pressure", "120 kPa"])
        wb.save(output)
    elif kind == "scan":
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.write(output)
    else:
        canvas = Canvas(output)
        canvas.drawString(40, 700, "RFQ: Maximum pressure 120 kPa")
        canvas.save()
    return output.getvalue()


def setup(
    client: TestClient, scope: Scope, kind: str = "xlsx"
) -> tuple[str, dict[str, str], bytes, dict[str, Any]]:
    headers = bearer_headers(client)
    sid = space(client, headers)
    base = f"/api/product-work/spaces/{sid}"
    content = document(kind)
    body = dict(
        request_id=str(uuid4()),
        filename="customer." + ("xlsx" if kind == "xlsx" else "pdf"),
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
        classification="internal",
    )
    return base, headers, content, body


@pytest.mark.parametrize("kind", ["pdf", "xlsx"])
def test_source_file_registration_upload_parse_and_immutable_origin(
    client: TestClient, isolated_test_run_database: str, kind: str
) -> None:
    scope = Scope(client, isolated_test_run_database)
    store = Store()
    app.dependency_overrides[get_document_object_store] = lambda: store
    try:
        base, headers, content, body = setup(client, scope, kind)
        registered = client.post(base + "/source-files", headers=headers, json=body)
        assert registered.status_code == 201, registered.text
        row = registered.json()
        path = base + "/source-files/" + row["id"]
        assert "object_key" not in row
        assert (
            client.post(base + "/source-files", headers=headers, json=body).json()["id"]
            == row["id"]
        )
        assert client.put(path + "/upload", headers=headers, content=b"wrong").status_code == 409
        assert client.post(path + "/parse", headers=headers).status_code == 409
        uploaded = client.put(path + "/upload", headers=headers, content=content)
        assert uploaded.status_code == 200 and uploaded.json()["status"] == "uploaded", (
            uploaded.text
        )
        parsed = client.post(path + "/parse", headers=headers)
        assert parsed.status_code == 200 and parsed.json()["status"] == "extracted", parsed.text
        detail = client.get(path, headers=headers).json()
        assert detail["fragments"] and "120" in str(detail["fragments"])
        assert ("page:" if kind == "pdf" else "sheet:") in str(detail["fragments"])
        assert (
            client.post(path + "/parse", headers=headers).json()["version"]
            == parsed.json()["version"]
        )
        with scope.engine.connect() as c:
            assert c.execute(select(func.count()).select_from(tables.projects)).scalar_one() == 0
            file = (
                c.execute(
                    select(tables.product_source_files).where(
                        tables.product_source_files.c.id == UUID(row["id"])
                    )
                )
                .mappings()
                .one()
            )
            assert store.objects[file["object_key"]] == content
        with pytest.raises(DBAPIError), scope.engine.begin() as c:
            c.execute(
                tables.product_source_files.update()
                .where(tables.product_source_files.c.id == UUID(row["id"]))
                .values(fragments=[], version=4)
            )
        assert client.post(path + "/revoke", headers=headers).json()["revoked_at"]
        assert client.get(path, headers=headers).json()["fragments"] == []
        assert client.post(path + "/parse", headers=headers).status_code == 409
        with pytest.raises(DBAPIError), rollback_migration_operations(scope.engine):
            import_module("migrations.versions.0403_product_source_files").downgrade()
    finally:
        app.dependency_overrides.pop(get_document_object_store, None)
        scope.dispose()


def test_source_file_private_scope_failed_storage_and_scanned_pdf(
    client: TestClient, isolated_test_run_database: str
) -> None:
    scope = Scope(client, isolated_test_run_database)
    store = Store()
    app.dependency_overrides[get_document_object_store] = lambda: store
    try:
        base, headers, content, body = setup(client, scope, "scan")
        response = client.post(base + "/source-files", headers=headers, json=body)
        assert response.status_code == 201, response.text
        row = response.json()
        path = base + "/source-files/" + row["id"]
        assert client.put(path + "/upload", headers=headers, content=content).status_code == 200
        key = next(iter(store.objects))
        store.objects[key] = b"corrupted"
        parsed = client.post(path + "/parse", headers=headers)
        assert parsed.status_code == 200 and parsed.json()["status"] == "failed"
        store.objects[key] = content
        assert client.post(path + "/parse", headers=headers).json()["status"] == "ocr_required"
        member = uuid4()
        with scope.engine.begin() as c:
            password = c.execute(
                select(tables.users.c.password_hash).where(tables.users.c.id == scope.owner_id)
            ).scalar_one()
            c.execute(
                tables.users.insert().values(
                    id=member,
                    tenant_id=scope.tenant_id,
                    username="other-pm",
                    display_name="Other PM",
                    role="project_manager",
                    password_hash=password,
                    is_active=True,
                )
            )
            c.execute(
                tables.market_space_members.insert().values(
                    tenant_id=scope.tenant_id,
                    market_space_id=UUID(base.rsplit("/", 1)[-1]),
                    user_id=member,
                    access="manager",
                    added_by_user_id=scope.owner_id,
                )
            )
        login = client.post(
            "/api/auth/login",
            json=dict(tenant_slug="beepump", username="other-pm", password=PASSWORD),
        )
        assert login.status_code == 200
        denied = {"Authorization": "Bearer " + login.json()["access_token"]}
        assert client.get(path, headers=denied).status_code == 403
        assert client.post(path + "/revoke", headers=denied).status_code == 403
        assert client.get(base + "/source-files", headers=denied).json()["items"] == []
    finally:
        app.dependency_overrides.pop(get_document_object_store, None)
        scope.dispose()


def test_rfq_preparation_requires_original_fragments_and_internal_scope(
    client: TestClient, isolated_test_run_database: str
) -> None:
    scope = Scope(client, isolated_test_run_database)
    store = Store()
    app.dependency_overrides[get_document_object_store] = lambda: store
    try:
        base, headers, content, body = setup(client, scope)
        for classification in ["confidential", "internal"]:
            body.update(request_id=str(uuid4()), classification=classification)
            file = client.post(base + "/source-files", headers=headers, json=body).json()
            path = base + "/source-files/" + file["id"]
            assert client.put(path + "/upload", headers=headers, content=content).status_code == 200
            assert client.post(path + "/parse", headers=headers).status_code == 200
            selection: dict[str, Any] = dict(
                capability="rfq_requirements",
                question="抽取原文要求",
                product_line_id=None,
                sources=[dict(kind="file", id=file["id"], ordinals=[1])],
            )
            response = client.post(base + "/product-ai-context", headers=headers, json=selection)
            assert response.status_code == (409 if classification == "confidential" else 200), (
                response.text
            )
            if classification == "internal":
                selection["sources"][0]["ordinals"] = [999]
                assert (
                    client.post(
                        base + "/product-ai-context", headers=headers, json=selection
                    ).status_code
                    == 409
                )
                selection["sources"][0]["ordinals"] = [1]
                selection["capability"] = "research_planning"
                assert (
                    client.post(
                        base + "/product-ai-context", headers=headers, json=selection
                    ).status_code
                    == 422
                )
        with scope.engine.connect() as c:
            assert (
                c.execute(select(func.count()).select_from(tables.model_invocations)).scalar_one()
                == 0
            )
    finally:
        app.dependency_overrides.pop(get_document_object_store, None)
        scope.engine.dispose()
